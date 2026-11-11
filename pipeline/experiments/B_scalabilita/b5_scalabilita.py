# -*- coding: utf-8 -*-
r"""
b5 - Benchmark di scalabilita' della Transform (tasks_MPP n.7): lettura dei CSV con e senza la parallelizzazione
Dask, su volumi crescenti dello stesso file. Esperimento con misure di TEMPO: va eseguito a PC libero (di notte).

Cosa fa la pipeline (scripts/modules/utils/excel_parser.py, verificato):
  parse_csv:  is_large = dimensione del file / 1e9 > 0.3
  read_on_parallel(large=True)   dd.read_csv(..., assume_missing=True, dtype=object).compute()   [Dask]
  read_on_parallel(large=False)  pd.read_csv(..., engine='python', quoting=..., dtype=object)     [pandas, motore Python]
  Dask parallelizza solo la lettura: dopo compute() la tabella e' in memoria e pulizia/armonizzazione girano in serie.
  multiprocessing.Pool (nuts_region_harmonizer.parallelize_dataframe) non e' chiamato da nessuna parte.

Modi di lettura confrontati (stesso file, stessa ExcelParser.parse_file della pipeline; cambia solo read_on_parallel):
  python     pandas, motore Python          = quello che la pipeline usa sotto i 300 MB
  c          pandas, motore C (in serie)    = non usato dalla pipeline: separa l'effetto del motore da quello di Dask
  dask_sync  Dask con scheduler sincrono    = stesso codice Dask, un solo thread: separa l'effetto della parallelizzazione
  dask       Dask, scheduler a thread       = quello che la pipeline usa sopra i 300 MB
  In piu', per ogni volume: lettura a vuoto dei byte del file (limite inferiore dovuto al disco) e, una volta per
  volume, i tempi di pulizia (input_cleaner) e armonizzazione (harmonize_regions + Trentino come data_miner) sulla
  tabella letta come in produzione: la parte della Transform che Dask non tocca.

Volumi: prefissi dello stesso CSV (intestazione + righe intere fino alla dimensione richiesta), scritti nella
cartella di lavoro (default D:\MEDITA_b5_work, fuori da OneDrive; riusati se gia' presenti); 0 = file intero (letto
dalla sua cartella, nessuna copia). Nessun file della pipeline viene modificato.

Protocollo: ogni misura in un processo separato (memoria pulita, timeout); per ogni ripetizione e volume prima la
lettura a vuoto, poi i modi in ordine ruotato da una ripetizione all'altra (la cache del disco non favorisce sempre
lo stesso modo). Se un modo supera il timeout, nella stessa ripetizione i volumi maggiori per quel modo sono saltati.
Il PC non va in sospensione durante l'esecuzione. Il file dei risultati viene riscritto dopo ogni misura.

Scrive: experiments/B_scalabilita/out/b5_scalabilita_<data_ora>.xlsx (README, ambiente, volumi, misure, sintesi, pulizia)
        e i prefissi nella cartella di lavoro.

Uso (da MEDITA):
  prova breve:  python experiments/B_scalabilita/b5_scalabilita.py --file MINIS:dispositivi_medici.csv --volumi 50 --ripetizioni 1
  notte:        python experiments/B_scalabilita/b5_scalabilita.py
Opzioni: --file FONTE:nome.csv[,..]  --volumi MB[,..] (0 = intero)  --modi python,c,dask_sync,dask
         --ripetizioni 3  --timeout 3600 (s per misura)  --no-pulizia  --work D:\MEDITA_b5_work
"""
import argparse
import contextlib
import csv
import json
import multiprocessing as mp
import os
import platform
import sys
import time
import traceback

HOME = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")).replace("\\", "/") + "/"
sys.path.insert(0, HOME)

import pandas as pd

DEF_FILE = "ISTAT:DCIS_DECESSI.csv,MINIS:dispositivi_medici.csv"
DEF_VOLUMI = "50,150,300,600,1200,0"
DEF_MODI = "python,c,dask_sync,dask"
OUT_DIR = f"{HOME}experiments/B_scalabilita/out/"
STAMP = time.strftime("%Y%m%d_%H%M%S")


