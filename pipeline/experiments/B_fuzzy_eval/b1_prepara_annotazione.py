# -*- coding: utf-8 -*-
r"""
b1_prepara_annotazione.py  (MEDITA, task B - gold standard del fuzzy, snapshot unico 29/10/2026)

Prepara il file da annotare/validare per le statistiche del fuzzy (b4_stats.py stats), a partire dai fuzzy
log di PRODUZIONE dello snapshot unico (letture complete, niente dry run):
    logs\fuzzy\fuzzy_log_MINIS_20261025_20261025_200056.csv
    logs\fuzzy\fuzzy_log_AIFA_20261025_20261025_210407.csv
    logs\fuzzy\fuzzy_log_ISTAT_20261027_20261028_205139.csv

1. tiene le righe in cui il fuzzy viene chiamato (step canonical / files / sheets, con ratio; esclusi
   identical_columns e new_group, dove non c'e' confronto), come "b4_stats.py estrai";
2. ESCLUDE le righe del file MINIS con errore della fonte (decisione 29/10/2026):
     scambi_di_alimenti_di_origine_animale_01_07_2024_31_12_2024.csv  (ALIM_EXCHANGE_VIVI, 2° sem. 2024):
     ogni riga del CSV e' racchiusa tra virgolette, la pipeline la legge come una sola colonna.
   Sono escluse sia le righe con quel file sia i confronti del file successivo con quel file (file_prev);
3. riporta le etichette gia' validate (gold standard 2025, fuzzy_annotato.xlsx nell'archivio) sulle coppie
   identiche (step, colonna, candidato): il fuzzy e' deterministico e il ratio e' lo stesso;
4. per le coppie nuove usa le bozze di bozze_claude_2026.csv (da validare; LABEL vuota = da annotare).

Scrive experiments\B_fuzzy_eval\out\fuzzy_annotato_2026.xlsx con i fogli:
  Annotazione     una riga per applicazione del fuzzy (input di b4_stats.py stats); colonna 'fonte':
                  "B3 2025" / "Claude 2025" = etichetta gia' validata, "bozza Claude 2026" = da validare
  coppie_nuove    le coppie distinte nuove, con la bozza: si valida QUI (LABEL, NOTE), poi si rilancia
                  questo script con --validate per riportarle nel foglio Annotazione
  escluse         righe tolte per l'errore della fonte
  riepilogo       conteggi
Non modifica i log ne' l'archivio.

Uso (cmd), dalla cartella MEDITA:
  "C:\Program Files\Python314\python.exe" experiments\B_fuzzy_eval\b1_prepara_annotazione.py
  (dopo aver validato il foglio coppie_nuove di fuzzy_annotato_2026.xlsx:)
  "C:\Program Files\Python314\python.exe" experiments\B_fuzzy_eval\b1_prepara_annotazione.py --validate
"""
import os
import sys
import argparse
import datetime as dt

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.abspath(os.path.join(HERE, "..", ".."))
LOGS = [os.path.join(HOME, "logs", "fuzzy", f) for f in (
    "fuzzy_log_MINIS_20261025_20261025_200056.csv",
    "fuzzy_log_AIFA_20261025_20261025_210407.csv",
    "fuzzy_log_ISTAT_20261027_20261028_205139.csv")]
ESCLUSI = {"scambi_di_alimenti_di_origine_animale_01_07_2024_31_12_2024.csv":
           "errore della fonte: ogni riga tra virgolette, letta come una sola colonna (decisione 29/10/2026)"}
OLD = os.path.join(HOME, "experiments", "old", "prima_del_rerun_20261029", "B_fuzzy_eval", "out", "fuzzy_annotato.xlsx")
BOZZE = os.path.join(HERE, "bozze_claude_2026.csv")
OUT = os.path.join(HERE, "out", "fuzzy_annotato_2026.xlsx")
STEPS = ("canonical", "files", "sheets")
SKIP = ("identical_columns", "new_group")
COLS = ["source", "snapshot", "var_code", "file_prev", "file", "sheet", "step", "num", "item_a", "item_b",
        "ratio", "threshold", "decision", "examples", "LABEL", "NOTE", "fonte"]
KEY = ["step", "item_a", "item_b"]


