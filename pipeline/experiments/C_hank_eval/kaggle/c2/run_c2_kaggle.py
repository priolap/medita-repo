# -*- coding: utf-8 -*-
"""
Kernel Kaggle per c2 (retrieval sulle 300 domande), stesso ambiente di c0: chromadb 0.5.5.
  1. trova in /kaggle/input la collezione e gli input del task C (espritz/hank-c-inputs);
  2. copia la collezione in /kaggle/working (chroma richiede scrittura);
  3. scrive config_c.json con i percorsi Kaggle e lancia c2_retrieve.py;
  4. cancella la copia della collezione, cosi' l'output contiene solo i risultati.

Output: /kaggle/working/C_hank_eval/out/c2_contexts.json, c2_contexts.xlsx, c2_log.txt
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

IN = Path(os.environ.get("C_KAGGLE_INPUT", "/kaggle/input"))
WORK = Path(os.environ.get("C_KAGGLE_WORK", "/kaggle/working"))
DRY = os.environ.get("C_DRY") == "1"
FILES = ["c0_check_repro.py", "c2_retrieve.py", "benchmark_300.json"]


def find_one(name):
    hits = sorted(IN.rglob(name))
    if len(hits) != 1:
        sys.exit(f"[STOP] {name}: trovati {len(hits)} file in {IN}: {hits}")
    return hits[0]


def pip(*pkgs):
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", *pkgs], check=True)


def main():
    coll_in = find_one("chroma.sqlite3").parent
    inputs = find_one("config_c.json").parent
    run = WORK / "C_hank_eval"
    out = run / "out"
    out.mkdir(parents=True, exist_ok=True)
    coll_work = WORK / "coll" / coll_in.name

    for f in FILES:
        shutil.copy2(inputs / f, run / f)
    cfg = json.load(open(inputs / "config_c.json", encoding="utf-8"))
    cfg.update({
        "rag_root": str(inputs),
        "collection_dir": str(coll_in),
        "collection_dir_work": str(coll_work),
        "paper_results_dir": str(inputs),
        "qa_list": str(inputs / "qa_list_setup_final.xlsx"),
    })
    json.dump(cfg, open(run / "config_c.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("collezione:", coll_in, "\ninput:", inputs)
    if DRY:
        print("[DRY] pronto in", run)
        return

    try:
        if not coll_work.exists():
            print("copia della collezione in", coll_work)
            shutil.copytree(coll_in, coll_work)
        pip("chromadb==0.5.5")
        log = open(out / "c2_log.txt", "w", encoding="utf-8")
        cmd = [sys.executable, "c2_retrieve.py"]
        rc = subprocess.run(cmd, cwd=run, stdout=log, stderr=subprocess.STDOUT).returncode
        if rc != 0:
            log.write("\n[retry con numpy<2]\n"); log.flush()
            pip("numpy<2")
            rc = subprocess.run(cmd, cwd=run, stdout=log, stderr=subprocess.STDOUT).returncode
        log.close()
        print(open(out / "c2_log.txt", encoding="utf-8").read())
        print("returncode:", rc)
    finally:
        shutil.rmtree(WORK / "coll", ignore_errors=True)


if __name__ == "__main__":
    main()
