# -*- coding: utf-8 -*-
"""
b3 - Ablation della Transform (tasks_MPP n.5).

Rifa' in memoria i passi 1-3 di data_miner.data_miner (struttura -> pulizia/dizionario/fuzzy -> armonizzazione
regioni) per ogni VAR_CODE, una volta per configurazione, con uno step spento alla volta. Il codice della
pipeline non viene modificato: gli step si spengono sostituendo funzioni solo dentro questo processo.

Configurazioni
  full                    pipeline com'e' (riferimento)
  no_harmonization        salta il passo 3 di data_miner: harmonize_regions e aggregazione del Trentino
                          (PATCH_B3_ALLINEA_261029)
  no_structure            nessuna ricostruzione della struttura: ogni file (e ogni foglio non vuoto) e' una
                          tabella a se' (niente MS/MM, niente raggruppamento dei fogli, niente concatenazione)
  no_fuzzy                fuzzy spento (soglia 101) in input_cleaner (nomi canonici) e in fuzzy_labeler (file
                          consecutivi); il dizionario resta. Il raggruppamento dei fogli (88) e' struttura e resta
  no_dictionary           find_name_out_convention -> None (dizionario cols_attributes spento), fuzzy acceso
  no_dictionary_no_fuzzy  dizionario e fuzzy spenti
  no_numfmt               format_number -> identita' (niente pulizia dei formati numerici; resta to_numeric)

Misure (per tabella e per VAR_CODE, confrontate con full)
  righe            righe dopo l'export simulato (to_csv '|' + rilettura come stringhe + drop_duplicates, come il
                   passo 5); delta_righe = righe - righe di full (negativo = righe perse)
  righe_identiche  righe identiche tolte dal drop_duplicates
  dup_chiave       righe che ripetono la chiave della tabella full con lo stesso nome (chiave cercata come in
                   superkey_finder, ma con r <= --max-r e tempo limitato). chiave_assente = colonne della chiave
                   non presenti nella tabella (la tabella non si puo' unire per quella chiave)
  righe_cod_non_valido  righe con CODICE_REGIONE fuori dai codici NUTS di codregione_map.json (join falliti
                   con la dimensione territoriale); senza_codice_regione = tabella che in full ha
                   CODICE_REGIONE e qui no
  col_non_canoniche colonne con nome fuori dal vocabolario canonico (name_out)
  col_extra / col_mancanti  colonne in piu' / in meno rispetto a full (in piu' = nomi non riconciliati che la
                   concatenazione mette in colonne separate)
  indicatori_persi colonne numeriche canoniche presenti in full e assenti qui
  valori_num / somma_num  valori numerici leggibili e somma dei valori assoluti nelle colonne numeriche canoniche

Controllo: le tabelle di full vengono confrontate con data/output/<FONTE>/<snapshot>/ (righe e colonne).

NON scrive: data/output, info_<FONTE>.json, logs/fuzzy. Scrive solo experiments/B_ablation/out/ablation_*.xlsx.

Uso (da MEDITA):
  python experiments/B_ablation/ablation_transform.py --source MINIS
  python experiments/B_ablation/ablation_transform.py --source AIFA
Opzioni: --only VAR_CODE[,..]  --configs full,no_fuzzy,...  --max-r 3  --key-seconds 60
         --leggero  senza cache, export su file, tabelle liberate una alla volta (tabelle grandi)
         [PATCH_B3_MEMORIA_261030]
         --escludi-var VAR_CODE[,..] (default ALIM_EXCHANGE_VIVI)  --escludi-file nome[,..] (default il file ALIM
         del secondo semestre 2024, errore della fonte)   [PATCH_B3_ALLINEA_261029]
"""
import argparse
import contextlib
import gc  # PATCH_B3_MEMORIA_261030
import io
import os
import sys
import time
import traceback
import types
from itertools import combinations

HOME = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")).replace("\\", "/") + "/"
sys.path.insert(0, HOME)

