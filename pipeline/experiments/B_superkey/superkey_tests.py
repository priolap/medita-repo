# -*- coding: utf-8 -*-
"""
b4 - Superkey (tasks_MPP n.6): casi limite, tempi su dati sintetici, tempi sulle tabelle reali.

Prova le funzioni della pipeline cosi' come sono (non le modifica):
  superkey_finder.find_super_key(df)
      per r = 1..n prova le combinazioni di r colonne nell'ordine di itertools.combinations e restituisce la
      prima per cui df.duplicated(subset) e' tutto False; None se nessuna (righe identiche).
  RegionHarmonizer.aggregate_trentino_data(df, numeric_cols)
      l'unico chiamante di find_super_key; in data_miner la chiamata e' commentata (dal 2024).

Parti (tutte per default):
  casi     casi limite con esito atteso / ottenuto
  sintetici  tempi e combinazioni provate per n colonne x N righe x tipo di chiave (timeout per caso)
  reali    tempi su ogni tabella in data/output/<FONTE>/<snapshot piu' recente>/ (colonne non numeriche),
           sull'intera tabella e sulle sole righe ITH1/ITH2 (l'uso previsto nell'aggregazione del Trentino)

Scrive solo experiments/B_superkey/out/superkey_tests_<data_ora>.xlsx.
Uso (da MEDITA):  python experiments/B_superkey/superkey_tests.py
Opzioni: --parti casi,sintetici,reali  --sources MINIS,AIFA,ISTAT  --timeout 120  --max-n 16 (il timeout comprende la lettura del file)
"""
import argparse
import math
import multiprocessing as mp
import os
import sys
import time
import traceback
from itertools import combinations

HOME = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")).replace("\\", "/") + "/"
sys.path.insert(0, HOME)

import numpy as np
import pandas as pd

from scripts.modules.utils import superkey_finder, nuts_region_harmonizer
from scripts.modules.utils import json_handler as jh


class _Log:
    def __init__(self):
        self.m = []

    def _w(self, x, *a, **k):
        self.m.append(str(x))

    debug = info = warning = error = critical = exception = _w


def combos_tested(cols, key):
    """Quante combinazioni prova find_super_key prima di restituire key (stesso ordine di iterazione)."""
    n = len(cols)
    if key is None:
        return 2 ** n - 1
    k, cnt = len(key), sum(math.comb(n, r) for r in range(1, len(key)))
    for sub in combinations(cols, k):
        cnt += 1
        if list(sub) == list(key):
            return cnt
    return None


def numeric_cols():
    cm = jh.JsonHandler(f"{HOME}config/cols_attributes.json", "ISO-8859-1").json_reader()
    return list(cm.loc[cm['dtype'] == 'numeric', 'name_out'])


