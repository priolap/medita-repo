# -*- coding: utf-8 -*-
r"""
b4_verifica_ith0.py  (MEDITA, task B - superkey e aggregazione del Trentino, snapshot unico 29/10/2026)

Controllo a valle, sulle tabelle gia' trasformate, delle righe regionali del Trentino-Alto Adige (ITH0)
che la Transform aggiunge da Bolzano (ITH1) e Trento (ITH2) (RegionHarmonizer.aggregate_trentino_data,
PATCH_TRENTINO_SUPERKEY). Sostituisce trentino_attiva.py (archiviato), che sulle tabelle nuove salterebbe
tutto perche' ITH0 c'e' gia'. Sola lettura.

Per ogni tabella di data\output\<FONTE>\<snapshot piu' recente>\ con CODICE_REGIONE:
  righe, righe_ITH0/ITH1/ITH2
  misure_somma / misure_media    colonne numeriche del dizionario presenti, per regola di conversione
  scarto_max_totale              max su ogni misura 'sum' di |somma ITH0 - (somma ITH1 + somma ITH2)| / (ITH1+ITH2)
  scarto_max_per_anno            lo stesso, anno per anno (se c'e' ANNO)
  dup_ITH0                       righe ITH0 che ripetono le stesse colonne descrittive (attese 0)
  celle_MERGED                   celle descrittive ITH0 valorizzate 'MERGED' (attributo diverso tra le province)
  esito                          OK / ITH0 da verificare / senza ITH0 (motivo) / errore
Le misure 'mean' (4 nel dizionario) non si controllano con le somme: sono contate e segnalate.
Le tabelle grandi si leggono a blocchi tenendo solo le righe ITH0/ITH1/ITH2.

Scrive experiments\B_superkey\out\verifica_ith0_<data_ora>.xlsx (fogli tabelle, per_anno, README).

Uso (cmd), dalla cartella MEDITA:
  "C:\Program Files\Python314\python.exe" experiments\B_superkey\b4_verifica_ith0.py
Opzioni: --sources MINIS,AIFA (default; ISTAT pubblica gia' ITH0 e non e' aggregata)  --tol 1e-9
"""
import os
import sys
import time
import argparse

import numpy as np
import pandas as pd

HOME = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")).replace("\\", "/") + "/"
PROV = ["ITH1", "ITH2"]
CHUNK = 500_000
TERR = {"CODICE_REGIONE", "REGIONE", "UNITA_ADMIN"}


def dizionario():
    cm = pd.read_json(f"{HOME}config/cols_attributes.json", encoding="ISO-8859-1")
    num = set(cm.loc[cm["dtype"] == "numeric", "name_out"])
    conv = dict(zip(cm["name_out"], cm["conversion"]))
    return num, conv


def leggi_trentino(path):
    cols = pd.read_csv(path, sep="|", nrows=0).columns.tolist()
    if "CODICE_REGIONE" not in cols:
        return cols, None, 0
    parti, n = [], 0
    for ch in pd.read_csv(path, sep="|", dtype=str, keep_default_na=False, na_values=[""], chunksize=CHUNK):
        n += len(ch)
        parti.append(ch[ch["CODICE_REGIONE"].isin(["ITH0"] + PROV)])
    return cols, pd.concat(parti, ignore_index=True), n