import numpy as np
import pandas as pd

from scripts.modules import data_miner as dm_mod
from scripts.modules.data_miner import DataMiner
from scripts.modules.utils import excel_parser, datatable_cleaner, files_handler, sheets_handler
from scripts.modules.utils import nuts_region_harmonizer, fuzzy_log

CONFIGS = {
    "full":                   dict(harm=True,  struct=True,  fuzzy=True,  dict=True,  numfmt=True),
    "no_harmonization":       dict(harm=False, struct=True,  fuzzy=True,  dict=True,  numfmt=True),
    "no_structure":           dict(harm=True,  struct=False, fuzzy=True,  dict=True,  numfmt=True),
    "no_fuzzy":               dict(harm=True,  struct=True,  fuzzy=False, dict=True,  numfmt=True),
    "no_dictionary":          dict(harm=True,  struct=True,  fuzzy=True,  dict=False, numfmt=True),
    "no_dictionary_no_fuzzy": dict(harm=True,  struct=True,  fuzzy=False, dict=False, numfmt=True),
    "no_numfmt":              dict(harm=True,  struct=True,  fuzzy=True,  dict=True,  numfmt=False),
}
NULLS = {"", "nan", "NaN", "NAN", "None", "<NA>", "NaT"}


class _Log:
    """Sostituto del logger: tiene i messaggi in memoria."""
    def __init__(self):
        self.m = []

    def _w(self, x, *a, **k):
        self.m.append(str(x))

    debug = info = warning = error = critical = exception = _w


# ---------------------------------------------------------------- cache (stessi dati letti una volta per VAR_CODE)
PARSE_CACHE, XLS_CACHE, CLEAN_CACHE = {}, {}, {}
CURRENT = {"variant": None}
_orig_parse = excel_parser.ExcelParser.parse_file
_orig_read_excel = pd.read_excel
_orig_clean = datatable_cleaner.DataFrameCleaner.input_cleaner


def _parse_cached(self, parsing_log, log):
    k = self.file_path
    if k not in PARSE_CACHE:
        df, d, e, s, _ = _orig_parse(self, [], log)
        PARSE_CACHE[k] = (df, d, e, list(s))
    df, d, e, s = PARSE_CACHE[k]
    self.delim, self.encoding = d, e
    return df.copy(deep=True), d, e, list(s), parsing_log


def _read_excel_cached(io_, *args, **kw):
    if not isinstance(io_, str):
        return _orig_read_excel(io_, *args, **kw)
    k = (io_, repr(args), repr(sorted(kw.items(), key=lambda t: t[0])))
    if k not in XLS_CACHE:
        XLS_CACHE[k] = _orig_read_excel(io_, *args, **kw)
    v = XLS_CACHE[k]
    return {n: d.copy(deep=True) for n, d in v.items()} if isinstance(v, dict) else v.copy(deep=True)


def _clean_cached(self):
    """La pulizia dipende solo dal file/foglio e dalla variante (fuzzy, dizionario, formati)."""
    k = (fuzzy_log.CONTEXT["file"], fuzzy_log.CONTEXT["sheet"], CURRENT["variant"])
    if k not in CLEAN_CACHE:
        df, _ = _orig_clean(self)
        CLEAN_CACHE[k] = df
    return CLEAN_CACHE[k].copy(deep=True), self.log


def clear_caches():
    PARSE_CACHE.clear(); XLS_CACHE.clear(); CLEAN_CACHE.clear()
    fuzzy_log.RECORDS.clear()


_NOFUZZ = types.SimpleNamespace(ratio=lambda a, b: 0)
LEGGERO = {"on": False, "tmp": None}  # PATCH_B3_MEMORIA_261030: impostato da --leggero


def _iter_tables(tables):  # PATCH_B3_MEMORIA_261030: in modalita' leggera le tabelle escono dal dict una alla volta
    for name in list(tables):
        yield name, (tables.pop(name) if LEGGERO["on"] else tables[name])


