# -*- coding: utf-8 -*-
"""Export the outputs of the experiments to small CSV files in results/experiments/.

The experiments (pipeline/experiments/<EXP>/) write Excel workbooks in their own out/ folders,
which are not committed. This script copies the sheets that the paper uses into
results/experiments/<EXP>/<workbook>__<sheet>.csv (UTF-8, comma-separated), so that
paper/make_all.py can rebuild every table and figure without the data.

  python tools/export_results.py                     # from pipeline/experiments/ (after a re-run)
  python tools/export_results.py --src <folder>      # from another experiments/ folder
  python tools/export_results.py --check             # only list what would be exported
  python tools/export_results.py --strict            # fail if an expected output is missing
After re-running a single experiment, only its results are replaced; the others are kept.

For workbooks with a timestamp in the name (e.g. b6_baseline_<date_time>.xlsx) the most recent
one is used. Absolute paths of the machine that ran the experiment are replaced by <MEDITA> or
<WORK>; the health-news corpus is never exported (only per-question scores of HANK, no text).
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
DEFAULT_SRC = REPO / "pipeline" / "experiments"
DST = REPO / "results" / "experiments"

# (experiment, workbook pattern inside the experiment folder, sheets or None = all sheets)
WORKBOOKS = [
    ("A_lake", "out/misura_lake_*.xlsx", ["sintesi", "tempi", "footprint_zone", "macchina"]),
    ("B_fuzzy_eval", "out/fuzzy_annotato_2026.xlsx", ["Annotazione", "escluse", "riepilogo"]),
    ("B_fuzzy_eval", "out/b4_risultati.xlsx", None),
    ("B_baseline", "out/b6_baseline_*.xlsx", ["coppie", "metriche", "valentine", "controllo_b2",
                                             "copertura_wordnet", "ambiente"]),
    ("B_ablation", "out/b3_sintesi_ablation.xlsx", ["README", "sintesi", "var_code_con_effetto", "errori",
                                                   "controllo_full", "file_usati"]),
    ("B_superkey", "out/superkey_tests_*.xlsx", None),
    ("B_superkey", "out/verifica_ith0_*.xlsx", None),
    ("B_scalabilita", "out/b5_scalabilita_*.xlsx", ["README", "ambiente", "volumi", "sintesi", "pulizia"]),
    # HANK: scores only. The questions, contexts and answers come from the copyrighted news corpus.
    ("C_hank_eval", "out/kaggle_c4/out/c4_metrics.xlsx", ["README", "classic", "nmiss", "hallucinations",
                                                        "abstention_C12", "confusion_C12", "per_answer", "env"]),
    ("D_case_study", "out/d14_integrazione_*.xlsx", None),
    ("D_case_study", "out/d15_missingness_*.xlsx", None),
]
# plain files already in CSV/JSON (A_storage_benchmark writes its results/ folder directly)
PLAIN = [
    ("A_storage_benchmark", "results", ["summary_engines.csv", "repro_summary.csv", "repro_stability.csv",
                                        "repro_lakehouse.csv", "repro_runs_used.txt", "p2_checklist.csv",
                                        "summary_queries.csv", "summary_queries_by_table.csv", "footprint.csv",
                                        "ingestion.csv", "queries.csv", "tables.csv", "lakehouse_ops.csv",
                                        "engine_notes.csv", "env.json", "params.json"]),
]
PLAIN_RUNS = ("A_storage_benchmark", "results/runs", "summary_queries.csv")  # one file per run
FORBIDDEN_COLUMNS = {"HUMAN", "SYSTEM", "Question", "Context", "TEXT", "CONTEXT", "QUESTION", "ANSWER"}


def sanitizer(src):
    """Replace the absolute paths of the machine that produced the outputs."""
    home = src.resolve().parent  # .../MEDITA (src = .../MEDITA/experiments)
    variants = {str(home), str(home).replace("\\", "/"), str(home).replace("/", "\\")}
    variants |= {v for v in list(variants) if v}
    work = re.compile(r"[A-Za-z]:[\\/]MEDITA_[A-Za-z0-9_]+")
    medita_win = re.compile(r"[A-Za-z]:[\\/][^|;\"\n]*?[\\/]MEDITA(?=[\\/]|$|\")")

    def clean(text):
        if not isinstance(text, str):
            return text
        for v in sorted(variants, key=len, reverse=True):
            text = text.replace(v, "<MEDITA>")
        text = work.sub("<WORK>", text)
        return medita_win.sub("<MEDITA>", text)
    return clean


def latest(folder, pattern):
    files = sorted(p for p in folder.glob(pattern) if not p.name.startswith("~$"))
    return files[-1] if files else None


def export(src, check=False):
    clean = sanitizer(src)
    rows, missing = [], []
    for exp, pattern, sheets in WORKBOOKS:
        wb = latest(src / exp, pattern)
        if wb is None:
            missing.append(f"{exp}/{pattern}")
            continue
        book = pd.read_excel(wb, sheet_name=None)
        names = list(book) if sheets is None else sheets
        for sh in names:
            if sh not in book:
                missing.append(f"{exp}/{wb.name}#{sh}")
                continue
            df = book[sh]
            bad = FORBIDDEN_COLUMNS & set(map(str, df.columns))
            if bad:
                sys.exit(f"STOP: {wb.name}#{sh} contains text columns {sorted(bad)}: not exported.")
            df = df.map(clean)
            stem = re.sub(r"_\d{8}_\d{6}$", "", wb.stem)
            out = DST / exp / f"{stem}__{sh}.csv"
            rows.append((exp, f"{wb.name}#{sh}", out.relative_to(REPO).as_posix(), len(df)))
            if not check:
                out.parent.mkdir(parents=True, exist_ok=True)
                df.to_csv(out, index=False, encoding="utf-8", lineterminator="\n")
    for exp, sub, names in PLAIN:
        for n in names:
            p = src / exp / sub / n
            if not p.exists():
                missing.append(f"{exp}/{sub}/{n}")
                continue
            out = DST / exp / n
            rows.append((exp, f"{sub}/{n}", out.relative_to(REPO).as_posix(), None))
            if not check:
                out.parent.mkdir(parents=True, exist_ok=True)
                text = p.read_text(encoding="utf-8")
                if p.suffix == ".json":  # paths inside JSON strings are escaped
                    data = json.loads(text)
                    text = json.dumps(json.loads(json.dumps(data), object_hook=lambda d: {
                        k: clean(v) for k, v in d.items()}), indent=2, ensure_ascii=False) + "\n"
                else:
                    text = clean(text)
                out.write_text(text, encoding="utf-8", newline="\n")
    exp, sub, name = PLAIN_RUNS
    for run in sorted((src / exp / sub).glob("run_*"), key=lambda p: int(p.name.split("_")[1])):
        p = run / name
        if p.exists():
            out = DST / exp / "runs" / f"{run.name}__{name}"
            rows.append((exp, f"{sub}/{run.name}/{name}", out.relative_to(REPO).as_posix(), None))
            if not check:
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, out)
    return rows, missing


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", default=str(DEFAULT_SRC), help="experiments folder (default: pipeline/experiments)")
    ap.add_argument("--check", action="store_true", help="list only, write nothing")
    ap.add_argument("--strict", action="store_true", help="fail if an expected output is missing")
    a = ap.parse_args()
    src = Path(a.src)
    if not src.is_dir():
        sys.exit(f"{src} not found")
    rows, missing = export(src, a.check)
    for exp, what, out, n in rows:
        print(f"{exp:20s} {what:55s} -> {out}" + (f"  ({n} rows)" if n is not None else ""))
    print(f"\n{len(rows)} files {'to export' if a.check else 'exported'} to {DST.relative_to(REPO).as_posix()}/")
    if missing:
        print("Not found, the results already in results/experiments/ are kept:\n  " + "\n  ".join(missing))
        if a.strict:
            sys.exit(1)


if __name__ == "__main__":
    main()
