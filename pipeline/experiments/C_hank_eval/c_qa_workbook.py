# -*- coding: utf-8 -*-
"""
Unico file di lavoro del task C, nel formato del foglio questions_2 di qa_rag_models_comparison_v2.xlsx:

  Question | Context | ID | LEVEL | HUMAN | gemma2 | llama3 | IS_HALL_gemma2 | IS_HALL_llama3 | NOTE

  - Question, Context, ID, LEVEL : dal retrieval di c2 (Context = i 4 chunk che riceve il modello)
  - HUMAN   : gold. Q001-Q100 dal paper; Q101-Q300 la scrivi tu usando solo il contesto
              (contesto insufficiente -> testo di astensione, come nel paper)
  - gemma2, llama3 : risposte di c3 (si riempiono quando l'output del kernel e' scaricato)
  - IS_HALL_<modello> : 0/1, la annoti tu dopo c3, come nel paper
  - NOTE    : libera

Si puo' rilanciare quando vuoi: conserva quello che hai scritto (HUMAN di Q101-Q300, IS_HALL_*, NOTE),
aggiorna le risposte dei modelli dai file di c3 e prima salva il file precedente in .bak.

Input : out/kaggle_c2/C_hank_eval/out/c2_contexts.json
        out/kaggle_c3/**/answers_<modello>.json (se presenti)
Output: annotation/qa_rag_models_comparison_v3.xlsx (foglio questions)

Uso:  python c_qa_workbook.py
"""
import json
import re
import shutil
import sys
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

HERE = Path(__file__).resolve().parent
CFG = json.load(open(HERE / "config_c.json", encoding="utf-8"))
CTX = HERE / "out" / "kaggle_c2" / "C_hank_eval" / "out" / "c2_contexts.json"
C3_DIR = HERE / "out" / "kaggle_c3"
OUT_X = HERE / "annotation" / "qa_rag_models_comparison_v3.xlsx"
SHEET = "questions"
MODELS = list(CFG["generators"].keys())
KEEP_COLS = ["HUMAN"] + [f"IS_HALL_{m}" for m in MODELS] + ["NOTE"]


def blank(v):
    return v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == ""


def load_answers(model):
    hits = sorted(C3_DIR.rglob(f"answers_{model}.json")) if C3_DIR.exists() else []
    if not hits:
        return {}
    if len(hits) > 1:
        sys.exit(f"[STOP] piu' file answers_{model}.json in {C3_DIR}: {hits}")
    # stessa pulizia finale del paper (merge_QA_models.py)
    return {a["ID"]: re.sub(r"\[\/INST|\[\/", "", a["ANSWER"]).strip()
            for a in json.load(open(hits[0], encoding="utf-8"))}


def main():
    if not CTX.exists():
        sys.exit(f"[STOP] manca {CTX}: scarica prima l'output del kernel c2")
    recs = json.load(open(CTX, encoding="utf-8"))
    if len(recs) != 300:
        sys.exit(f"[STOP] attese 300 domande, trovate {len(recs)}")

    df = pd.DataFrame({
        "Question": [r["QUESTION"] for r in recs],
        "Context": [r["CONTEXT"] for r in recs],
        "ID": [r["ID"] for r in recs],
        "LEVEL": [r["LEVEL"] for r in recs],
        "HUMAN": [r["GOLD_PAPER"] if r["SOURCE"] == "paper" else "" for r in recs],
    })
    for m in MODELS:
        ans = load_answers(m)
        df[m] = df["ID"].map(ans).fillna("")
        print(f"{m}: {len(ans)} risposte da c3")
    for m in MODELS:
        df[f"IS_HALL_{m}"] = ""
    df["NOTE"] = ""
    df = df.astype(object)

    if OUT_X.exists():
        old = pd.read_excel(OUT_X, sheet_name=SHEET, dtype=object).set_index("ID")
        shutil.copy2(OUT_X, OUT_X.with_name(OUT_X.name + ".bak"))
        is_new = df["ID"].str[1:].astype(int) > 100
        for col in KEEP_COLS:
            if col not in old.columns:
                continue
            prev = df["ID"].map(old[col])
            mask = prev.map(lambda v: not blank(v))
            if col == "HUMAN":
                mask &= is_new  # le gold del paper vengono sempre dal paper
            df.loc[mask, col] = prev[mask]
        print(f"Conservate le annotazioni da {OUT_X.name} (backup .bak)")

    OUT_X.parent.mkdir(exist_ok=True)
    with pd.ExcelWriter(OUT_X, engine="openpyxl") as w:
        df.to_excel(w, sheet_name=SHEET, index=False)

    wb = load_workbook(OUT_X)
    ws = wb[SHEET]
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="DDDDDD")
    widths = {"Question": 35, "Context": 80, "ID": 7, "LEVEL": 7, "HUMAN": 50, "NOTE": 30}
    for idx, name in enumerate(df.columns, start=1):
        letter = ws.cell(1, idx).column_letter
        ws.column_dimensions[letter].width = widths.get(name, 50 if name in MODELS else 12)
        if name.startswith("IS_HALL_"):
            dv = DataValidation(type="list", formula1='"0,1"', allow_blank=True)
            ws.add_data_validation(dv)
            dv.add(f"{letter}2:{letter}{len(df) + 1}")
    for row in ws.iter_rows(min_row=2, max_row=len(df) + 1):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "C2"
    wb.save(OUT_X)

    new = df[df["ID"].str[1:].astype(int) > 100]
    print(f"Creato: {OUT_X}")
    print(f"HUMAN da scrivere (Q101-Q300): {int(new['HUMAN'].map(blank).sum())} su {len(new)}")
    for m in MODELS:
        print(f"IS_HALL_{m} da annotare: {int(df[f'IS_HALL_{m}'].map(blank).sum())} su {len(df)}")


if __name__ == "__main__":
    main()