@contextlib.contextmanager
def patched(cfg):
    saved = []

    def put(obj, name, val):
        saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, val)

    if not LEGGERO["on"]:  # PATCH_B3_MEMORIA_261030: in modalita' leggera niente cache
        put(excel_parser.ExcelParser, "parse_file", _parse_cached)
        put(pd, "read_excel", _read_excel_cached)
        put(datatable_cleaner.DataFrameCleaner, "input_cleaner", _clean_cached)
    if not cfg["fuzzy"]:
        put(datatable_cleaner, "FUZZY_THRESHOLD", 101)
        put(files_handler, "fuzz", _NOFUZZ)
    if not cfg["dict"]:
        for cls in (datatable_cleaner.DataFrameCleaner, files_handler.FilesHandler, sheets_handler.SheetsHandler):
            put(cls, "find_name_out_convention", lambda self, col: None)
    if not cfg["numfmt"]:
        put(datatable_cleaner.DataFrameCleaner, "format_number", lambda self, value: value)
    CURRENT["variant"] = (cfg["fuzzy"], cfg["dict"], cfg["numfmt"])
    try:
        yield
    finally:
        for obj, name, val in reversed(saved):
            setattr(obj, name, val)


# ---------------------------------------------------------------- passi 1-3 di data_miner (copia fedele)
def finish(dm, df, cfg, var_code):
    """Passo 3 (armonizzazione) e pulizia dei '-' del passo 4."""
    if cfg["harm"] and "CODICE_REGIONE" in df.columns:
        h = nuts_region_harmonizer.RegionHarmonizer(file_path=dm.codregione_path, log=dm.log, s=dm.source)
        df = h.harmonize_regions(df, numeric_cols=dm.numeric_cols)
        # PATCH_B3_ALLINEA_261029: come data_miner (PATCH_TRENTINO_SUPERKEY), stessa condizione
        if 'ELEN' not in var_code and dm.source != 'ISTAT' and set(dm.numeric_cols) & set(df.columns):
            df = h.aggregate_trentino_data(df, numeric_cols=dm.numeric_cols, conversions=dm.conversions)
    df = df.replace("-", np.nan)
    return df