# ------------------------------------------------------------------------------------------- casi limite
def casi_limite():
    rows = []

    def sk(nome, df, atteso, nota=""):
        try:
            got = superkey_finder.find_super_key(df)
            esito = "coincide" if got == atteso else "diverso"
            got_s = repr(got)
        except Exception as e:
            got_s, esito = f"ERRORE {e!r}", "errore"
        rows.append(dict(funzione="find_super_key", caso=nome, colonne=", ".join(map(str, df.columns)),
                         righe=len(df), atteso=repr(atteso), ottenuto=got_s, esito=esito, nota=nota))

    sk("tabella vuota", pd.DataFrame(columns=["A", "B"]), ["A"],
       "nessuna riga = nessun duplicato: qualunque colonna e' chiave, restituisce la prima (degenere)")
    sk("una riga", pd.DataFrame({"A": [1], "B": [2]}), ["A"], "come sopra")
    sk("righe identiche", pd.DataFrame({"A": [1, 1], "B": [2, 2]}), None, "nessuna chiave -> None")
    sk("colonna costante", pd.DataFrame({"C": ["x", "x", "x"], "B": [1, 2, 3]}), ["B"], "")
    sk("due chiavi minime, ordine X,Y", pd.DataFrame({"X": [1, 2], "Y": [3, 4]}), ["X"],
       "vince la prima nell'ordine delle colonne")
    sk("due chiavi minime, ordine Y,X", pd.DataFrame({"Y": [3, 4], "X": [1, 2]}), ["Y"],
       "stessi dati, colonne invertite: chiave diversa")
    sk("NaN ripetuti", pd.DataFrame({"A": [np.nan, np.nan], "B": [1, 2]}), ["B"],
       "duplicated considera uguali due NaN")
    sk("'nan' testo (output della pipeline)", pd.DataFrame({"A": ["nan", "nan"], "B": ["1", "2"]}), ["B"],
       "input_cleaner trasforma NaN nella stringa 'nan'")
    sk("tipi misti '1' e 1", pd.DataFrame({"A": ["1", 1], "B": ["x", "x"]}), None,
       "stesso valore per un lettore, diverso per duplicated: A risulta chiave")
    sk("spazi e maiuscole", pd.DataFrame({"A": ["Roma", "ROMA "], "B": ["x", "x"]}), None,
       "differenze di formato rendono A chiave")
    sk("chiave composta di 3 colonne", pd.DataFrame({"A": [1, 1, 1, 1, 2, 2, 2, 2], "B": [1, 1, 2, 2, 1, 1, 2, 2],
                                                      "C": [1, 2, 1, 2, 1, 2, 1, 2], "D": [0] * 8}),
       ["A", "B", "C"], "")

    # aggregate_trentino_data
    num = ["VALORE"]

    def base(extra=None):
        d = {"CODICE_REGIONE": ["ITH1", "ITH2", "ITH1", "ITH2", "ITC1", "ITC1"],
             "REGIONE": ["TRENTINO-ALTO ADIGE"] * 4 + ["PIEMONTE"] * 2,
             "UNITA_ADMIN": ["PROV. AUTON. BOLZANO", "PROV. AUTON. TRENTO"] * 2 + ["PIEMONTE"] * 2,
             "ANNO": ["2020", "2020", "2021", "2021", "2020", "2021"],
             "VALORE": ["10", "20", "30", "40", "100", "200"]}
        d.update(extra or {})
        return pd.DataFrame(d)

    def ag(nome, df, atteso, check, conv=None):  # PATCH_TRENTINO_SUPERKEY
        log = _Log()
        h = nuts_region_harmonizer.RegionHarmonizer(file_path=f"{HOME}config/codregione_map.json", log=log, s="MINIS")
        try:
            out = h.aggregate_trentino_data(df.copy(), numeric_cols=num, conversions=conv)
            th0 = out[out["CODICE_REGIONE"] == "ITH0"]
            got = f"{len(th0)} righe ITH0, VALORE={sorted(pd.to_numeric(th0['VALORE']).tolist())}"
            esito = "coincide" if check(th0) else "diverso"
        except Exception as e:
            got, esito = f"ERRORE {e!r}", "errore"
        percorso = " | ".join(m for m in log.m if m.startswith("Trentino"))
        rows.append(dict(funzione="aggregate_trentino_data", caso=nome, colonne=", ".join(df.columns), righe=len(df),
                         atteso=atteso, ottenuto=got, esito=esito, nota=percorso))

    ag("regione x anno, senza anagrafica", base(), "2 righe ITH0: 30 (2020), 70 (2021)",
       lambda t: sorted(pd.to_numeric(t["VALORE"]).tolist()) == [30, 70])
    ag("con colonna anagrafica uguale tra le province (COMUNE)", base({"COMUNE": ["X"] * 6}),
       "2 righe ITH0: 30, 70 (COMUNE = MERGED)", lambda t: sorted(pd.to_numeric(t["VALORE"]).tolist()) == [30, 70])
    ag("con colonna anagrafica diversa (CODICE_ASL)", base({"CODICE_ASL": ["101", "201", "101", "201", "301", "301"]}),
       "2 righe ITH0: 30, 70", lambda t: sorted(pd.to_numeric(t["VALORE"]).tolist()) == [30, 70])
    ag("colonna descrittiva non anagrafica che distingue le province (PROVINCIA)",
       base({"PROVINCIA": ["BZ", "TN", "BZ", "TN", "TO", "TO"]}),
       "2 righe ITH0: 30, 70", lambda t: sorted(pd.to_numeric(t["VALORE"]).tolist()) == [30, 70])
    ag("Trentino gia' presente nella fonte (ITH0)",
       pd.concat([base(), pd.DataFrame({"CODICE_REGIONE": ["ITH0", "ITH0"], "REGIONE": ["TRENTINO-ALTO ADIGE"] * 2,
                                        "UNITA_ADMIN": ["TRENTINO-ALTO ADIGE"] * 2, "ANNO": ["2020", "2021"],
                                        "VALORE": ["30", "70"]})], ignore_index=True),
       "2 righe ITH0 (quelle della fonte), nessun doppio", lambda t: len(t) == 2)
    ag("nessuna riga ITH1/ITH2", base().iloc[4:].reset_index(drop=True), "tabella invariata, 0 righe ITH0",
       lambda t: len(t) == 0)
    ag("valori non numerici ('nan', '-')", base({"VALORE": ["10", "nan", "30", "-", "100", "200"]}),
       "2 righe ITH0: 10, 30 (i mancanti non contano)", lambda t: sorted(pd.to_numeric(t["VALORE"]).tolist()) == [10, 30])
    ag("misura media (conversion = mean)", base(), "2 righe ITH0: 15 (2020), 35 (2021)",
       lambda t: sorted(pd.to_numeric(t["VALORE"]).tolist()) == [15, 35], conv={"VALORE": "mean"})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------- tempi (processo separato, con timeout)
