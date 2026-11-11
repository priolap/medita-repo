# -*- coding: utf-8 -*-
"""
Kernel Kaggle per c4: metriche C11 (EM, ROUGE, BLEU, METEOR, NMISS, BERTScore) e astensione C12.
  1. trova in /kaggle/input c4_metrics.py, config_c.json, il file di lavoro e il pacchetto nmiss;
  2. installa bert-score e scarica i dati NLTK (punkt, punkt_tab, wordnet, omw-1.4);
  3. lancia c4_metrics.py --bertscore.
Output: /kaggle/working/out/c4_metrics.xlsx, c4_log.txt
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

IN = Path(os.environ.get("C_KAGGLE_INPUT", "/kaggle/input"))
WORK = Path(os.environ.get("C_KAGGLE_WORK", "/kaggle/working"))
DRY = os.environ.get("C_DRY") == "1"


def find_one(name):
    hits = sorted(IN.rglob(name))
    if len(hits) != 1:
        sys.exit(f"[STOP] {name}: trovati {len(hits)} file in {IN}: {hits}")
    return hits[0]


def main():
    script = find_one("c4_metrics.py")
    wb = find_one("qa_rag_models_comparison_v3.xlsx")
    nmiss = find_one("scorer.py").parent.parent
    run = WORK / "run"
    out = WORK / "out"
    run.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(script, run / "c4_metrics.py")
    shutil.copy2(script.parent / "config_c.json", run / "config_c.json")
    cmd = [sys.executable, "c4_metrics.py", "--workbook", str(wb), "--nmiss", str(nmiss),
           "--out", str(out / "c4_metrics.xlsx")]
    if not DRY:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "bert-score", "nltk"], check=True)
        import nltk
        for p in ["punkt", "punkt_tab", "wordnet", "omw-1.4"]:
            nltk.download(p, quiet=True)
        cmd.append("--bertscore")
    with open(out / "c4_log.txt", "w", encoding="utf-8") as log:
        rc = subprocess.run(cmd, cwd=run, stdout=log, stderr=subprocess.STDOUT).returncode
    print(open(out / "c4_log.txt", encoding="utf-8").read())
    print("returncode:", rc)


if __name__ == "__main__":
    main()