def run_structured(dm, var_code, files, cfg):
    """Come data_miner.data_miner, passi 1-3, senza export: restituisce {nome_tabella: df}."""
    parsing_log, dfs_temp, output_files = [], [], []
    hank = DataMiner.architecture_definition(dm, var_code, files)
    if hank == "SINGLEOBJECT_MULTITABLES":
        raise RuntimeError("SINGLEOBJECT_MULTITABLES: data_miner si ferma (quit)")
    last_num = max(0, len(files) - 1)
    output_files.append(f"{dm.out_path}{var_code}.txt")
    unique_out_files = []
    for num, f_path in enumerate(files):
        f_in = os.path.basename(f_path)
        fuzzy_log.set_context(source=dm.source, snapshot=dm.last_request, var_code=var_code, file=f_in,
                              sheet='(primo foglio via parse_file, non usato in MM)' if hank == 'MULTIOBJECTS_MULTITABLES' else '')
        excelparser = excel_parser.ExcelParser(f_path)
        df, delim, enc, sheet_names, parsing_log = excelparser.parse_file(parsing_log, dm.log)
        dfclean = datatable_cleaner.DataFrameCleaner(df=df, log=parsing_log, col_MAP=dm.col_map)
        df_temp, parsing_log = dfclean.input_cleaner()

        if hank == 'SINGLEOBJECT_SINGLETABLE':
            dfs_temp.append(df_temp)

        if hank == 'MULTIOBJECTS_SINGLETABLE':
            if num == 0:
                dfs_handler = files_handler.FilesHandler(dm.col_map, parsing_log, dfs_temp, output_files)
            try:
                if num == 0:
                    df_prev = df_temp
                elif num == 1:
                    df_next = df_temp
                else:
                    df_prev = df_next
                    df_next = df_temp
                if num > 0:
                    dfs_temp, parsing_log = dfs_handler.fuzzy_labeler(num, df_prev, df_next)
            except UnboundLocalError:
                dfs_temp.append(df_temp)
            if num == last_num:
                dfs_temp = dfs_handler.harmonize_dataframes()

        if hank == 'MULTIOBJECTS_MULTITABLES':
            if num == 0:
                dfs_handler = files_handler.FilesHandler(dm.col_map, parsing_log, dfs_temp, output_files)
            if not sheet_names:
                dfs_temp.append([df_temp])
                output_files.append(f"{dm.out_path}{var_code}.txt")
            else:
                dh = sheets_handler.SheetsHandler(f_path, sheet_names, dm.out_path, var_code,
                                                  dfs_temp, output_files, parsing_log, dm.col_map)
                dfs_temp, output_files, parsing_log = dh.handle_multiple_sheets()
            output_files = [x for x in output_files if x.split('/')[-1].split('.')[0] != var_code]
            if num == last_num:
                dfs_temp = dfs_handler.harmonize_multisheetsfiles_dfs(dfs_temp)

        if var_code in ['AASL_STAFFLEX_TIPO']:
            output_files = [f'{dm.homepath}data/output/MINIS/{dm.last_request}/{var_code}.txt']
        unique_out_files = []
        for file in output_files:
            if file not in unique_out_files:
                unique_out_files.append(file)
        if len(unique_out_files) > 1:
            unique_out_files = [outf.replace(os.path.basename(outf), f"{var_code}{ii + 1}.txt")
                                for ii, outf in enumerate(unique_out_files)]

    if isinstance(dfs_temp, pd.DataFrame):
        dfs_temp = [dfs_temp]
    tables = {}
    for jj, df in enumerate(dfs_temp):
        try:
            df = pd.DataFrame(df[0])
        except KeyError:
            df = pd.DataFrame(df)
            for wa in ['level_0', 'index']:
                if wa in df.columns:
                    df = df.drop(columns=wa)
        name = os.path.basename(unique_out_files[jj])[:-4]
        tables[name] = finish(dm, df, cfg, var_code)  # PATCH_B3_ALLINEA_261029
    return tables, hank


def run_no_structure(dm, var_code, files, cfg):
    """Ogni file CSV e ogni foglio Excel non vuoto e' una tabella; stessa pulizia e armonizzazione."""
    tables = {}
    for i, f_path in enumerate(files):
        f_in = os.path.basename(f_path)
        ext = f_path.split('.')[-1].lower()
        if ext == 'csv':
            sheets = [None]
        else:
            eng = 'openpyxl' if ext == 'xlsx' else 'odf' if ext == 'ods' else 'xlrd'
            sheets = dm_mod._fogli_non_vuoti(f_path, eng)
        for j, sh in enumerate(sheets):
            fuzzy_log.set_context(source=dm.source, snapshot=dm.last_request, var_code=var_code, file=f_in,
                                  sheet='' if sh is None else str(sh))
            if sh is None or len(sheets) == 1:
                df = excel_parser.ExcelParser(f_path).parse_file([], dm.log)[0]
            else:
                df = pd.read_excel(f_path, sheet_name=[sh])[sh]   # come SheetsHandler (senza dtype=object)
            df_c, _ = datatable_cleaner.DataFrameCleaner(df=df, log=[], col_MAP=dm.col_map).input_cleaner()
            name = f"{var_code}__f{i + 1}" + ("" if sh is None else f"_s{j + 1}")
            tables[name] = finish(dm, df_c, cfg, var_code)  # PATCH_B3_ALLINEA_261029
    return tables, "NO_STRUCTURE"