def _worker_synth(n, N, tipo, q):
    rng = np.random.default_rng(0)
    df = pd.DataFrame({f"c{j}": rng.integers(0, 5, N) for j in range(n)})
    if tipo == "chiave_prima":
        df["c0"] = np.arange(N)
    elif tipo == "chiave_ultime_2":
        k = math.ceil(math.sqrt(N))
        df[f"c{n - 2}"] = np.arange(N) // k
        df[f"c{n - 1}"] = np.arange(N) % k
    elif tipo == "nessuna":
        df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    t0 = time.perf_counter()
    key = superkey_finder.find_super_key(df)
    q.put((key, time.perf_counter() - t0, list(df.columns)))


def _worker_real(path, numcols, subset, q):
    df = pd.read_csv(path, delimiter='|', dtype=str, keep_default_na=False, na_values=[''])
    if subset:
        if 'CODICE_REGIONE' not in df.columns:
            q.put(("n/a", None, None, 0)); return
        df = df[df['CODICE_REGIONE'].isin(['ITH1', 'ITH2'])].drop_duplicates()
        if df.empty:
            q.put(("n/a", None, None, 0)); return
    cols = [c for c in df.columns if c not in set(numcols)]
    t0 = time.perf_counter()
    key = superkey_finder.find_super_key(df[cols])
    q.put((key, time.perf_counter() - t0, cols, len(df)))


def run_timeout(target, args, timeout):
    q = mp.Queue()
    p = mp.Process(target=target, args=args + (q,))
    p.start()
    p.join(timeout)
    if p.is_alive():
        p.terminate(); p.join()
        return None
    return q.get() if not q.empty() else "errore"


