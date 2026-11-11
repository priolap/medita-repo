# -*- coding: utf-8 -*-
"""
load.py - Load di MEDITA sul lakehouse (Delta Lake + DuckDB). Nessun SQLite.

PATCH_LOAD_LAKE_261109: dal 09/11/2026 questo file e' la Load della pipeline (prima scripts/load_lake.py).
La Load SQLite precedente (DB.sql, DB_ts.sql) e' in scripts/old/load_sqlite_20261109.py; il confronto
di parita' lake/SQLite (experiments/A_lake/, 09/11/2026) ha dato esito OK su tutte le tabelle.

Struttura del lake (MEDITA/lake/), tre zone:
  bronze/raw_catalog     catalogo Delta dei file grezzi di data/input/<FONTE>/<snapshot>/
                         (i file restano nel formato originale; solo righe nuove: append)
  silver/<VAR_CODE>      tabelle della Transform (data/output/<FONTE>/<VAR_CODE>.txt), stessi tipi
                         della Load SQLite
  gold/<VAR_CODE>_ts     serie temporali (stessa logica della Load SQLite, eseguita da DuckDB)
  gold/ts_colonne, gold/metadata, gold/statsdata
  _lake_log              registro Delta (append) di ogni scrittura: tabella, versione, snapshot

Ogni Load scrive UNA nuova versione Delta per tabella (mode='overwrite', un solo commit):
le versioni precedenti restano leggibili con il time travel.

Uso dal MASTER (invariato):
    from scripts import load as l
    l.load_process(homepath, sources_list, log)
"""

import os
import re
import json
import time
import hashlib
import datetime as dt

import pandas as pd
import pyarrow as pa
import duckdb
from deltalake import DeltaTable, write_deltalake

# =============================================================================
# PATCH_LOAD_LAKE_261109: costanti e funzioni ereditate dalla Load SQLite (PATCH_LOAD_261026 e
# PATCH_LOAD_ISTAT2026_261028N), copiate senza modifiche da scripts/old/load_sqlite_20261109.py
# =============================================================================
_CHUNK = 200_000
_INT_COLS = ['ANNO', 'MESE']                      # MESE: '1' e '01' (AIFA dal 2021) -> 1
_NA_VALUES = ['', 'nan', 'NaN', 'None']           # 'NA' NON e' mancante (puo' essere un codice)
_TRENTINO_PROV = ('ITH1', 'ITH2')
# MINIS: colonne non additive con formula verificata riga per riga sui dati (26/10/2026)
#   TASSO_UTILIZZO = valore di struttura ripetuto sui reparti = sum(GIORNATE_DEGENZA)/sum(GIORNATE_DISPONIBILI)*100
#   DEGENZA_MEDIA_ORDINARIA = GIORNATE_DEGENZA / NUMERO_UTENTI_DIMESSI
_RATIO_COLS = {
    'TASSO_UTILIZZO': ('GIORNATE_DEGENZA', 'GIORNATE_DISPONIBILI', 100.0),
    'DEGENZA_MEDIA_ORDINARIA': ('GIORNATE_DEGENZA', 'NUMERO_UTENTI_DIMESSI', 1.0),
}
_NON_ADDITIVE_NO_FORMULA = ['ICM']                # indice di case mix: non si somma, formula da definire
# ISTAT: struttura del cubo
_ISTAT_NON_DIM = {'ID', 'DATAFLOW', 'FREQ', 'ANNO', 'CODICE_REGIONE', 'REGIONE', 'UNITA_ADMIN',
                  'OBS_VALUE', 'OBS_STATUS', 'NAME_ID_IT', 'NAME_ID_EN', 'NUM_ID', 'REF_ID'}
_ISTAT_MEASURE = ['DATA_TYPE', 'MEASURE', 'TIPO_DATO', 'MISURA1']  # PATCH_LOAD_ISTAT2026_261028N: nomi 2026, poi 2025
_TOT_DESC = ['totale', 'total', 'tutte le voci', 'all items', 'tutti', 'anno', 'mondo', 'italia',
             'world']  # PATCH_LOAD_ISTAT2026_261028N: X1033 'World' in DCIS_DECESSI (copia 2025)
