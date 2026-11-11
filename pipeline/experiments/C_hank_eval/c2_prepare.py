# -*- coding: utf-8 -*-
"""
C2a - Costruisce il benchmark da 300 domande e prepara gli input Kaggle per il retrieval.

Benchmark: Q001-Q100 = le 100 domande del paper (qa_list_setup_final.xlsx, con la loro gold);
           Q101-Q300 = le 200 nuove selezionate in annotation/c1_selezione.xlsx (KEEP = "si'"),
           ordinate per livello (LOW, MID, HIGH) e poi per C_ID; si tiene C_ID per tracciabilita'.

Input : qa_list_setup_final.xlsx, annotation/c1_selezione.xlsx, out/c1_judge.xlsx
Output: annotation/benchmark_300.xlsx       (per leggerlo)
        kaggle/inputs/benchmark_300.json     (per il kernel)
        kaggle/inputs/ aggiornata con c2_retrieve.py, c0_check_repro.py, config_c.json

Uso:  python c2_prepare.py
"""
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
CFG = json.load(open(HERE / "config_c.json", encoding="utf-8"))
LEVELS = ["LOW", "MID", "HIGH"]
KIN = HERE / "kaggle" / "inputs"


def resolve(p):
    return Path(p.replace("{rag_root}", CFG["rag_root"]))


def main():
    paper = pd.read_excel(resolve(CFG["qa_list"]), sheet_name="questions", header=1)
    paper = pd.DataFrame({
        "ID": paper["ID"], "C_ID": "", "SOURCE": "paper", "LEVEL": paper["LEVEL"],
        "QUESTION": paper["QUESTION"].astype(str).str.strip(),
        "GOLD_PAPER": paper["REFERENCE ANSWER"].astype(str).str.strip(),
        "LLM_JUDGE": "",
    })
    sel = pd.read_excel(HERE / "annotation" / "c1_selezione.xlsx", sheet_name="selected")
    sel = sel[sel["KEEP"].astype(str).str.strip().str.lower() != "no"].copy()
    counts = sel["LEVEL_DESIGN"].value_counts().to_dict()
    need = {lv: 100 - int((paper["LEVEL"] == lv).sum()) for lv in LEVELS}
    if counts != need:
        sys.exit(f"[STOP] selezione {counts} diversa dal target {need}: completa c1_select.py --apply")
    sel["LVL_ORD"] = sel["LEVEL_DESIGN"].map({lv: i for i, lv in enumerate(LEVELS)})
    sel = sel.sort_values(["LVL_ORD", "C_ID"]).reset_index(drop=True)
    new = pd.DataFrame({
        "ID": [f"Q{101 + i:03d}" for i in range(len(sel))], "C_ID": sel["C_ID"], "SOURCE": "new",
        "LEVEL": sel["LEVEL_DESIGN"], "QUESTION": sel["QUESTION"].astype(str).str.strip(),
        "GOLD_PAPER": "", "LLM_JUDGE": sel["LLM"],
    })
    bench = pd.concat([paper, new], ignore_index=True)
    if bench["QUESTION"].duplicated().any():
        sys.exit("[STOP] domande duplicate nel benchmark")
    bench["LEN_CHAR"] = bench["QUESTION"].str.len()

    (HERE / "annotation").mkdir(exist_ok=True)
    with pd.ExcelWriter(HERE / "annotation" / "benchmark_300.xlsx", engine="openpyxl") as w:
        bench.to_excel(w, sheet_name="benchmark", index=False)
        bench.groupby(["SOURCE", "LEVEL"]).agg(N=("ID", "count"), LEN_MEDIA=("LEN_CHAR", "mean")).round(1) \
             .reset_index().to_excel(w, sheet_name="stats", index=False)

    KIN.mkdir(parents=True, exist_ok=True)
    json.dump(bench.to_dict(orient="records"), open(KIN / "benchmark_300.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    for f in ["c2_retrieve.py", "c0_check_repro.py", "config_c.json"]:
        shutil.copy2(HERE / f, KIN / f)
    print(bench.groupby(["SOURCE", "LEVEL"]).size().to_string())
    print("Creato: annotation/benchmark_300.xlsx e kaggle/inputs/benchmark_300.json")


if __name__ == "__main__":
    main()