def sintetici(timeout, max_n):
    rows = []
    for tipo in ("chiave_prima", "chiave_ultime_2", "nessuna"):
        for N in (1_000, 10_000, 100_000):
            for n in range(4, max_n + 1, 2):
                r = run_timeout(_worker_synth, (n, N, tipo), timeout)
                if r is None:
                    rows.append(dict(tipo=tipo, n_colonne=n, n_righe=N, chiave="(timeout)", secondi=f">{timeout}",
                                     combinazioni=None, combinazioni_max=2 ** n - 1))
                    print(f"  sintetico {tipo} n={n} N={N}: timeout")
                    continue
                key, secs, cols = r
                rows.append(dict(tipo=tipo, n_colonne=n, n_righe=N, chiave=repr(key), secondi=round(secs, 4),
                                 combinazioni=combos_tested(cols, key), combinazioni_max=2 ** n - 1))
                print(f"  sintetico {tipo} n={n} N={N}: {secs:.3f}s")
    return pd.DataFrame(rows)


def reali(sources, timeout):
    numcols = numeric_cols()
    rows = []
    for src in sources:
        base = f"{HOME}data/output/{src}/"
        if not os.path.isdir(base):
            continue
        snaps = sorted([d for d in os.listdir(base) if d.isdigit() and os.path.isdir(base + d)], reverse=True)
        if not snaps:
            continue
        snap = snaps[0]
        for f in sorted(os.listdir(base + snap)):
            if not f.endswith(".txt"):
                continue
            path = f"{base}{snap}/{f}"
            for subset in (False, True):
                r = run_timeout(_worker_real, (path, numcols, subset), timeout)
                row = dict(fonte=src, snapshot=snap, tabella=f[:-4], righe_usate="solo ITH1/ITH2" if subset else "tutte",
                           mb=round(os.path.getsize(path) / 1e6, 1))
                if r is None:
                    row.update(chiave="(timeout)", secondi=f">{timeout}")
                elif r == "errore":
                    row.update(chiave="(errore)")
                elif r[0] == "n/a":
                    row.update(chiave="(nessuna riga ITH1/ITH2)")
                else:
                    key, secs, cols, n = r
                    row.update(n_righe=n, n_colonne_descrittive=len(cols), chiave="; ".join(key) if key else "None",
                               r=len(key) if key else None, secondi=round(secs, 4), combinazioni=combos_tested(cols, key))
                rows.append(row)
                print(f"  {src} {f} [{row['righe_usate']}]: {row.get('chiave')} {row.get('secondi', '')}")
    return pd.DataFrame(rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--parti", default="casi,sintetici,reali")
    p.add_argument("--sources", default="MINIS,AIFA,ISTAT")
    p.add_argument("--timeout", type=float, default=120)
    p.add_argument("--max-n", type=int, default=16)
    a = p.parse_args()
    parti = a.parti.split(",")
    out = {}
    if "casi" in parti:
        out["casi_limite"] = casi_limite()
        print(out["casi_limite"][["funzione", "caso", "esito"]].to_string())
    if "sintetici" in parti:
        out["tempi_sintetici"] = sintetici(a.timeout, a.max_n)
    if "reali" in parti:
        out["tempi_reali"] = reali(a.sources.split(","), a.timeout)
    readme = pd.DataFrame({"voce": ["eseguito", "timeout (s)", "algoritmo", "complessita'", "nota"],
                           "valore": [time.strftime("%Y-%m-%d %H:%M"), a.timeout,
                                      "ricerca esaustiva per grandezza crescente (itertools.combinations), "
                                      "si ferma alla prima combinazione senza duplicati",
                                      "O(N * somma_{r<=k} C(n,r)) con k = grandezza della chiave trovata; "
                                      "O(N * 2^n) se non esiste chiave",
                                      "combinazioni = combinazioni provate fino alla chiave (stesso ordine della funzione)"]})
    os.makedirs(f"{HOME}experiments/B_superkey/out", exist_ok=True)
    path = f"{HOME}experiments/B_superkey/out/superkey_tests_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        readme.to_excel(w, sheet_name="README", index=False)
        for k, v in out.items():
            v.to_excel(w, sheet_name=k, index=False)
    print(f"\nRisultati: {path}")


if __name__ == "__main__":
    main()
