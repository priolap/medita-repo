#!/usr/bin/env python3
"""
run_repro.py - riproducibilita' del benchmark A1: piu' run delle query, tutto in automatico.

Non ricarica nulla: usa i DB gia' presenti in WORK_DIR (D:\\MEDITA_bench_work).
Per ogni run:
  1. python bench_storage.py --queries   (SQLite senza indici -> DuckDB -> Parquet -> Delta -> indici -> SQLite+idx)
  2. python make_report.py
  3. copia i risultati in results/runs/run_<k>/   (niente piu' sovrascritture)
Alla fine confronta i run:
  results/repro_summary.csv      mediana di ogni run, mediana tra i run, min, max, max/min per query x engine
  results/repro_stability.csv    scostamento massimo tra run per engine
  results/repro_table.tex        tabella per il paper: mediana [min-max] tra i run
  results/fig_repro.pdf/.png     mediane con barre min-max (scala log)

Uso:
  python run_repro.py               # 10 run (PATCH_A1_V3)
  python run_repro.py --runs 3
  python run_repro.py --compare     # solo confronto dei run gia' presenti in results/runs/
"""
import argparse
import csv
import shutil
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
R = HERE / "results"
RUNS = R / "runs"
KEEP = ["queries.csv", "params.json", "summary_queries.csv", "summary_queries_by_table.csv",
        "engine_notes.csv", "env.json", "footprint.csv", "lakehouse_ops.csv"]


class MachineMonitor(threading.Thread):
    """Campiona lo stato della macchina ogni `every` secondi durante un run."""

    def __init__(self, every=5):
        super().__init__(daemon=True)
        self.every, self.samples, self._halt = every, [], threading.Event()

    def run(self):
        try:
            import psutil
        except ImportError:
            return
        psutil.cpu_percent(None)
        while not self._halt.wait(self.every):
            b = psutil.sensors_battery()
            f = psutil.cpu_freq()
            self.samples.append({
                "ora": time.strftime("%H:%M:%S"), "cpu_pct": psutil.cpu_percent(None),
                "cpu_mhz": round(f.current) if f else "",
                "ram_libera_gb": round(psutil.virtual_memory().available / 2**30, 2),
                "alimentatore": b.power_plugged if b else "desktop", "batteria_pct": round(b.percent) if b else ""})

    def stop(self):
        self._halt.set()
        self.join(timeout=15)

    def summary(self):
        s = self.samples
        if not s:
            return {"campioni": 0, "alimentazione_ok": "sconosciuta"}
        plugged = [x["alimentatore"] for x in s]
        mhz = [x["cpu_mhz"] for x in s if x["cpu_mhz"] != ""]
        batt = [x["batteria_pct"] for x in s if x["batteria_pct"] != ""]
        return {"campioni": len(s),
                "alimentazione_ok": all(p in (True, "desktop") for p in plugged),
                "campioni_a_batteria": sum(p is False for p in plugged),
                "batteria_min_pct": min(batt) if batt else "",
                "cpu_pct_medio": round(statistics.mean(x["cpu_pct"] for x in s), 1),
                "cpu_mhz_mediana": statistics.median(mhz) if mhz else "",
                "ram_libera_min_gb": min(x["ram_libera_gb"] for x in s)}


def keep_awake(on=True):
    """Impedisce la sospensione di Windows durante i run (nessun effetto su altri sistemi)."""
    if sys.platform != "win32":
        return
    import ctypes
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))
ORDER = ["sqlite", "sqlite_ix", "duckdb", "parquet", "delta"]
LABEL = {"sqlite": "SQLite", "sqlite_ix": "SQLite+idx", "duckdb": "DuckDB",
         "parquet": "Parquet+DuckDB", "delta": "Delta+DuckDB"}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def step(args):
    log(">>", " ".join(args))
    r = subprocess.run([sys.executable] + args, cwd=HERE)
    if r.returncode != 0:
        sys.exit(f"Interrotto: {' '.join(args)} ha restituito {r.returncode}")