_TOT_CODE = ['TOTAL', 'TOT', 'ALL', 'YEAR', 'WORLD', 'IT', 'ITTOT', '99', '9', 'Y_GE0']


def _q(name):
    return '"' + str(name).replace('"', '""') + '"'



def _clean(x):
    return '' if x is None or (isinstance(x, float) and pd.isna(x)) else str(x).strip()



def _istat_total(codes, descs):
    """Codice di totale di una dimensione ISTAT, ricavato dai dati. (codice, criterio) o (None, motivo)."""
    codes = sorted(c for c in codes if c is not None)
    for t in _TOT_DESC:
        for c in codes:
            if _clean(descs.get(c)).lower() == t:
                return c, f"descrizione '{_clean(descs.get(c))}'"
    for t in _TOT_CODE:
        if t in codes:
            return t, f"codice {t}" + ('' if _clean(descs.get(t)) else ' (senza descrizione)')
    roots = [c for c in codes if all(o.startswith(c) for o in codes)]
    if roots:
        return roots[0], 'radice della gerarchia'
    return None, 'nessun totale'



def _safe(s):
    return re.sub(r'[^0-9A-Za-z_]+', '_', str(s)).strip('_') or 'X'

from scripts.modules.utils import db_wrapper

try:                                    # deltalake >= 0.21
    from deltalake import CommitProperties
except ImportError:                     # versioni vecchie: metadati solo in _lake_log
    CommitProperties = None

_DATA_SOURCES = ('AIFA', 'MINIS', 'ISTAT')
_TEXT_SOURCES = ()  # REPO_NEWS_261111: fonti testuali non incluse nella repository pubblica (copyright)
_META_COLS = ['FILE_NAME', 'VAR_NAME', 'VAR_CODE', 'TAG', 'DESC', 'source', 'permalink',
              'download_link', 'url', 'file_in', 'file_out', 'EXT_TYPE', 'data_format',
              'last_update', 'encoding', 'delimiter', 'sheets', 'outcome', 'last_pars', 'parsing',
              'admin_info', 'topics', 'update_frequency', 'last_meta_mod', 'last_update_source',
              'loading_date', 'urn']          # colonne del modello ORM Metadata (relations.py)
_DELTA_BAD = re.compile(r'[ ,;{}()\n\t=]')    # caratteri non ammessi nei nomi di colonna Delta


