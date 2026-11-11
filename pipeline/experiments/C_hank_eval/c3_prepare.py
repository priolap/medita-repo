# -*- coding: utf-8 -*-
"""
C3a - Aggiunge agli input Kaggle i contesti di c2 per la generazione (c3).
Copia (senza modificarli) out/kaggle_c2/C_hank_eval/out/c2_contexts.json e config_c.json
in kaggle/inputs/. Poi: kaggle datasets version + kaggle kernels push -p kaggle\\c3.

Uso:  python c3_prepare.py
"""
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "out" / "kaggle_c2" / "C_hank_eval" / "out" / "c2_contexts.json"
KIN = HERE / "kaggle" / "inputs"


def main():
    if not SRC.exists():
        sys.exit(f"[STOP] manca {SRC}: scarica prima l'output del kernel c2")
    recs = json.load(open(SRC, encoding="utf-8"))
    if len(recs) != 300:
        sys.exit(f"[STOP] attese 300 domande, trovate {len(recs)}")
    KIN.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC, KIN / "c2_contexts.json")
    shutil.copy2(HERE / "config_c.json", KIN / "config_c.json")
    print("Copiati in kaggle/inputs: c2_contexts.json, config_c.json")


if __name__ == "__main__":
    main()
