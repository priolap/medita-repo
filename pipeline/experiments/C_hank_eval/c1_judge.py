# -*- coding: utf-8 -*-
"""
C1b - Verifica del livello di difficolta' con LLM-as-a-judge (task C9), come nel DKE.

Riusa da RAG/scripts/llm_judge_agreement.py, importandoli senza copiarli:
  build_messages (prompt verbatim della Tabella A.9), parse_label, compute_agreement,
  MODEL ("gpt-4") e TEMPERATURE (0).
La chiamata all'API usa gli stessi parametri dello script originale (max_tokens=5) e in piu'
registra il modello che ha risposto davvero.

Input : annotation/c1_candidati.xlsx (foglio candidates; si valutano le righe con KEEP diverso da "no")
        chiave nella variabile d'ambiente OPENAI_API_KEY
Output: out/c1_judge.xlsx  (labels, agreement_per_category, summary, confusion_matrix)

Uso:  python c1_judge.py [--model NOME]   (--model solo se gpt-4 non fosse piu' disponibile)
"""
import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
CFG = json.load(open(HERE / "config_c.json", encoding="utf-8"))
IN_X = HERE / "annotation" / "c1_candidati.xlsx"
OUT_X = HERE / "out" / "c1_judge.xlsx"


def load_judge_module():
    path = Path(CFG["rag_root"]) / "scripts" / "llm_judge_agreement.py"
    if not path.exists():
        sys.exit(f"[STOP] non trovo {path}")
    spec = importlib.util.spec_from_file_location("llm_judge_agreement", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, path


def load_candidates():
    if not IN_X.exists():
        sys.exit(f"[STOP] manca {IN_X}: lancia prima c1_make_workbook.py")
    df = pd.read_excel(IN_X, sheet_name="candidates")
    keep = df["KEEP"].astype(str).str.strip().str.lower() != "no"
    df = df[keep].copy()
    df["QUESTION"] = df["QUESTION"].astype(str).str.strip()
    df["LEN_CHAR"] = df["QUESTION"].str.len()  # ricalcolata qui: le formule Excel non vengono lette
    df["HUMAN"] = df["LEVEL_DESIGN"].astype(str).str.strip().str.upper()
    return df.reset_index(drop=True)


def classify(df, mod, model):
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    labels, used = [], []
    for i, row in df.iterrows():
        for attempt in range(4):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    temperature=mod.TEMPERATURE,
                    max_tokens=5,
                    messages=mod.build_messages(row["QUESTION"]),
                )
                labels.append(mod.parse_label(resp.choices[0].message.content))
                used.append(resp.model)
                break
            except Exception as e:
                if attempt == 3:
                    print(f"  ! errore definitivo su {row['C_ID']}: {e}")
                    labels.append("UNKNOWN")
                    used.append("")
                else:
                    time.sleep(2 * (attempt + 1))
        if (i + 1) % 20 == 0:
            print(f"  ...{i + 1}/{len(df)}")
    out = df.copy()
    out["LLM"] = labels
    out["MODEL_USED"] = used
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None)
    args = ap.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("[STOP] variabile d'ambiente OPENAI_API_KEY non impostata (setx OPENAI_API_KEY ... e nuova finestra cmd)")

    mod, path = load_judge_module()
    model = args.model or mod.MODEL
    df = load_candidates()
    print(f"Domande da valutare: {len(df)}  | modello richiesto: {model}  | prompt da {path.name}")

    df = classify(df, mod, model)
    per_cat, summary, conf = mod.compute_agreement(df)
    extra = pd.DataFrame({
        "metric": ["model_requested", "model_used", "temperature", "n_questions", "run_at", "prompt_source"],
        "value": [model, ", ".join(sorted(set(m for m in df["MODEL_USED"] if m))), mod.TEMPERATURE,
                  len(df), time.strftime("%Y-%m-%d %H:%M:%S"), str(path)],
    })
    summary = pd.concat([summary, extra], ignore_index=True)

    OUT_X.parent.mkdir(exist_ok=True)
    cols = ["C_ID", "LEVEL_DESIGN", "LLM", "QUESTION", "LEN_CHAR", "MODEL_USED"]
    with pd.ExcelWriter(OUT_X, engine="openpyxl") as w:
        df[cols].to_excel(w, sheet_name="labels", index=False)
        per_cat.to_excel(w, sheet_name="agreement_per_category", index=False)
        summary.to_excel(w, sheet_name="summary", index=False)
        conf.to_excel(w, sheet_name="confusion_matrix")
    print(per_cat.to_string(index=False))
    print(summary.to_string(index=False))
    print(conf.to_string())
    print(f"Creato: {OUT_X}")


if __name__ == "__main__":
    main()