class _Log:
    def __init__(self):
        self.m = []

    def _w(self, x, *a, **k):
        self.m.append(str(x))

    debug = info = warning = error = critical = exception = _w


def keep_awake(on=True):
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | (0x00000001 if on else 0))


def snapshot_di(fonte):
    """Snapshot piu' recente, come path_processor.read_data."""
    return sorted(os.listdir(f"{HOME}data/input/{fonte}"), reverse=True)[0]


def var_code_di(fonte, nome):
    try:
        with open(f"{HOME}config/info_{fonte}.json", encoding="utf-8") as f:
            info = pd.DataFrame(json.load(f))
        hit = info[info["file_in"].apply(lambda x: isinstance(x, list) and nome in x)]
        return str(hit["VAR_CODE"].iloc[0]) if len(hit) else ""
    except Exception:
        return ""


# ------------------------------------------------------------------------------------------- misure (processi figli)
def _peak_mb():
    try:
        import psutil
        mi = psutil.Process().memory_info()
        return round(getattr(mi, "peak_wset", mi.rss) / 2 ** 20, 1)
    except Exception:
        return None


@contextlib.contextmanager
def modo_lettura(modo):
    """Sostituisce solo ExcelParser.read_on_parallel, dentro il processo figlio."""
    from scripts.modules.utils import excel_parser
    orig = excel_parser.ExcelParser.read_on_parallel

    def leggi(self, quoting, large=False):
        if modo == "python":
            return orig(self, quoting, large=False)
        if modo in ("dask", "dask_sync"):
            if modo == "dask_sync":
                import dask
                with dask.config.set(scheduler="synchronous"):
                    return orig(self, quoting, large=True)
            return orig(self, quoting, large=True)
        if modo == "c":  # come il ramo pandas della pipeline, ma con il motore C
            try:
                return pd.read_csv(self.file_path, delimiter=self.delim, encoding=self.encoding,
                                   engine="c", quoting=quoting, dtype=object)
            except pd.errors.ParserError:
                return pd.read_csv(self.file_path, delimiter=self.delim, encoding=self.encoding,
                                   engine="c", quoting=csv.QUOTE_MINIMAL, dtype=object)
        raise ValueError(modo)

    excel_parser.ExcelParser.read_on_parallel = leggi
    try:
        yield
    finally:
        excel_parser.ExcelParser.read_on_parallel = orig


def _w_raw(path, q):
    try:
        t0 = time.perf_counter()
        n = 0
        with open(path, "rb") as f:
            while True:
                b = f.read(16 * 2 ** 20)
                if not b:
                    break
                n += len(b)
        q.put(dict(esito="ok", secondi=time.perf_counter() - t0, byte=n, picco_mb=_peak_mb()))
    except Exception as e:
        q.put(dict(esito=f"errore: {e!r}"[:300]))


def _w_read(path, modo, q):
    try:
        from scripts.modules.utils import excel_parser
        with modo_lettura(modo):
            t0 = time.perf_counter()
            df, delim, enc, _, plog = excel_parser.ExcelParser(path).parse_file([], _Log())
            secs = time.perf_counter() - t0
        q.put(dict(esito="ok", secondi=secs, righe=len(df), colonne=df.shape[1], encoding=enc, delimiter=delim,
                   parsing="; ".join(str(x) for x in plog if x), picco_mb=_peak_mb()))
    except Exception as e:
        q.put(dict(esito=f"errore: {e!r}"[:300], dove=traceback.format_exc().strip().splitlines()[-3][:300]))


