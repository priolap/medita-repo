# -*- coding: utf-8 -*-
"""Regenerate all experimental tables and figures of the paper.

  python paper/make_all.py               # figures and tables from results/ (minutes, no data needed)
  python paper/make_all.py --from-data   # first recompute results/ from the MEDITA data snapshot
                                         # (set MEDITA_HOME; reads ~8 GB of tables)
  python paper/make_all.py --list        # show the steps and stop
  python paper/make_all.py --from-experiments [--experiments-src DIR]
                                         # first re-export results/experiments/ from the outputs of
                                         # pipeline/experiments/ (after re-running an experiment)

Every step is a script in paper/scripts/; each one documents its inputs and outputs.
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent / "scripts"
# REPO_EXP_261111: fixed creation date in the PDF files, so that the same results give byte-identical figures
ENV = dict({"SOURCE_DATE_EPOCH": "1794355200"}, **os.environ)

# (name, script, kind)  kind: "data" = needs the MEDITA snapshot, "build" = only needs results/,
# "export" = copies the outputs of the experiments to results/experiments/ (tools/export_results.py).
# REPO_NEWS_261111: Figure 2.3 is built from the aggregated counts in results/news/.
# REPO_EXP_261111: experiments A-D; every build_*.py checks its values against the paper.
STEPS = [
    ("Corpus statistics by domain and year", "data_topic_stats.py", "data"),
    ("Export of the experiment results",      "../../tools/export_results.py", "export"),
    ("Figure 2.2 and Table 2.4",              "fig_data_topics.py",  "build"),
    ("Figure 2.3",                            "fig_news_topics.py",  "build"),
    ("A storage and lakehouse: tables and figure", "build_A_storage.py",   "build"),
    ("B Transform: tables and figures",            "build_B_transform.py", "build"),
    ("C HANK: tables and figure",                  "build_C_hank.py",      "build"),
    ("D use case and missingness: tables and figures", "build_D_usecase.py", "build"),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-data", action="store_true", help="recompute results/ from the data snapshot")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--from-experiments", action="store_true",  # REPO_EXP_261111
                    help="re-export results/experiments/ from the experiment outputs first")
    ap.add_argument("--experiments-src", default=None, help="experiments folder (default: pipeline/experiments)")
    a = ap.parse_args()

    selected = [s for s in STEPS if s[2] == "build"
                or (s[2] == "data" and a.from_data)
                or (s[2] == "export" and (a.from_experiments or a.experiments_src))]
    for name, script, kind in STEPS:
        mark = "x" if (name, script, kind) in selected else " "
        print(f"[{mark}] {kind:7s} {script.split('/')[-1]:24s} {name}")
    if a.list:
        return
    for name, script, _ in selected:
        print(f"\n=== {name} ({script})", flush=True)
        t0 = time.time()
        extra = ["--src", a.experiments_src] if script.endswith("export_results.py") and a.experiments_src else []
        r = subprocess.run([sys.executable, str((SCRIPTS / script).resolve())] + extra, cwd=SCRIPTS,
                           env=ENV)  # REPO_EXP_261111
        if r.returncode:
            sys.exit(f"Step failed: {script}")
        print(f"--- done in {time.time() - t0:.1f} s")
    print("\nAll steps completed.")


if __name__ == "__main__":
    main()
