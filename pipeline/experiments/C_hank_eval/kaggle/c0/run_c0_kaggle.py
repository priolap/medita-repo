# -*- coding: utf-8 -*-
"""
Kernel Kaggle per c0 (verifica di riproducibilita' del retrieval).

Gira nello stesso ambiente del paper: chromadb 0.5.5 su Kaggle.
  1. trova in /kaggle/input la collezione (espritz/medita-news-chunk512-over64-2) e gli
     input del task C (espritz/hank-c-inputs: config_c.json, c0_check_repro.py,
     results_pro_gemma2.json, qa_list_setup_final.xlsx);
  2. copia la collezione in /kaggle/working (chroma richiede scrittura, come nel notebook v10);
  3. scrive un config_c.json con i percorsi Kaggle e lancia c0_check_repro.py --dup;
  4. cancella la copia della collezione, cosi' l'output del kernel contiene solo gli Excel.

Output: /kaggle/working/C_hank_eval/out/c0_repro_check.xlsx, c0_collection_dups.xlsx, c0_log.txt
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

    shutil.copy2(inputs / "c0_check_repro.py", run / "c0_check_repro.py")
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
        print("[DRY] config scritto:", run / "config_c.json")
        return

    try:
        if not coll_work.exists():
            print("copia della collezione in", coll_work)
            shutil.copytree(coll_in, coll_work)
        pip("chromadb==0.5.5")
        log = open(out / "c0_log.txt", "w", encoding="utf-8")
        cmd = [sys.executable, "c0_check_repro.py", "--dup"]
        rc = subprocess.run(cmd, cwd=run, stdout=log, stderr=subprocess.STDOUT).returncode
        if rc != 0:
            # chromadb 0.5.5 puo' non funzionare con numpy 2: nuovo tentativo con numpy<2
            log.write("\n[retry con numpy<2]\n"); log.flush()
            pip("numpy<2")
            rc = subprocess.run(cmd, cwd=run, stdout=log, stderr=subprocess.STDOUT).returncode
        log.close()
        print(open(out / "c0_log.txt", encoding="utf-8").read())
        print("returncode:", rc)
    finally:
        shutil.rmtree(WORK / "coll", ignore_errors=True)


if __name__ == "__main__":
    main()