def next_run_index():
    RUNS.mkdir(parents=True, exist_ok=True)
    done = [int(p.name.split("_")[1]) for p in RUNS.glob("run_*") if p.name.split("_")[1].isdigit()]
    return max(done, default=0) + 1


def one_run(k):
    t0 = time.time()
    mon = MachineMonitor()
    mon.start()
    try:
        step(["bench_storage.py", "--queries"])
        step(["bench_storage.py", "--lakehouse"])
        step(["make_report.py"])
    finally:
        mon.stop()
    dest = RUNS / f"run_{k}"
    dest.mkdir(parents=True, exist_ok=True)
    for f in KEEP:
        if (R / f).exists():
            shutil.copy2(R / f, dest / f)
    if mon.samples:
        with (dest / "machine_state.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(mon.samples[0]))
            w.writeheader()
            w.writerows(mon.samples)
    info = {"run": k, "inizio": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0)),
            "fine": time.strftime("%Y-%m-%d %H:%M:%S"), "durata_min": round((time.time() - t0) / 60, 1)}
    info.update(mon.summary())
    (dest / "run_info.txt").write_text("\n".join(f"{a}: {b}" for a, b in info.items()) + "\n", encoding="utf-8")
    flag = "" if info["alimentazione_ok"] is not False else "  [A BATTERIA: escluso dal confronto]"
    log(f"run {k} salvato in {dest} ({info['durata_min']} min){flag}")


def run_ok(p):
    """True se il run e' stato eseguito sempre con alimentatore (o su desktop / stato sconosciuto)."""
    f = p / "run_info.txt"
    if not f.exists():
        return True
    return "alimentazione_ok: False" not in f.read_text(encoding="utf-8")