class LoadProcess:
    def __init__(self, homepath, sources_list, log, lake_root=None, bronze_hash=True):
        self.homepath = homepath
        self.sources_list = sources_list
        self.log = log
        self.lake = (lake_root or f"{homepath}lake").rstrip('/\\')
        self.bronze_hash = bronze_hash
        self.load_id = dt.datetime.now().strftime('%Y%m%d_%H%M%S')
        self._log_rows = []
        with open(f"{homepath}config/cols_attributes.json", 'r', encoding='ISO-8859-1') as f:
            labels = json.load(f)
        # stesse definizioni della Load SQLite (LoadProcess.load_configs, ora in scripts/old/)
        self.numeric_cols = [i['name_out'] for i in labels if i.get('is_obs')]
        self.numeric_dtype = [i['name_out'] for i in labels if i.get('dtype') == 'numeric']
        self.dfmeta, self.sources = db_wrapper.generate_metadata_df(sources_list, homepath)
        for z in ('bronze', 'silver', 'gold'):
            os.makedirs(f"{self.lake}/{z}", exist_ok=True)

    # ------------------------------------------------------------------ scrittura Delta
    def _path(self, zone, name):
        return f"{self.lake}/{zone}/{name}"

    def _write(self, zone, name, data, snapshot='', mode='overwrite'):
        """Un solo commit Delta; registra tabella, versione e snapshot in _lake_log."""
        path = self._path(zone, name)
        meta = {'medita_load_id': self.load_id, 'zone': zone, 'table': name, 'snapshot': snapshot}
        kw = dict(mode=mode)
        if mode == 'overwrite':
            kw['schema_mode'] = 'overwrite'   # una nuova versione puo' avere colonne diverse
        if CommitProperties is not None:
            kw['commit_properties'] = CommitProperties(custom_metadata=meta)
        t0 = time.time()
        write_deltalake(path, data, **kw)
        dtab = DeltaTable(path)
        n = dtab.to_pyarrow_dataset().count_rows()
        self._log_rows.append({'LOAD_ID': self.load_id, 'ZONE': zone, 'TABLE': name,
                               'VERSION': dtab.version(), 'SNAPSHOT': snapshot, 'MODE': mode,
                               'ROWS': n, 'SECONDS': round(time.time() - t0, 3),
                               'TS': dt.datetime.now().isoformat(timespec='seconds')})
        return n

    def _flush_log(self):
        if self._log_rows:
            df = pd.DataFrame(self._log_rows)
            write_deltalake(f"{self.lake}/_lake_log", pa.Table.from_pandas(df, preserve_index=False),
                            mode='append')
            self._log_rows = []

    # ------------------------------------------------------------------ BRONZE
    def build_bronze_catalog(self):
        """Catalogo dei file grezzi: una riga per file nuovo o cambiato (append)."""
        root = f"{self.homepath}data/input"
        file2var = {}
        for _, r in self.dfmeta.iterrows():
            fin = r.get('file_in')
            try:
                names = json.loads(fin) if isinstance(fin, str) and fin.startswith('[') else [fin]
            except ValueError:
                names = [fin]
            for fn in names:
                if isinstance(fn, str) and fn:
                    file2var.setdefault((r['source'], fn.strip().lower()), set()).add(r['VAR_CODE'])
        path = self._path('bronze', 'raw_catalog')
        noti = set()
        if os.path.exists(f"{path}/_delta_log"):
            old = DeltaTable(path).to_pandas(columns=['REL_PATH', 'BYTES', 'MTIME'])
            noti = set(zip(old['REL_PATH'], old['BYTES'].astype('int64'), old['MTIME']))
        rows = []
        for cur, _, files in os.walk(root):
            for fn in sorted(files):
                full = os.path.join(cur, fn)
                rel = os.path.relpath(full, root).replace('\\', '/')
                parts = rel.split('/')
                st = os.stat(full)
                mtime = dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec='seconds')
                if (rel, int(st.st_size), mtime) in noti:
                    continue
                src = parts[0]
                snap = parts[1] if len(parts) > 2 and re.fullmatch(r'\d{8}', parts[1]) else ''
                sha = ''
                if self.bronze_hash:
                    h = hashlib.sha256()
                    with open(full, 'rb') as f:
                        for blk in iter(lambda: f.read(8 * 1024 * 1024), b''):
                            h.update(blk)
                    sha = h.hexdigest()
                rows.append({'SOURCE': src, 'SNAPSHOT': snap, 'REL_PATH': rel, 'FILE_NAME': fn,
                             'EXT': os.path.splitext(fn)[1].lower().lstrip('.'),
                             'BYTES': int(st.st_size), 'MTIME': mtime, 'SHA256': sha,
                             'VAR_CODE': ';'.join(sorted(file2var.get((src, fn.lower()), []))),
                             'CATALOG_LOAD_ID': self.load_id})
        if not rows:
            self.log.debug('bronze/raw_catalog: nessun file nuovo')
            return 0
        tab = pa.Table.from_pandas(pd.DataFrame(rows), preserve_index=False)
        self._write('bronze', 'raw_catalog', tab, mode='append')
        senza = sum(1 for r in rows if not r['VAR_CODE'])
        self.log.debug(f"bronze/raw_catalog: {len(rows)} file aggiunti ({senza} senza VAR_CODE)")
        return len(rows)

    # ------------------------------------------------------------------ SILVER
    def _txt_reader(self, path, cols):
        """Stessi tipi di load._store_txt_table: ID, INTEGER (ANNO/MESE), REAL, TEXT."""
        ints = [c for c in cols if c in _INT_COLS]
        nums = [c for c in cols if c in self.numeric_dtype and c not in ints]
        fields = [pa.field('ID', pa.int64())]
        for c in cols:
            fields.append(pa.field(c, pa.int64() if c in ints else pa.float64() if c in nums
                                   else pa.string()))
        schema = pa.schema(fields)
        stato = {'n': 0, 'persi': {}}

        def batches():
            for ch in pd.read_csv(path, sep='|', dtype=str, keep_default_na=False,
                                  na_values=_NA_VALUES, chunksize=_CHUNK):
                n0 = stato['n']
                stato['n'] += len(ch)
                arrays = [pa.array(range(n0 + 1, stato['n'] + 1), pa.int64())]
                for c in cols:
                    if c in ints or c in nums:
                        conv = pd.to_numeric(ch[c], errors='coerce')
                        bad = int((ch[c].notna() & conv.isna()).sum())
                        if bad:
                            stato['persi'][c] = stato['persi'].get(c, 0) + bad
                        if c in ints:      # come int(round(x)): arrotondamento al pari
                            arrays.append(pa.array(conv.astype('float64').round().astype('Int64'),
                                                   pa.int64(), from_pandas=True))
                        else:
                            arrays.append(pa.array(conv.astype('float64'), pa.float64(), from_pandas=True))
                    else:
                        arrays.append(pa.array(ch[c].astype(object), pa.string(), from_pandas=True))
                yield pa.RecordBatch.from_arrays(arrays, schema=schema)

        return pa.RecordBatchReader.from_batches(schema, batches()), stato

    def store_silver_table(self, source, var, snapshot):
        path = f"{self.homepath}data/output/{source}/{var}.txt"
        cols = pd.read_csv(path, sep='|', nrows=0).columns.tolist()
        if any(str(c).upper() == 'ID' for c in cols):     # in SQLite: "duplicate column name: ID"
            self.log.critical(f"silver/{var}: il .txt ha gia' una colonna ID, tabella saltata")
            return
        bad = [c for c in cols if _DELTA_BAD.search(str(c))]
        if bad:
            self.log.critical(f"silver/{var}: nomi di colonna non ammessi da Delta {bad}, tabella saltata")
            return
        reader, stato = self._txt_reader(path, cols)
        n_lake = self._write('silver', var, reader, snapshot=snapshot)
        if n_lake != stato['n']:
            self.log.critical(f"silver/{var}: righe nel .txt {stato['n']}, nel lake {n_lake}")
        else:
            self.log.debug(f"silver/{var}: {n_lake} righe, {len(cols)} colonne")
        for c, n in stato['persi'].items():
            self.log.warning(f"silver/{var}.{c}: {n} valori non numerici diventati NULL")

    def store_text_source(self, source):
        """Come load.process_text_sources: TOKENS e BIGRAMS uniti con virgole."""
        data = pd.read_pickle(f"{self.homepath}data/output/{source}/{source}.pkl")
        for c in ('TOKENS', 'BIGRAMS'):
            if c in data.columns:
                data[c] = data[c].apply(lambda x: ','.join(map(str, x)))
        # PATCH_LAKE_ORDINE_261109: colonne e ordine del modello ORM (come la tabella SQLite)
        model = db_wrapper.get_model_class(source)
        if model is not None:
            ordine = [c.name for c in model.__table__.columns]
            fuori = [c for c in data.columns if c not in ordine]
            if fuori:
                self.log.warning(f"silver/{source}: colonne non nel modello ORM, escluse: {fuori}")
            data = data.reindex(columns=ordine)
        else:
            self.log.warning(f"silver/{source}: nessun modello ORM, ordine del pickle")
        # PATCH_LAKE_TESTO_261109: tutte le colonne come testo, come il modello ORM (String); NaN/None -> NULL
        for c in data.columns:
            data[c] = data[c].astype(object).map(
                lambda x: None if x is None or (isinstance(x, float) and pd.isna(x)) else str(x))
        tab = pa.Table.from_pandas(data, preserve_index=False,
                                   schema=pa.schema([pa.field(str(c), pa.string()) for c in data.columns]))
        n = self._write('silver', source, tab)
        self.log.debug(f"silver/{source}: {n} righe")

    def build_silver(self):
        for source in self.sources:
            try:
                if source in _TEXT_SOURCES:
                    self.store_text_source(source)
                    continue
                if source not in _DATA_SOURCES:
                    continue
                m = self.dfmeta[self.dfmeta['source'] == source].dropna(subset=['file_out'])
                for fout in sorted(set(m['file_out'])):
                    var = fout.strip()[:-4]
                    snap = str(m.loc[m['file_out'] == fout, 'last_pars'].dropna().astype(str).max())
                    try:
                        self.store_silver_table(source, var, snap if snap != 'nan' else '')
                    except Exception as err:
                        self.log.exception(f"silver/{var} non scritta: {err}")
            except Exception as err:
                self.log.exception(f"{source}: silver non scritto: {err}")
            self._flush_log()

    # ------------------------------------------------------------------ GOLD
    def _duck(self):
        """DuckDB con una vista per ogni tabella silver (delta_scan, altrimenti Arrow)."""
        con = duckdb.connect()
        try:
            con.execute("LOAD delta")
            reader = 'delta_scan'
        except Exception:
            try:
                con.execute("INSTALL delta; LOAD delta")
                reader = 'delta_scan'
            except Exception as err:
                self.log.warning(f"delta_scan non disponibile ({err!r:.120}): lettura via Arrow")
                reader = 'arrow'
        silver = f"{self.lake}/silver"
        for name in sorted(os.listdir(silver)):
            p = f"{silver}/{name}"
            if not os.path.isdir(f"{p}/_delta_log"):
                continue
            if reader == 'delta_scan':
                con.execute(f"CREATE VIEW {_q(name)} AS SELECT * FROM delta_scan('{p.replace(chr(39), chr(39) * 2)}')")
            else:
                con.register(name, DeltaTable(p).to_pyarrow_dataset())
        self.log.debug(f"DuckDB: tabelle silver lette con {reader}")
        return con

    @staticmethod
    def _cols(con, table):
        return [r[0] for r in con.execute(f"DESCRIBE {_q(table)}").fetchall()]

    def _ts_somma(self, con, table, cols):
        """= load._ts_somma, su DuckDB. LAKE: pd.read_sql -> con.execute().df();
        SUM su TRY_CAST(.. AS DOUBLE) (SQLite somma anche le colonne TEXT)."""
        obs = [c for c in self.numeric_cols if c in cols]
        if not obs:
            return None, []
        skip = [c for c in obs if c in _NON_ADDITIVE_NO_FORMULA]
        for c in skip:
            self.log.warning(f"{table}.{c}: indice non additivo senza formula, escluso dalle _ts")
        ratio = {}
        for c, (num, den, k) in _RATIO_COLS.items():
            if c in obs:
                if num in cols and den in cols:
                    ratio[c] = (num, den, k)
                else:
                    skip.append(c)
                    self.log.error(f"{table}.{c}: mancano {num}/{den}, colonna esclusa dalle _ts")
        add = [c for c in obs if c not in skip and c not in ratio]
        need = list(dict.fromkeys(add + [x for n, d, _ in ratio.values() for x in (n, d)]))
        n_ith0 = con.execute(f"SELECT COUNT(*) FROM {_q(table)} WHERE CODICE_REGIONE = 'ITH0'").fetchone()[0]
        cod = "CASE WHEN CODICE_REGIONE IN ('ITH1','ITH2') THEN 'ITH0' ELSE CODICE_REGIONE END"
        where = "WHERE CODICE_REGIONE NOT IN ('ITH1','ITH2')" if n_ith0 else ""
        sums = ', '.join(f"SUM(TRY_CAST({_q(c)} AS DOUBLE)) AS {_q(c)}" for c in need)
        df = con.execute(f"""SELECT ANNO, {cod} AS COD, MIN(REGIONE) AS REGIONE,
                                    COUNT(DISTINCT REGIONE) AS NREG, {sums}
                             FROM {_q(table)} {where} GROUP BY ANNO, COD""").df()
        nulli = df['ANNO'].isna() | df['COD'].isna()
        if nulli.any():
            self.log.warning(f"{table}: {int(nulli.sum())} gruppi senza ANNO o CODICE_REGIONE esclusi")
            df = df[~nulli]
        if (df['NREG'] > 1).any():
            self.log.warning(f"{table}: codici regione con piu' nomi: {sorted(df.loc[df.NREG > 1, 'COD'])}")
        for c, (num, den, k) in ratio.items():
            d = df[den].where(df[den] > 0)
            df[c] = df[num] / d * k
        keep = [c for c in obs if c not in skip]
        diz = [{'TABELLA': f"{table}_ts", 'COLONNA': c,
                'REGOLA': (f"rapporto di somme: {ratio[c][0]}/{ratio[c][1]}*{ratio[c][2]:g}" if c in ratio
                           else 'somma'),
                'FILTRI_TOTALE': '', 'DESCRIZIONE': ''} for c in keep]
        df['ANNO'] = df['ANNO'].astype(int)
        df = df.sort_values(['ANNO', 'COD']).reset_index(drop=True)   # LAKE: ordine stabile
        return df[['ANNO', 'REGIONE'] + keep], diz

    def _ts_istat(self, con, table, cols):
        """= load._ts_istat, su DuckDB. LAKE: 'IS ?' -> 'IS NOT DISTINCT FROM ?';
        nessun indice temporaneo (DuckDB non indicizza le viste); pd.read_sql -> .df()."""
        mcols = [c for c in _ISTAT_MEASURE if c in cols]
        dims = [c for c in cols if c not in _ISTAT_NON_DIM and not c.endswith('_DESC') and c not in mcols]
        tot, crit, descs = {}, {}, {}
        for d in dims:
            dc = f"{d}_DESC" if f"{d}_DESC" in cols else None
            q = f"SELECT DISTINCT {_q(d)}" + (f", {_q(dc)}" if dc else "") + f" FROM {_q(table)}"
            rows = con.execute(q).fetchall()
            descs[d] = {r[0]: (r[1] if dc else None) for r in rows if r[0] is not None and (not dc or r[1])}
            for r in rows:
                descs[d].setdefault(r[0], None)
            tot[d], crit[d] = _istat_total(set(descs[d]), descs[d])
        mdesc = {}
        if mcols:
            mdc = [f"{c}_DESC" for c in mcols if f"{c}_DESC" in cols]
            q = f"SELECT DISTINCT {', '.join(_q(c) for c in mcols + mdc)} FROM {_q(table)}"
            for r in con.execute(q).fetchall():
                mdesc.setdefault(tuple(r[:len(mcols)]), ' | '.join(_clean(x) for x in r[len(mcols):]))
            measures = sorted(mdesc, key=lambda t: tuple(_clean(x) for x in t))
        else:
            measures = [()]
        base_cols = ['ANNO', 'CODICE_REGIONE', 'REGIONE', 'OBS_VALUE'] + dims
        series, diz, regioni, usati = [], [], {}, set()
        for m in measures:
            if mcols:
                cond = ' AND '.join(f"{_q(c)} IS NOT DISTINCT FROM ?" for c in mcols)
                g = con.execute(f"SELECT {', '.join(_q(c) for c in base_cols)} FROM {_q(table)} WHERE {cond}",
                                list(m)).df()
            else:
                g = con.execute(f"SELECT {', '.join(_q(c) for c in base_cols)} FROM {_q(table)}").df()
            nome_m = '_'.join(_safe(x) for x in m if x is not None) or 'OBS_VALUE'
            if (g['CODICE_REGIONE'] == 'ITH0').any():
                g = g[~g['CODICE_REGIONE'].isin(_TRENTINO_PROV)]
            elif g['CODICE_REGIONE'].isin(_TRENTINO_PROV).any():
                self.log.warning(f"{table} [{nome_m}]: Bolzano/Trento senza ITH0, esclusi")
                g = g[~g['CODICE_REGIONE'].isin(_TRENTINO_PROV)]
            g = g[g['ANNO'].notna() & g['CODICE_REGIONE'].notna()]
            filtri, free = [], []
            for d in dims:
                vals = set(g[d].dropna().unique())
                if len(g[d].unique()) <= 1:
                    continue
                if tot[d] is not None and tot[d] in vals:
                    g = g[g[d] == tot[d]]
                    filtri.append(f"{d}={tot[d]}" + (' (senza descrizione)' if 'senza descr' in crit[d] else ''))
                else:
                    free.append(d)
            free = [d for d in free if len(g[d].unique()) > 1]
            key = ['ANNO', 'CODICE_REGIONE'] + free
            dup = int(g.duplicated(key).sum())
            if dup:
                self.log.error(f"{table} [{nome_m}]: {dup} righe duplicate per cella, misura esclusa")
                continue
            regioni.update(dict(zip(g['CODICE_REGIONE'], g['REGIONE'])))
            if free:
                combo = g[free].astype(str).apply(
                    lambda r: '__'.join(f"{_safe(d)}_{_safe(v)}" for d, v in zip(free, r)), axis=1)
                g = g.assign(COL=nome_m + '__' + combo)
            else:
                g = g.assign(COL=nome_m)
            for col, gg in g.groupby('COL'):
                nome, i = col, 2
                while nome in usati:
                    nome, i = f"{col}_{i}", i + 1
                usati.add(nome)
                s = gg.set_index(['ANNO', 'CODICE_REGIONE'])['OBS_VALUE'].rename(nome)
                series.append(s)
                dfree = ''
                if free:
                    v0 = gg.iloc[0]
                    dfree = ' | '.join(f"{d}={v0[d]} ({_clean(descs[d].get(v0[d]))})" for d in free)
                diz.append({'TABELLA': f"{table}_ts", 'COLONNA': nome,
                            'REGOLA': 'valore pubblicato (nessuna aggregazione)',
                            'FILTRI_TOTALE': '; '.join(filtri),
                            'DESCRIZIONE': ' | '.join(x for x in [mdesc.get(m, ''), dfree] if x)})
        if not series:
            return None, []
        df = pd.concat(series, axis=1).reset_index()
        df['REGIONE'] = df['CODICE_REGIONE'].map(regioni)
        df['ANNO'] = df['ANNO'].astype(int)
        df = df.sort_values(['ANNO', 'CODICE_REGIONE']).reset_index(drop=True)   # LAKE: ordine stabile
        return df[['ANNO', 'REGIONE'] + [s.name for s in series]], diz

    def build_gold(self):
        fonte = dict(zip(self.dfmeta['VAR_CODE'], self.dfmeta['source']))
        snap = (self.dfmeta.dropna(subset=['VAR_CODE']).assign(lp=lambda d: d['last_pars'].astype(str))
                .groupby('VAR_CODE')['lp'].max().to_dict())
        # metadata (stesse colonne del modello ORM; ID come la chiave SQLite)
        meta = self.dfmeta.reindex(columns=_META_COLS).astype(object)
        meta = meta.where(meta.notna(), None).map(lambda x: None if x is None else str(x))
        meta.insert(0, 'ID', range(1, len(meta) + 1))
        self._write('gold', 'metadata', pa.Table.from_pandas(meta, preserve_index=False))

        con = self._duck()
        dizionario, stats = [], []
        try:
            tables = sorted(r[0] for r in con.execute("SHOW TABLES").fetchall())
            for table in tables:
                if table not in fonte:
                    continue
                cols = self._cols(con, table)
                # statsdata (= load.get_counts_from_db): conteggi per ANNO e per REGIONE
                tag = self.dfmeta.loc[self.dfmeta['VAR_CODE'] == table, 'TAG'].values[0]
                for tgt in ('ANNO', 'REGIONE'):
                    if tgt in cols:
                        for v, n in con.execute(f"SELECT {_q(tgt)}, COUNT(*) FROM {_q(table)} "
                                                f"GROUP BY {_q(tgt)} ORDER BY 1").fetchall():
                            stats.append({'VAR_CODE': table, 'TAG': tag, tgt: v, f"{tgt}_COUNT": n})
                    else:
                        stats.append({'VAR_CODE': table, 'TAG': tag, tgt: None, f"{tgt}_COUNT": None})
                # serie temporali
                if 'ANNO' not in cols or 'CODICE_REGIONE' not in cols:
                    continue
                try:
                    if fonte[table] == 'ISTAT':
                        df, diz = self._ts_istat(con, table, cols)
                    else:
                        df, diz = self._ts_somma(con, table, cols)
                    if df is None:
                        continue
                    # LAKE: nessun limite di 1900 colonne (era un limite di SQLite)
                    for c in df.columns[2:]:
                        df[c] = pd.to_numeric(df[c], errors='coerce').astype('float64')
                    df['REGIONE'] = df['REGIONE'].astype(object).where(df['REGIONE'].notna(), None)
                    if df.duplicated(['ANNO', 'REGIONE']).any():   # in SQLite: PRIMARY KEY violata
                        self.log.error(f"{table}_ts: chiave (ANNO, REGIONE) duplicata, tabella non scritta")
                        continue
                    self._write('gold', f"{table}_ts", pa.Table.from_pandas(df, preserve_index=False),
                                snapshot=snap.get(table, ''))
                    dizionario += diz
                    self.log.debug(f"gold/{table}_ts: {len(df)} righe, {df.shape[1] - 2} colonne")
                except Exception as err:
                    self.log.exception(f"gold/{table}_ts non generata: {err}")
        finally:
            con.close()
        if dizionario:
            self._write('gold', 'ts_colonne', pa.Table.from_pandas(pd.DataFrame(dizionario),
                                                                   preserve_index=False))
        if stats:
            st = pd.DataFrame(stats).reindex(columns=['VAR_CODE', 'TAG', 'ANNO', 'ANNO_COUNT',
                                                      'REGIONE', 'REGIONE_COUNT'])
            st['ANNO'] = st['ANNO'].astype('Int64')
            st['REGIONE'] = st['REGIONE'].astype(object).where(st['REGIONE'].notna(), None)
            for c in ('ANNO_COUNT', 'REGIONE_COUNT'):
                st[c] = st[c].astype('Int64')
            st.insert(0, 'ID', range(1, len(st) + 1))
            self._write('gold', 'statsdata', pa.Table.from_pandas(st, preserve_index=False))
        self._flush_log()


def load_process(homepath, sources_list, log, lake_root=None, bronze_hash=True):
    lp = LoadProcess(homepath, sources_list, log, lake_root=lake_root, bronze_hash=bronze_hash)
    log.info(f"LAKE LOAD {lp.load_id}: {lp.lake}")
    for step, fn in (('bronze', lp.build_bronze_catalog), ('silver', lp.build_silver),
                     ('gold', lp.build_gold)):
        t0 = time.time()
        try:
            fn()
        except Exception as err:
            log.exception(f"LAKE {step} interrotto: {err}")
        finally:
            lp._flush_log()
        log.info(f"LAKE {step}: {time.time() - t0:.1f} s")
    return lp.load_id


# PATCH_LOAD_LAKE_261109: nomi usati fino al 09/11/2026 (experiments/A_lake)
LakeLoadProcess = LoadProcess
load_lake_process = load_process