# ---------------------------------------------------------------- misure
def roundtrip(df):
    """Export e rilettura come nel passo 5 (to_csv '|', read_csv dtype=str, drop_duplicates)."""
    if LEGGERO["on"]:  # PATCH_B3_MEMORIA_261030: stesso export, su file invece che in memoria
        df.to_csv(LEGGERO["tmp"], index=False, sep='|')
        d = pd.read_csv(LEGGERO["tmp"], delimiter='|', dtype=str, keep_default_na=False, na_values=[''])
        n = len(d)
        d = d.drop_duplicates()
        return d, n - len(d)
    buf = io.StringIO()
    df.to_csv(buf, index=False, sep='|')
    buf.seek(0)
    d = pd.read_csv(buf, delimiter='|', dtype=str, keep_default_na=False, na_values=[''])
    n = len(d)
    d = d.drop_duplicates()
    return d, n - len(d)


def is_null(s):
    return s.isna() | s.astype(str).str.strip().isin(NULLS)


def descriptive_cols(df, numeric_set):
    return [c for c in df.columns if c not in numeric_set and c != 'UNITA_ADMIN']


def find_key_bounded(df, cols, max_r, budget):
    """Stesso ordine di superkey_finder.find_super_key, ma con r <= max_r e tempo limitato."""
    if not cols:
        return None, "nessuna colonna descrittiva"
    if df.duplicated(subset=cols).any():
        return None, "non univoca neanche su tutte le descrittive"
    t0 = time.time()
    for r in range(1, min(max_r, len(cols)) + 1):
        for sub in combinations(cols, r):
            if time.time() - t0 > budget:
                return list(cols), "tutte le descrittive (tempo esaurito)"
            if not df.duplicated(subset=list(sub)).any():
                return list(sub), f"minima (r={r})"
    return list(cols), f"tutte le descrittive (nessuna con r<={max_r})"


def table_metrics(d, numeric_set, canon, valid):
    cols = list(d.columns)
    num = [c for c in cols if c in numeric_set]
    vals, tot = 0, 0.0
    for c in num:
        x = pd.to_numeric(d[c].where(~is_null(d[c])), errors='coerce')
        vals += int(x.notna().sum())
        tot += float(x.abs().sum())
    m = dict(righe=len(d), colonne=len(cols), col_non_canoniche=sum(c not in canon for c in cols),
             indicatori=len(num), valori_num=vals, somma_num=tot, ha_codice_regione=int('CODICE_REGIONE' in cols),
             righe_cod_non_valido=0, righe_cod_mancante=0)
    if 'CODICE_REGIONE' in cols:
        s = d['CODICE_REGIONE'].astype(str).str.strip()
        nn = ~is_null(d['CODICE_REGIONE'])
        m['righe_cod_non_valido'] = int((nn & ~s.isin(valid)).sum())
        m['righe_cod_mancante'] = int((~nn).sum())
    return m, set(cols), set(num)


def prod_check(dm, name, d):
    p = f"{dm.out_path}{name}.txt"
    if not os.path.exists(p):
        return dict(file_produzione="assente")
    if LEGGERO["on"]:  # PATCH_B3_MEMORIA_261030: righe contate a blocchi, colonne dall'intestazione
        qcols = list(pd.read_csv(p, delimiter='|', dtype=str, nrows=0).columns)
        qlen = sum(len(ch) for ch in pd.read_csv(p, delimiter='|', dtype=str, keep_default_na=False,
                                                  na_values=[''], usecols=[0], chunksize=500000))
        return dict(file_produzione=os.path.basename(p), righe_produzione=qlen, righe_full=len(d),
                    righe_uguali=qlen == len(d), colonne_uguali=qcols == list(d.columns),
                    colonne_solo_produzione="; ".join(sorted(set(qcols) - set(d.columns))),
                    colonne_solo_full="; ".join(sorted(set(d.columns) - set(qcols))))
    q = pd.read_csv(p, delimiter='|', dtype=str, keep_default_na=False, na_values=[''])
    return dict(file_produzione=os.path.basename(p), righe_produzione=len(q), righe_full=len(d),
                righe_uguali=len(q) == len(d), colonne_uguali=list(q.columns) == list(d.columns),
                colonne_solo_produzione="; ".join(sorted(set(q.columns) - set(d.columns))),
                colonne_solo_full="; ".join(sorted(set(d.columns) - set(q.columns))))