def leggi_log():
    righe = []
    for p in LOGS:
        if not os.path.exists(p):
            sys.exit(f"STOP: log non trovato: {p}")
        f = pd.read_csv(p, dtype=str, keep_default_na=False)
        righe.append(f[f.step.isin(STEPS) & ~f.decision.isin(SKIP) & (f.ratio != "")])
    return pd.concat(righe, ignore_index=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true",
                    help="riporta nel foglio Annotazione le etichette del foglio coppie_nuove gia' validato")
    a = ap.parse_args()

    log = leggi_log()
    excl = log.file.isin(ESCLUSI) | log.file_prev.isin(ESCLUSI)
    escluse = log[excl].copy()
    escluse["motivo"] = [ESCLUSI.get(f) or ESCLUSI.get(fp) for f, fp in zip(escluse.file, escluse.file_prev)]
    ann = log[~excl].copy()

    old = pd.read_excel(OLD, sheet_name=0, dtype=str).fillna("")
    old = old.drop_duplicates(KEY).set_index(KEY)
    if a.validate:
        if not os.path.exists(OUT):
            sys.exit(f"STOP: {OUT} non esiste: lanciare prima senza --validate.")
        nuove = pd.read_excel(OUT, sheet_name="coppie_nuove", dtype=str).fillna("")
        fonte_nuove = "validata 2026"
    else:
        nuove = pd.read_csv(BOZZE, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        fonte_nuove = "bozza Claude 2026"
    nuove = nuove.drop_duplicates(KEY).set_index(KEY)

    lab, note, fonte = [], [], []
    for k in zip(ann.step, ann.item_a, ann.item_b):
        if a.validate and k in nuove.index and k in old.index:  # PATCH_B1_CORREZIONI_261029: correzione di un'etichetta 2025
            r, r0 = nuove.loc[k], old.loc[k]
            lab.append(r["LABEL"]); note.append(r["NOTE"])
            fonte.append(f"corretta 2026 (2025: {r0['LABEL']})" if r["LABEL"] != r0["LABEL"] else f"{r0['fonte']} 2025")
        elif k in old.index:
            r = old.loc[k]
            lab.append(r["LABEL"]); note.append(r["NOTE"]); fonte.append(f"{r['fonte']} 2025")
        elif k in nuove.index:
            r = nuove.loc[k]
            lab.append(r["LABEL"]); note.append(r["NOTE"]); fonte.append(fonte_nuove)
        else:
            lab.append(""); note.append(""); fonte.append("da annotare")
    ann["LABEL"], ann["NOTE"], ann["fonte"] = lab, note, fonte
    ann = ann[COLS]

    dist = ann.drop_duplicates(KEY)
    is_new = ~dist.fonte.str.endswith("2025")
    coppie_nuove = dist[is_new][["source", "step", "var_code", "item_a", "item_b", "ratio", "decision",
                                 "examples", "LABEL", "NOTE", "fonte"]]
    rie = [("righe dei log in cui interviene il fuzzy", len(log)),
           ("righe escluse (errore della fonte)", int(excl.sum())),
           ("righe valutate (applicazioni del fuzzy)", len(ann)),
           ("coppie distinte (step, colonna, candidato)", len(dist)),
           ("coppie con etichetta 2025 riportata", int((~is_new).sum())),
           ("coppie nuove", int(is_new.sum())),
           ("coppie nuove senza etichetta", int((is_new & (dist.LABEL.str.strip() == "")).sum()))]
    for (src, st), g in dist.groupby(["source", "step"]):
        rie.append((f"coppie {src} {st}", len(g)))
    for L, g in dist.groupby(dist.LABEL.replace("", "(vuota)")):
        rie.append((f"coppie con LABEL {L}", len(g)))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if os.path.exists(OUT):   # niente sovrascritture silenziose: la versione precedente resta con data e ora
        os.replace(OUT, OUT.replace(".xlsx", f"_{dt.datetime.now():%Y%m%d_%H%M%S}.xlsx"))
    with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
        ann.to_excel(xw, sheet_name="Annotazione", index=False)
        coppie_nuove.to_excel(xw, sheet_name="coppie_nuove", index=False)
        escluse.to_excel(xw, sheet_name="escluse", index=False)
        pd.DataFrame(rie, columns=["voce", "valore"]).to_excel(xw, sheet_name="riepilogo", index=False)
    for v, n in rie:
        print(f"  {v:48s} {n}")
    print(f"\nScritto {OUT}")


if __name__ == "__main__":
    main()