def compare(include_battery=False, warmup=0):                # PATCH_A1_CLOSE: --warmup
    runs = sorted((p for p in RUNS.glob("run_*") if (p / "summary_queries.csv").exists()),
                  key=lambda p: int(p.name.split("_")[1]))
    excluded = [] if include_battery else [p.name for p in runs if not run_ok(p)]
    runs = [p for p in runs if p.name not in excluded]
    if excluded:
        log(f"Esclusi perche' eseguiti a batteria: {', '.join(excluded)}")
    warm = [p.name for p in runs[:warmup]]
    runs = runs[warmup:]
    if warm:
        log(f"Esclusi come warm-up (cache fredda): {', '.join(warm)}")
    if len(runs) < 2:
        sys.exit("Servono almeno 2 run in results/runs/ per il confronto.")
    frames = []
    for p in runs:
        s = pd.read_csv(p / "summary_queries.csv")[["query", "engine", "median_s"]]
        frames.append(s.rename(columns={"median_s": p.name}))
    m = frames[0]
    for f in frames[1:]:
        m = m.merge(f, on=["query", "engine"], how="outer")
    cols = [p.name for p in runs]
    m["median_runs"] = m[cols].median(axis=1)
    m["min"] = m[cols].min(axis=1)
    m["max"] = m[cols].max(axis=1)
    m["max_over_min"] = m["max"] / m["min"]
    m["q1"] = m[cols].quantile(0.25, axis=1)
    m["q3"] = m[cols].quantile(0.75, axis=1)
    m["q3_over_q1"] = m["q3"] / m["q1"]
    m = m[m["query"] != "Q2"]
    m["engine"] = pd.Categorical(m["engine"], [e for e in ORDER if e in set(m["engine"])], ordered=True)
    m = m.sort_values(["query", "engine"])
    m.to_csv(R / "repro_summary.csv", index=False)

    stab = m.groupby("engine", observed=True).agg(
        max_over_min_mediano=("max_over_min", "median"), max_over_min_peggiore=("max_over_min", "max"),
        q3_over_q1_mediano=("q3_over_q1", "median"), q3_over_q1_peggiore=("q3_over_q1", "max")).reset_index()
    stab.to_csv(R / "repro_stability.csv", index=False)

    def cell(r):
        if r["q3_over_q1"] < 1.10:                             # IQR entro il 10%: un solo numero
            return f"{r['median_runs']:.3f}"
        return f"{r['median_runs']:.3f} [{r['q1']:.3f}--{r['q3']:.3f}]"
    tab = m.assign(cell=m.apply(cell, axis=1)).pivot(index="query", columns="engine", values="cell")
    tab = tab[[e for e in ORDER if e in tab.columns]].rename(columns=LABEL)
    (R / "repro_table.tex").write_text(
        tab.to_latex(caption=f"Latenza mediana (s) su {len(runs)} run; tra parentesi l'intervallo "
                             f"interquartile tra i run quando supera il 10\\%.", label="tab:storage_repro"),
        encoding="utf-8")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        qs = sorted(m["query"].unique())
        engs = [e for e in ORDER if e in set(m["engine"].astype(str))]
        w = 0.8 / len(engs)
        fig, ax = plt.subplots(figsize=(9, 4))
        for i, e in enumerate(engs):
            d = m[m["engine"].astype(str) == e].set_index("query").reindex(qs)
            x = np.arange(len(qs)) + i * w
            ax.bar(x, d["median_runs"], w, label=LABEL[e])
            ax.errorbar(x, d["median_runs"], yerr=[d["median_runs"] - d["min"], d["max"] - d["median_runs"]],
                        fmt="none", ecolor="black", elinewidth=0.8, capsize=2)
        ax.set_xticks(np.arange(len(qs)) + 0.4 - w / 2)
        ax.set_xticklabels(qs)
        ax.set_yscale("log")
        ax.set_ylabel("Latenza mediana (s, log) - barre: min/max tra i run")
        ax.legend(frameon=False, fontsize=8, ncol=len(engs))
        plt.tight_layout()
        for ext in ("pdf", "png"):
            plt.savefig(R / f"fig_repro.{ext}", dpi=300)
    except ImportError:
        log("matplotlib non installato: figura saltata")

    lk = [pd.read_csv(p / "lakehouse_ops.csv").assign(run=p.name) for p in runs if (p / "lakehouse_ops.csv").exists()]
    if lk:
        lk = pd.concat(lk)
        lk["ok"] = lk["ok"].astype(str) == "True"
        g = lk.groupby("operation", sort=False)
        pd.DataFrame({"n": g.size(), "n_ok": g["ok"].sum(), "ok_all": g["ok"].all(),
                      "median_s": g["seconds"].median(), "min_s": g["seconds"].min(),
                      "max_s": g["seconds"].max()}).reset_index().to_csv(R / "repro_lakehouse.csv", index=False)

    (R / "repro_runs_used.txt").write_text(
        "usati: " + ", ".join(p.name for p in runs) + "\nesclusi (batteria): " + (", ".join(excluded) or "nessuno")
        + "\nesclusi (warm-up): " + (", ".join(warm) or "nessuno") + "\n",
        encoding="utf-8")
    log(f"Confronto su {len(runs)} run")
    print(stab.round(2).to_string(index=False))
    if (HERE / "make_lakehouse_checklist.py").exists():
        step(["make_lakehouse_checklist.py"])
    else:
        log("make_lakehouse_checklist.py non trovato: checklist P2 saltata")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--compare", action="store_true", help="solo confronto dei run gia' salvati")
    ap.add_argument("--include-battery", action="store_true", help="tiene nel confronto anche i run a batteria")
    ap.add_argument("--warmup", type=int, default=0, help="esclude dal confronto i primi N run (cache fredda)")
    a = ap.parse_args()
    if not a.compare:
        keep_awake(True)
        try:
            start = next_run_index()
            for k in range(start, start + a.runs):
                log(f"===== run {k} di {start + a.runs - 1} =====")
                one_run(k)
        finally:
            keep_awake(False)
    compare(a.include_battery, a.warmup)


if __name__ == "__main__":
    main()