# ---------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True)
    p.add_argument("--only", default="")
    p.add_argument("--configs", default=",".join(CONFIGS))
    p.add_argument("--max-r", type=int, default=3)
    p.add_argument("--key-seconds", type=float, default=60)
    # PATCH_B3_ALLINEA_261029: esclusioni decise il 29/10 (ALIM fuori dall'ablation; file con errore della fonte)
    p.add_argument("--escludi-var", default="ALIM_EXCHANGE_VIVI")
    p.add_argument("--leggero", action="store_true")  # PATCH_B3_MEMORIA_261030
    p.add_argument("--escludi-file",
                   default="scambi_di_alimenti_di_origine_animale_01_07_2024_31_12_2024.csv")
    a = p.parse_args()
    if a.leggero:  # PATCH_B3_MEMORIA_261030
        os.makedirs(f"{HOME}experiments/B_ablation/out/", exist_ok=True)
        LEGGERO.update(on=True, tmp=f"{HOME}experiments/B_ablation/out/_tmp_roundtrip_leggero.txt")
        print("Modalita' leggera: senza cache, export su file")

    cfg_names = [c for c in a.configs.split(",") if c]
    bad = [c for c in cfg_names if c not in CONFIGS]
    if bad:
        sys.exit(f"Configurazioni sconosciute: {bad}. Disponibili: {list(CONFIGS)}")
    if "full" not in cfg_names:
        cfg_names.insert(0, "full")
    # prima le configurazioni che condividono la pulizia di full (cache), poi le altre
    same_clean = [c for c in cfg_names if CONFIGS[c]["fuzzy"] and CONFIGS[c]["dict"] and CONFIGS[c]["numfmt"]]
    cfg_names = same_clean + [c for c in cfg_names if c not in same_clean]

    log = _Log()
    dm = DataMiner(homepath=HOME, new_info=False, log=log, today=None, source=a.source)
    numeric_set = set(dm.numeric_cols)
    canon = set(dm.col_map['name_out'])
    import json
    with open(dm.codregione_path, encoding='utf-8') as f:
        valid = set(json.load(f).keys())
    info = dm.DB_info
    info['file_in'] = info['file_in'].apply(lambda x: x if isinstance(x, list) else [])
    only = {x for x in a.only.split(",") if x}
    var_codes = [v for v in sorted(info['VAR_CODE'].unique()) if not only or v in only]
    escl_var = {x for x in a.escludi_var.split(",") if x}  # PATCH_B3_ALLINEA_261029
    escl_file = {x for x in a.escludi_file.split(",") if x}
    a.var_tolti = [v for v in var_codes if v in escl_var]
    a.file_tolti = []
    var_codes = [v for v in var_codes if v not in escl_var]
    if a.var_tolti:
        print(f"VAR_CODE esclusi: {a.var_tolti}")
    print(f"{a.source} snapshot {dm.last_request}: {len(var_codes)} VAR_CODE, configurazioni {cfg_names}")

    per_tab, per_vc, controllo, errori = [], [], [], []
    t_start = time.time()
    for vc in var_codes:
        files = [i for sub in info.loc[info.VAR_CODE == vc, 'file_in'].values for i in sub]
        a.file_tolti += [f"{vc}: {i}" for i in files if i in escl_file]  # PATCH_B3_ALLINEA_261029
        files = [i for i in files if i not in escl_file]
        files = [os.path.join(f"{dm.dset_path}/{i}") for i in files]
        if not files:
            continue
        clear_caches()
        ref = {}       # tabella full -> (metriche, colonne, numeriche, chiave)
        ref_vc = None
        for cn in cfg_names:
            cfg = CONFIGS[cn]
            if not cfg["fuzzy"] or not cfg["dict"] or not cfg["numfmt"]:
                CLEAN_CACHE.clear()
            t0 = time.time()
            try:
                with patched(cfg):
                    tables, hank = (run_structured if cfg["struct"] else run_no_structure)(dm, vc, files, cfg)
            except (Exception, SystemExit) as e:
                errori.append(dict(config=cn, var_code=vc, errore=repr(e)[:500],
                                   dove=traceback.format_exc().strip().splitlines()[-3][:300]))
                per_vc.append(dict(config=cn, var_code=vc, esito="errore"))
                print(f"  {vc} [{cn}]: ERRORE {e!r}"[:200])
                continue
            secs = time.time() - t0
            agg = dict(config=cn, var_code=vc, esito="ok", architettura=hank, tabelle=len(tables), secondi=round(secs, 1))
            schemi = set()
            for name, df in _iter_tables(tables):  # PATCH_B3_MEMORIA_261030
                d, n_ident = roundtrip(df)
                del df
                m, cols, num = table_metrics(d, numeric_set, canon, valid)
                schemi.add(tuple(sorted(cols)))
                row = dict(config=cn, var_code=vc, tabella=name, righe_identiche=n_ident, **m)
                if cn == "full":
                    key, how = find_key_bounded(d, descriptive_cols(d, numeric_set), a.max_r, a.key_seconds)
                    ref[name] = (m, cols, num, key)
                    row.update(chiave="; ".join(key) if key else "", chiave_tipo=how,
                               dup_chiave=0 if key else None)
                    controllo.append(dict(var_code=vc, tabella=name, **prod_check(dm, name, d)))
                elif name in ref:
                    rm, rcols, rnum, key = ref[name]
                    row.update(delta_righe=m['righe'] - rm['righe'], col_extra=len(cols - rcols),
                               col_mancanti=len(rcols - cols), indicatori_persi=len(rnum - num),
                               senza_codice_regione=int(rm['ha_codice_regione'] == 1 and m['ha_codice_regione'] == 0))
                    if key and set(key) <= cols:
                        row.update(chiave="; ".join(key), dup_chiave=int(d.duplicated(subset=key).sum()), chiave_assente=0)
                    elif key:
                        row.update(chiave="; ".join(key), dup_chiave=None, chiave_assente=1)
                else:
                    row.update(tabella_non_in_full=1)
                per_tab.append(row)
                for k in ('righe', 'righe_identiche', 'col_non_canoniche', 'valori_num', 'somma_num',
                          'righe_cod_non_valido', 'righe_cod_mancante'):
                    agg[k] = agg.get(k, 0) + (row[k] or 0)
                for k in ('dup_chiave', 'chiave_assente', 'col_extra', 'col_mancanti', 'indicatori_persi',
                          'senza_codice_regione', 'tabella_non_in_full'):
                    if row.get(k) is not None:
                        agg[k] = agg.get(k, 0) + row[k]
                del d
            agg['schemi_distinti'] = len(schemi)
            if cn == "full":
                ref_vc = agg
            elif ref_vc:
                agg['delta_tabelle'] = agg['tabelle'] - ref_vc['tabelle']
                agg['delta_righe'] = agg['righe'] - ref_vc['righe']
                agg['delta_valori_num_%'] = _pct(agg['valori_num'], ref_vc['valori_num'])
                agg['delta_somma_num_%'] = _pct(agg['somma_num'], ref_vc['somma_num'])
            per_vc.append(agg)
            print(f"  {vc} [{cn}] {agg['tabelle']} tabelle, {agg['righe']} righe ({secs:.1f}s)")  # PATCH_B3_MEMORIA_261030
            fuzzy_log.RECORDS.clear()
            del tables  # PATCH_B3_MEMORIA_261030
            gc.collect()
        clear_caches()

    if LEGGERO["on"] and LEGGERO["tmp"] and os.path.exists(LEGGERO["tmp"]):  # PATCH_B3_MEMORIA_261030
        open(LEGGERO["tmp"], "w").close()   # svuotato, non cancellato
    write_excel(a, dm, cfg_names, per_tab, per_vc, controllo, errori, time.time() - t_start)


