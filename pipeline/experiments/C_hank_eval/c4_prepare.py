# -*- coding: utf-8 -*-
"""
C4a - Prepara gli input Kaggle per c4 (metriche con BERTScore).
Copia (senza modificarli) in kaggle/inputs/: c4_metrics.py, config_c.json, il file di lavoro
annotation/qa_rag_models_comparison_v3.xlsx e il pacchetto RAG/github/nmiss (solo modules/,
utils/ e __init__.py) nella sottocartella kaggle/inputs/nmiss/.
Poi: kaggle datasets version -p kaggle\\inputs -m "c4" --dir-mode tar

Uso:  python c4_prepare.py
"""
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CFG = json.load(open(HERE / "config_c.json", encoding="utf-8"))
KIN = HERE / "kaggle" / "inputs"
NMISS = Path(CFG["rag_root"]) / "github" / "nmiss"


def main():
    wb = HERE / "annotation" / "qa_rag_models_comparison_v3.xlsx"
    for f in [wb, HERE / "c4_metrics.py", NMISS / "modules" / "scorer.py"]:
        if not f.exists():
            sys.exit(f"[STOP] manca {f}")
    KIN.mkdir(parents=True, exist_ok=True)
    for f in [wb, HERE / "c4_metrics.py", HERE / "config_c.json"]:
        shutil.copy2(f, KIN / f.name)
    dst = KIN / "nmiss"
    dst.mkdir(exist_ok=True)
    shutil.copy2(NMISS / "__init__.py", dst / "__init__.py")
    for sub in ["modules", "utils"]:
        shutil.copytree(NMISS / sub, dst / sub, ignore=shutil.ignore_patterns("__pycache__"),
                        dirs_exist_ok=True)
    if not (dst / "modules" / "scorer.py").exists():
        sys.exit(f"[STOP] copia di nmiss non riuscita: manca {dst / 'modules' / 'scorer.py'}")
    print("Pronti in kaggle/inputs: c4_metrics.py, config_c.json,", wb.name, "e nmiss/")


if __name__ == "__main__":
    main()
