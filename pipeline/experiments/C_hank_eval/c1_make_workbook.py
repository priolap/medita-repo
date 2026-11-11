# -*- coding: utf-8 -*-
"""
C1a - Crea il workbook di selezione delle domande candidate (task C9).

Input : c1_candidates.json (240 candidate: 80 LOW, 80 MID, 80 HIGH)
        qa_list_setup_final.xlsx (le 100 domande del paper, solo come riferimento)
Output: annotation/c1_candidati.xlsx
          - candidates : una riga per candidata; KEEP gia' "si'": metti "no" su quelle da
                         scartare; QUESTION si puo' correggere (LEN_CHAR si aggiorna da sola)
          - stats      : conteggi e lunghezza media per livello delle tenute, con i target
          - paper_100  : le 100 domande del paper con livello e lunghezza

Non sovrascrive un workbook gia' esistente (per non perdere le tue scelte):
usa --force solo se vuoi rigenerarlo da zero.

Uso:  python c1_make_workbook.py [--force]
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

HERE = Path(__file__).resolve().parent
CFG = json.load(open(HERE / "config_c.json", encoding="utf-8"))
OUT = HERE / "annotation" / "c1_candidati.xlsx"
LEVELS = ["LOW", "MID", "HIGH"]


def resolve(p):
    return Path(p.replace("{rag_root}", CFG["rag_root"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if OUT.exists() and not args.force:
        sys.exit(f"[STOP] {OUT} esiste gia'. Usa --force per rigenerarlo (perdi le modifiche).")

    cand = json.load(open(HERE / "c1_candidates.json", encoding="utf-8"))["questions"]
    paper = pd.read_excel(resolve(CFG["qa_list"]), sheet_name="questions", header=1)[["ID", "LEVEL", "QUESTION"]]
    n_paper = paper["LEVEL"].value_counts().to_dict()
    target_total = 100  # per livello, sulle 300 finali

    wb = Workbook()
    bold = Font(bold=True)
    head = PatternFill("solid", fgColor="DDDDDD")

    # --- candidates
    ws = wb.active
    ws.title = "candidates"
    cols = ["C_ID", "LEVEL_DESIGN", "QUESTION", "LEN_CHAR", "TOPIC", "KEEP", "NOTE"]
    ws.append(cols)
    for c in ws[1]:
        c.font, c.fill = bold, head
    for i, q in enumerate(cand, start=2):
        ws.append([q["C_ID"], q["LEVEL_DESIGN"], q["QUESTION"], f"=LEN(C{i})", q["TOPIC"], "sì", ""])
    last = len(cand) + 1
    dv = DataValidation(type="list", formula1='"sì,no"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add(f"F2:F{last}")
    for col, w in zip("ABCDEFG", [8, 13, 70, 10, 13, 7, 40]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"

    # --- stats
    st = wb.create_sheet("stats")
    st.append(["LEVEL", "PAPER_100", "TARGET_NUOVE", "TENUTE", "MANCANO", "LEN_MEDIA_TENUTE", "LEN_MEDIA_PAPER"])
    for c in st[1]:
        c.font, c.fill = bold, head
    paper_len = paper.assign(L=paper["QUESTION"].astype(str).str.len()).groupby("LEVEL")["L"].mean().to_dict()
    for r, lv in enumerate(LEVELS, start=2):
        rng_lv, rng_keep, rng_len = f"candidates!B2:B{last}", f"candidates!F2:F{last}", f"candidates!D2:D{last}"
        st.append([
            lv, n_paper.get(lv, 0), target_total - n_paper.get(lv, 0),
            f'=COUNTIFS({rng_lv},"{lv}",{rng_keep},"sì")',
            f"=C{r}-D{r}",
            f'=IFERROR(AVERAGEIFS({rng_len},{rng_lv},"{lv}",{rng_keep},"sì"),"")',
            round(paper_len.get(lv, 0), 1),
        ])
    st.append(["TOTALE", "=SUM(B2:B4)", "=SUM(C2:C4)", "=SUM(D2:D4)", "=SUM(E2:E4)", "", ""])
    for col in "ABCDEFG":
        st.column_dimensions[col].width = 18

    # --- paper_100
    pp = wb.create_sheet("paper_100")
    pp.append(["ID", "LEVEL", "QUESTION", "LEN_CHAR"])
    for c in pp[1]:
        c.font, c.fill = bold, head
    for i, r in enumerate(paper.itertuples(index=False), start=2):
        pp.append([r.ID, r.LEVEL, r.QUESTION, f"=LEN(C{i})"])
    pp.column_dimensions["C"].width = 70

    OUT.parent.mkdir(exist_ok=True)
    wb.save(OUT)
    print(f"Creato: {OUT}  ({len(cand)} candidate)")
    print("Target nuove per livello:", {lv: target_total - n_paper.get(lv, 0) for lv in LEVELS})


if __name__ == "__main__":
    main()