def _w_pulizia(path, fonte, var_code, q):
    """Lettura come in produzione (non cronometrata), poi pulizia e passo 3 di data_miner cronometrati."""
    try:
        import numpy as np
        from scripts.modules.utils import excel_parser, datatable_cleaner, nuts_region_harmonizer
        from scripts.modules.utils import json_handler as jh
        col_map = jh.JsonHandler(file_tgt=f"{HOME}config/cols_attributes.json", encoding="ISO-8859-1").json_reader()
        numeric_cols = list(col_map.loc[col_map["dtype"] == "numeric", "name_out"])
        conversions = dict(zip(col_map["name_out"], col_map["conversion"]))
        log = _Log()
        df = excel_parser.ExcelParser(path).parse_file([], log)[0]
        righe_lette = len(df)
        t0 = time.perf_counter()
        df, _ = datatable_cleaner.DataFrameCleaner(df=df, log=[], col_MAP=col_map).input_cleaner()
        t_pul = time.perf_counter() - t0
        t_arm, t_tre, arm = 0.0, 0.0, "no (senza CODICE_REGIONE)"
        if "CODICE_REGIONE" in df.columns:
            h = nuts_region_harmonizer.RegionHarmonizer(file_path=f"{HOME}config/codregione_map.json", log=log, s=fonte)
            t0 = time.perf_counter()
            df = h.harmonize_regions(df, numeric_cols=numeric_cols)
            t_arm = time.perf_counter() - t0
            arm = "harmonize_regions"
            if 'ELEN' not in var_code and fonte != 'ISTAT' and set(numeric_cols) & set(df.columns):
                t0 = time.perf_counter()
                df = h.aggregate_trentino_data(df, numeric_cols=numeric_cols, conversions=conversions)
                t_tre = time.perf_counter() - t0
                arm += " + Trentino"
        df = df.replace("-", np.nan)
        q.put(dict(esito="ok", righe_lette=righe_lette, righe_finali=len(df), secondi_pulizia=t_pul,
                   secondi_armonizzazione=t_arm, secondi_trentino=t_tre, passo3=arm, picco_mb=_peak_mb()))
    except Exception as e:
        q.put(dict(esito=f"errore: {e!r}"[:300], dove=traceback.format_exc().strip().splitlines()[-3][:300]))


def run_timeout(target, args, timeout):
    q = mp.Queue()
    p = mp.Process(target=target, args=args + (q,))
    p.start()
    p.join(timeout)
    if p.is_alive():
        p.terminate()
        p.join()
        return dict(esito="timeout")
    try:
        return q.get(timeout=5)
    except Exception:
        return dict(esito=f"errore: processo terminato (codice {p.exitcode})")


# ------------------------------------------------------------------------------------------- volumi
def crea_volume(src, mb, work, fonte):
    """Prefisso del CSV con intestazione e righe intere fino a mb MB; 0 o >= dimensione = file intero."""
    size = os.path.getsize(src)
    if mb <= 0 or mb * 2 ** 20 >= size:
        return src, "intero", size
    os.makedirs(os.path.join(work, fonte), exist_ok=True)
    stem = os.path.splitext(os.path.basename(src))[0]
    dst = os.path.join(work, fonte, f"{stem}__{mb}MB.csv")
    target = mb * 2 ** 20
    if os.path.exists(dst) and abs(os.path.getsize(dst) - target) < 2 ** 20:
        return dst, "riusato", os.path.getsize(dst)
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        n = 0
        for line in fi:
            fo.write(line)
            n += len(line)
            if n >= target:
                break
    return dst, "creato", os.path.getsize(dst)


# ------------------------------------------------------------------------------------------- risultati
def ambiente(a):
    r = dict(eseguito=time.strftime("%Y-%m-%d %H:%M"), python=platform.python_version(), sistema=platform.platform(),
             cpu_logiche=os.cpu_count(), pandas=pd.__version__)
    try:
        import dask
        r["dask"] = dask.__version__
    except Exception:
        r["dask"] = "non disponibile"
    try:
        import psutil
        vm = psutil.virtual_memory()
        r["ram_totale_gb"] = round(vm.total / 2 ** 30, 1)
        r["ram_libera_inizio_gb"] = round(vm.available / 2 ** 30, 1)
        b = psutil.sensors_battery()
        r["alimentazione"] = "desktop" if b is None else ("corrente" if b.power_plugged else "BATTERIA")
        r["cpu_fisiche"] = psutil.cpu_count(logical=False)
    except Exception:
        r["psutil"] = "non disponibile: RAM e alimentazione non registrate"
    r.update(file=a.file, volumi_mb=a.volumi, modi=a.modi, ripetizioni=a.ripetizioni, timeout_s=a.timeout,
             pulizia=not a.no_pulizia, cartella_lavoro=a.work)
    return r