def rel(a, b):
    if pd.isna(a) and pd.isna(b):
        return 0.0
    if pd.isna(a) or pd.isna(b):
        return np.inf
    return abs(a - b) / abs(b) if b else (0.0 if a == 0 else np.inf)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="MINIS,AIFA")
    ap.add_argument("--tol", type=float, default=1e-9)
    a = ap.parse_args()
    num, conv = dizionario()
    righe, anni = [], []
    for src in a.sources.split(","):
        base = f"{HOME}data/output/{src}/"
        snaps = sorted([d for d in os.listdir(base) if d.isdigit() and os.path.isdir(base + d)], reverse=True)
        if not snaps:
            continue
        snap = snaps[0]
        for f in sorted(x for x in os.listdir(base + snap) if x.endswith(".txt")):
            tab, t0 = f[:-4], time.time()
            r = dict(fonte=src, snapshot=snap, tabella=tab)
            try:
                cols, s, n = leggi_trentino(base + snap + "/" + f)
                r["righe"] = n
                if s is None:
                    r["esito"] = "senza CODICE_REGIONE (tabella anagrafica)"
                    righe.append(r); continue
                cnt = s["CODICE_REGIONE"].value_counts()
                r.update(righe_ITH0=int(cnt.get("ITH0", 0)), righe_ITH1=int(cnt.get("ITH1", 0)),
                         righe_ITH2=int(cnt.get("ITH2", 0)))
                meas = [c for c in cols if c in num]
                ms = [c for c in meas if str(conv.get(c, "sum")).lower() not in ("mean", "avg")]
                mm = [c for c in meas if c not in ms]
                r.update(misure_somma=len(ms), misure_media=len(mm))
                if r["righe_ITH1"] + r["righe_ITH2"] == 0:
                    r["esito"] = "senza righe ITH1/ITH2"
                elif r["righe_ITH0"] == 0:
                    r["esito"] = ("senza ITH0: nessuna misura" if not meas else
                                  "senza ITH0: elenco ELEN (escluso dall'aggregazione)" if "ELEN" in tab else
                                  "senza ITH0: DA VERIFICARE")
                else:
                    th0, pv = s[s["CODICE_REGIONE"] == "ITH0"], s[s["CODICE_REGIONE"].isin(PROV)]
                    sc_tot, sc_anno = 0.0, 0.0
                    for c in ms:
                        x0 = pd.to_numeric(th0[c], errors="coerce")
                        xp = pd.to_numeric(pv[c], errors="coerce")
                        sc_tot = max(sc_tot, rel(x0.sum(min_count=1), xp.sum(min_count=1)))
                        if "ANNO" in cols:
                            g0 = x0.groupby(th0["ANNO"]).sum(min_count=1)
                            gp = xp.groupby(pv["ANNO"]).sum(min_count=1)
                            for y in sorted(set(g0.index) | set(gp.index)):
                                e = rel(g0.get(y, np.nan), gp.get(y, np.nan))
                                sc_anno = max(sc_anno, e)
                                if e > a.tol:
                                    anni.append(dict(fonte=src, tabella=tab, misura=c, ANNO=y,
                                                     somma_ITH0=g0.get(y, np.nan), somma_ITH1_ITH2=gp.get(y, np.nan),
                                                     scarto_relativo=e))
                    desc = [c for c in cols if c not in meas and c not in TERR]
                    r.update(scarto_max_totale=sc_tot, scarto_max_per_anno=sc_anno if "ANNO" in cols else None,
                             dup_ITH0=int(th0.duplicated(subset=desc).sum()) if desc else 0,
                             celle_MERGED=int((th0[desc] == "MERGED").sum().sum()) if desc else 0)
                    ok = sc_tot <= a.tol and (sc_anno <= a.tol) and r["dup_ITH0"] == 0
                    r["esito"] = "OK" if ok else "ITH0 da verificare"
                    if ok and mm:
                        r["esito"] = f"OK (somme); {len(mm)} misure 'mean' non controllate"
            except Exception as e:
                r["esito"] = f"errore: {e!r}"[:300]
            r["secondi"] = round(time.time() - t0, 1)
            righe.append(r)
            print(f"{src} {tab}: {r['esito']}")

    df = pd.DataFrame(righe)
    readme = pd.DataFrame({"voce": ["eseguito", "fonti", "tolleranza", "nota"],
                           "valore": [time.strftime("%Y-%m-%d %H:%M"), a.sources, a.tol,
                                      "scarto relativo |ITH0 - (ITH1+ITH2)| / (ITH1+ITH2) sulle misure 'sum'; "
                                      "dup_ITH0 sulle colonne descrittive (escluse quelle territoriali)"]})
    out_dir = f"{HOME}experiments/B_superkey/out/"
    os.makedirs(out_dir, exist_ok=True)
    out = f"{out_dir}verifica_ith0_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        readme.to_excel(w, sheet_name="README", index=False)
        df.to_excel(w, sheet_name="tabelle", index=False)
        pd.DataFrame(anni, columns=["fonte", "tabella", "misura", "ANNO", "somma_ITH0", "somma_ITH1_ITH2",
                                    "scarto_relativo"]).to_excel(w, sheet_name="per_anno", index=False)
    print("\n" + df["esito"].str.split(":").str[0].str.split(" \\(").str[0].value_counts().to_string())
    print(f"\nRisultati: {out}")


if __name__ == "__main__":
    main()
