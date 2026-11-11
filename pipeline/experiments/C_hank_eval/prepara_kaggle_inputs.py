# -*- coding: utf-8 -*-
"""
Prepara kaggle/inputs/ per il dataset Kaggle espritz/hank-c-inputs (task C).
Copia (senza modificarli) config_c.json, c0_check_repro.py, l'output del paper
results_pro_gemma2.json e qa_list_setup_final.xlsx, e scrive dataset-metadata.json.

Uso:  python prepara_kaggle_inputs.py
"""
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CFG = json.load(open(HERE / "config_c.json", encoding="utf-8"))
DEST = HERE / "kaggle" / "inputs"


def resolve(p):
    return Path(p.replace("{rag_root}", CFG["rag_root"]))


def main():
    files = [
        HERE / "config_c.json",
        HERE / "c0_check_repro.py",
        resolve(CFG["paper_results_dir"]) / CFG["paper_reference_json"],
        resolve(CFG["qa_list"]),
    ]
    for f in files:
        if not f.exists():
            sys.exit(f"[STOP] manca {f}")
    DEST.mkdir(parents=True, exist_ok=True)
    for f in files:
        shutil.copy2(f, DEST / f.name)
        print("copiato:", f.name)
    meta = {"title": "hank-c-inputs", "id": "espritz/hank-c-inputs",
            "licenses": [{"name": "CC0-1.0"}]}
    json.dump(meta, open(DEST / "dataset-metadata.json", "w", encoding="utf-8"), indent=2)
    print("Pronto:", DEST)


if __name__ == "__main__":
    main()