def sintesi(mis):
    m = mis[(mis["prova"] != "lettura_a_vuoto") & (mis["esito"] == "ok")]
    if m.empty:
        return pd.DataFrame()
    g = (m.groupby(["fonte", "file", "volume_mb_reale", "prova"])
         .agg(n_ok=("secondi", "size"), mediana_s=("secondi", "median"), min_s=("secondi", "min"),
              max_s=("secondi", "max"), righe=("righe", "max"), picco_mb_mediana=("picco_mb", "median"))
         .reset_index().rename(columns={"prova": "modo"}))
    g["mb_al_secondo"] = (g["volume_mb_reale"] / g["mediana_s"]).round(1)
    v = mis[mis["prova"] == "lettura_a_vuoto"].groupby(["fonte", "file", "volume_mb_reale"])["secondi"].median()
    g["lettura_a_vuoto_s"] = [v.get((r.fonte, r.file, r.volume_mb_reale)) for r in g.itertuples()]
    piv = g.pivot_table(index=["fonte", "file", "volume_mb_reale"], columns="modo", values="mediana_s")
    for modo, rif in (("c", "python"), ("dask_sync", "python"), ("dask", "python"), ("dask", "c"), ("dask", "dask_sync")):
        if modo in piv and rif in piv:
            col = f"speedup_{modo}_vs_{rif}"
            g[col] = [round(piv.loc[(r.fonte, r.file, r.volume_mb_reale), rif] /
                            piv.loc[(r.fonte, r.file, r.volume_mb_reale), modo], 2)
                      if r.modo == modo and pd.notna(piv.loc[(r.fonte, r.file, r.volume_mb_reale), rif]) else None
                      for r in g.itertuples()]
    righe = m.groupby(["fonte", "file", "volume_mb_reale"])["righe"].nunique()
    g["righe_uguali_tra_modi"] = [bool(righe.get((r.fonte, r.file, r.volume_mb_reale)) == 1) for r in g.itertuples()]
    g["modo_della_pipeline"] = ["dask" if r.volume_mb_reale * 2 ** 20 > 0.3e9 else "python" for r in g.itertuples()]
    return g