def _pct(x, ref):
    return None if not ref else round(100.0 * (x - ref) / ref, 3)


def write_excel(a, dm, cfg_names, per_tab, per_vc, controllo, errori, secs):
    vc = pd.DataFrame(per_vc)
    tab = pd.DataFrame(per_tab)
    sint = []
    ok = vc[vc.esito == "ok"] if len(vc) else vc
    full_ok = set(ok.loc[ok.config == "full", "var_code"]) if len(ok) else set()
    for cn in cfg_names:
        s = ok[ok.config == cn]
        both = s[s.var_code.isin(full_ok)]
        f = ok[(ok.config == "full") & ok.var_code.isin(set(both.var_code))]
        row = dict(config=cn, var_code_ok=len(s), var_code_errore=int(((vc.config == cn) & (vc.esito == "errore")).sum()))
        for k in ('tabelle', 'righe', 'righe_identiche', 'dup_chiave', 'chiave_assente', 'righe_cod_non_valido',
                  'righe_cod_mancante', 'senza_codice_regione', 'col_non_canoniche', 'col_extra', 'col_mancanti',
                  'indicatori_persi', 'tabella_non_in_full', 'valori_num', 'somma_num'):
            if k in both.columns:
                row[k] = both[k].fillna(0).sum()
        if cn != "full" and len(f):
            row['delta_tabelle'] = row.get('tabelle', 0) - f['tabelle'].sum()
            row['delta_righe'] = row.get('righe', 0) - f['righe'].sum()
            row['delta_valori_num_%'] = _pct(row.get('valori_num', 0), f['valori_num'].sum())
            row['delta_somma_num_%'] = _pct(row.get('somma_num', 0), f['somma_num'].sum())
        sint.append(row)
    readme = pd.DataFrame({"voce": [  # PATCH_B3_ALLINEA_261029: + esclusioni e passo 3
        "fonte", "snapshot", "eseguito", "durata (s)", "max r chiave", "configurazioni",
        "VAR_CODE esclusi", "file esclusi", "passo 3", "modalita'", "nota"],  # PATCH_B3_MEMORIA_261030
        "valore": [a.source, dm.last_request, time.strftime("%Y-%m-%d %H:%M"), round(secs), a.max_r,
                   ", ".join(cfg_names),
                   ", ".join(getattr(a, "var_tolti", [])) or "nessuno",
                   "; ".join(getattr(a, "file_tolti", [])) or "nessuno",
                   "harmonize_regions + aggregazione del Trentino come data_miner (no ELEN, no ISTAT); "
                   "no_harmonization salta entrambi",
                   "leggera (senza cache, export su file)" if LEGGERO["on"] else "standard (cache in memoria)",
                   "Le somme di sintesi sono sui VAR_CODE riusciti sia in full sia nella configurazione. "
                   "Definizioni delle misure nell'intestazione dello script."]})
    out_dir = f"{HOME}experiments/B_ablation/out/"
    os.makedirs(out_dir, exist_ok=True)
    path = f"{out_dir}ablation_{a.source}_{dm.last_request}_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        readme.to_excel(w, sheet_name="README", index=False)
        pd.DataFrame(sint).to_excel(w, sheet_name="sintesi", index=False)
        vc.to_excel(w, sheet_name="per_var_code", index=False)
        tab.to_excel(w, sheet_name="per_tabella", index=False)
        pd.DataFrame(controllo).to_excel(w, sheet_name="controllo_full", index=False)
        pd.DataFrame(errori, columns=["config", "var_code", "errore", "dove"]).to_excel(w, sheet_name="errori", index=False)
    print(f"\nRisultati: {path}\nTempo: {secs:.0f}s")


if __name__ == "__main__":
    main()