def scrivi(path, a, amb, vol, mis, pul):
    readme = pd.DataFrame({"voce": [
        "esperimento", "modi", "lettura_a_vuoto", "pulizia", "protocollo", "speedup", "nota"],
        "valore": [
            "b5 - scalabilita' della lettura dei CSV con e senza Dask (tasks_MPP n.7), volumi crescenti dello stesso file",
            "python = pandas motore Python (pipeline < 300 MB); c = pandas motore C (non usato dalla pipeline); "
            "dask_sync = Dask a un thread; dask = Dask a thread (pipeline > 300 MB). Stessa ExcelParser.parse_file "
            "della pipeline, cambia solo read_on_parallel",
            "lettura dei soli byte del file: limite inferiore dovuto al disco",
            "input_cleaner e passo 3 di data_miner sulla tabella letta come in produzione (una volta per volume)",
            f"ogni misura in un processo separato, timeout {a.timeout} s; modi in ordine ruotato tra le ripetizioni",
            "speedup_X_vs_Y = mediana di Y / mediana di X (>1: X piu' veloce)",
            "tempi validi solo se misurati a PC libero; volume_mb_reale in MiB"]})
    os.makedirs(OUT_DIR, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        readme.to_excel(w, sheet_name="README", index=False)
        pd.DataFrame(list(amb.items()), columns=["voce", "valore"]).to_excel(w, sheet_name="ambiente", index=False)
        pd.DataFrame(vol).to_excel(w, sheet_name="volumi", index=False)
        mdf = pd.DataFrame(mis)
        mdf.to_excel(w, sheet_name="misure", index=False)
        sintesi(mdf).to_excel(w, sheet_name="sintesi", index=False) if len(mdf) else None
        pd.DataFrame(pul).to_excel(w, sheet_name="pulizia", index=False)


# ------------------------------------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--file", default=DEF_FILE)
    p.add_argument("--volumi", default=DEF_VOLUMI)
    p.add_argument("--modi", default=DEF_MODI)
    p.add_argument("--ripetizioni", type=int, default=3)
    p.add_argument("--timeout", type=float, default=3600)
    p.add_argument("--no-pulizia", action="store_true")
    p.add_argument("--work", default=os.environ.get("MEDITA_B5_WORK", r"D:\MEDITA_b5_work"))
    a = p.parse_args()
    modi = [m for m in a.modi.split(",") if m]
    bad = [m for m in modi if m not in ("python", "c", "dask_sync", "dask")]
    if bad:
        sys.exit(f"Modi sconosciuti: {bad}")
    volumi = sorted({int(v) for v in a.volumi.split(",") if v.strip()}, key=lambda v: (v == 0, v))
    out = f"{OUT_DIR}b5_scalabilita_{STAMP}.xlsx"
    amb = ambiente(a)
    vol, mis, pul = [], [], []
    keep_awake(True)
    t_start = time.time()
    try:
        # volumi
        piani = []
        for spec in [s for s in a.file.split(",") if s]:
            fonte, nome = spec.split(":", 1)
            snap = snapshot_di(fonte)
            src = f"{HOME}data/input/{fonte}/{snap}/{nome}"
            vc = var_code_di(fonte, nome)
            for mb in volumi:
                path, come, size = crea_volume(src, mb, a.work, fonte)
                mbr = round(size / 2 ** 20, 1)
                if any(x["path"] == path for x in vol):
                    continue   # piu' volumi richiesti oltre la dimensione del file = file intero una volta sola
                vol.append(dict(fonte=fonte, snapshot=snap, var_code=vc, file=nome, volume_richiesto_mb=mb,
                                volume_mb_reale=mbr, path=path, origine=come))
                piani.append((fonte, nome, vc, path, mbr))
                print(f"volume {fonte} {nome} {mbr} MB ({come})", flush=True)
        scrivi(out, a, amb, vol, mis, pul)

        # letture
        for rep in range(1, a.ripetizioni + 1):
            ordine = modi[(rep - 1) % len(modi):] + modi[:(rep - 1) % len(modi)]
            saltati = set()
            for fonte, nome, vc, path, mbr in piani:
                base = dict(ripetizione=rep, fonte=fonte, file=nome, volume_mb_reale=mbr)
                r = run_timeout(_w_raw, (path,), a.timeout)
                mis.append(dict(base, prova="lettura_a_vuoto", ordine=0, **r))
                for k, modo in enumerate(ordine, start=1):
                    if (nome, modo) in saltati:
                        mis.append(dict(base, prova=modo, ordine=k, esito="saltato (timeout a un volume minore)"))
                        continue
                    r = run_timeout(_w_read, (path, modo), a.timeout)
                    if r.get("esito") == "timeout":
                        saltati.add((nome, modo))
                    mis.append(dict(base, prova=modo, ordine=k, **r))
                    print(f"  rip {rep} {nome} {mbr} MB {modo}: {r.get('esito')} "
                          f"{'' if r.get('secondi') is None else round(r['secondi'], 1)} s", flush=True)
                    scrivi(out, a, amb, vol, mis, pul)

        # pulizia e armonizzazione (una volta per volume)
        if not a.no_pulizia:
            for fonte, nome, vc, path, mbr in piani:
                r = run_timeout(_w_pulizia, (path, fonte, vc), a.timeout)
                pul.append(dict(fonte=fonte, file=nome, var_code=vc, volume_mb_reale=mbr, **r))
                print(f"  pulizia {nome} {mbr} MB: {r.get('esito')}", flush=True)
                scrivi(out, a, amb, vol, mis, pul)
        amb["durata_totale_min"] = round((time.time() - t_start) / 60, 1)
        scrivi(out, a, amb, vol, mis, pul)
        print(f"\nRisultati: {out}\nDurata: {amb['durata_totale_min']} min")
    finally:
        keep_awake(False)


if __name__ == "__main__":
    mp.freeze_support()
    main()
