# -*- coding: utf-8 -*-
"""Experiment A (storage): tables tab:storage_benchmark, tab:storage_latency, tab:lakehouse_checklist,
figure fig:storage_latency (figures/fig_repro.pdf) and the lakehouse Load figures quoted in the text.

Input : results/experiments/A_storage_benchmark/{summary_engines,repro_summary,repro_runs_used,p2_checklist}
        results/experiments/A_lake/misura_lake__{sintesi,tempi}.csv
Output: tables/tab_storage_benchmark, tab_storage_latency, tab_lakehouse_checklist, lake_load (.csv/.tex)
        figures/fig_repro.{pdf,png}
Producers: pipeline/experiments/A_storage_benchmark/bench_storage.py + run_repro.py (night run),
           pipeline/experiments/A_lake/misura_lake_notte.py
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from exp_common import Checks, f, read, save_fig, write_table

A, LAKE = "A_storage_benchmark", "A_lake"
ORDER = ["sqlite", "sqlite_ix", "duckdb", "parquet", "delta"]
NAMES = {"sqlite": "SQLite (baseline)", "sqlite_ix": "SQLite + indexes", "duckdb": "DuckDB",
         "parquet": "Parquet + DuckDB", "delta": "Delta Lake + DuckDB"}
SHORT = {"sqlite": "SQLite", "sqlite_ix": "SQLite + idx", "duckdb": "DuckDB", "parquet": "Parquet",
         "delta": "Delta Lake"}
FIG_LABEL = {"sqlite": "SQLite", "sqlite_ix": "SQLite + indexes", "duckdb": "DuckDB",
             "parquet": "Parquet + DuckDB", "delta": "Delta Lake + DuckDB"}
OPERATION = {"Q1": "Full read into pandas", "Q3": "Slice", "Q4": "Dice", "Q5": "Roll-up",
             "Q6": "Count by year", "Q7": r"Join MINIS \(\times\) ISTAT", "Q8": "High-cardinality group-by",
             "Q9": "Missingness profile"}
FEATURES = {  # p2_checklist.csv (Italian) -> paper
    "Formato dei dati aperto": "Open data format",
    "Storage colonnare e compressione": "Columnar storage and compression",
    "Transazioni ACID": "ACID transactions",
    "Schema enforcement": "Schema enforcement",
    "Schema evolution": "Schema evolution",
    "Time travel (lettura di versioni precedenti)": "Time travel",
    "Rollback a una versione precedente": "Rollback to a previous version",
    "Separazione storage / compute": "Separation of storage and compute",
    "Analisi e ML sugli stessi dati senza copie": "Analytics and ML without data copies",
}
CONFIGS = ["SQLite (MEDITA attuale)", "DuckDB", "Parquet + DuckDB", "Delta Lake + DuckDB"]
STATE = {"Si'": r"\checkmark", "Parziale": r"$\sim$", "No": "--"}


def gb(x):
    return f(x, 2) if x >= 1 else f(x, 3)


def storage_benchmark(chk):
    s = read(A, "summary_engines.csv").set_index("engine").loc[ORDER]
    rows = [[NAMES[e], f(r.ingest_min, 2), gb(r.footprint_GB), gb(r.ratio_vs_txt)] for e, r in s.iterrows()]
    write_table("tab_storage_benchmark", rows,
                ["Backend", "Ingestion time (min)", "Storage footprint (GB)", "Footprint / text"],
                "Storage backend benchmark: ingestion time and storage footprint of the 82 tables of the "
                r"snapshot (6.79\,GB of pipe-delimited text).", "tab:storage_benchmark",
                note="one full load in a controlled session; indexes on (year, region code).")
    paper = {"sqlite": ("2.37", "7.06", "1.04"), "sqlite_ix": ("2.51", "7.33", "1.08"),
             "duckdb": ("0.99", "0.660", "0.097"), "parquet": ("0.56", "0.234", "0.034"),
             "delta": ("0.75", "0.310", "0.046")}
    for row, e in zip(rows, ORDER):
        for got, exp, what in zip(row[1:], paper[e], ("ingestion", "footprint", "ratio")):
            chk.eq(f"storage {e} {what}", got, exp)
    chk.eq("tables", int(s.tables.iloc[0]), 82)


def storage_latency(chk):
    m = read(A, "repro_summary.csv")
    runs = [c for c in m.columns if c.startswith("run_")]
    chk.eq("runs used", len(runs), 9)
    rows = []
    for q, g in m.groupby("query", sort=True):
        g = g.set_index("engine")
        rows.append([q, OPERATION[q]] + [f(g.loc[e, "median_runs"], 3) for e in ORDER])
    write_table("tab_storage_latency", rows, ["Query", "Operation"] + [SHORT[e] for e in ORDER],
                "Median query latency (s) over nine runs, summed over the four benchmark tables.",
                "tab:storage_latency", colspec="llrrrrr",
                note="Parquet and Delta Lake are queried with DuckDB.")
    paper = {"Q1": ["21.584", "21.556", "6.408", "6.450", "6.453"], "Q5": ["1.886", "4.795", "0.025", "0.031", "0.060"],
             "Q8": ["1.187", "1.194", "0.005", "0.010", "0.017"], "Q9": ["1.333", "1.331", "0.010", "0.014", "0.109"]}
    for r in rows:
        for got, exp, e in zip(r[2:], paper.get(r[0], [None] * 5), ORDER):
            if exp is not None:
                chk.eq(f"latency {r[0]} {e}", got, exp)
    chk.eq("IQR within 8% (q3/q1 < 1.08 in every cell)", bool((m["q3_over_q1"] < 1.08).all()), True)
    return m


def fig_repro(m):
    qs = sorted(m["query"].unique())
    w = 0.8 / len(ORDER)
    colors = ["#8a8984", "#c3c2bd", "#2a78d6", "#eb6834", "#1baf7a"]
    plt.rcParams.update({"font.size": 8, "axes.labelsize": 8, "xtick.labelsize": 7, "ytick.labelsize": 7,
                         "legend.fontsize": 7, "pdf.fonttype": 42, "axes.spines.top": False,
                         "axes.spines.right": False})
    fig, ax = plt.subplots(figsize=(7.0, 3.1))
    for i, e in enumerate(ORDER):
        d = m[m["engine"] == e].set_index("query").reindex(qs)
        x = np.arange(len(qs)) + i * w
        ax.bar(x, d["median_runs"], w, label=FIG_LABEL[e], color=colors[i], edgecolor="white", linewidth=0.3)
        ax.errorbar(x, d["median_runs"], yerr=[d["median_runs"] - d["min"], d["max"] - d["median_runs"]],
                    fmt="none", ecolor="#2b2a28", elinewidth=0.6, capsize=1.5)
    ax.set_xticks(np.arange(len(qs)) + 0.4 - w / 2)
    ax.set_xticklabels(qs)
    ax.set_yscale("log")
    ax.set_xlabel("Query")
    ax.set_ylabel("Median latency (s, log scale)")
    ax.grid(axis="y", color="#e3e2de", lw=0.5)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, ncol=len(ORDER), loc="upper center", bbox_to_anchor=(0.5, 1.12))
    fig.text(0.99, 0.01, "bars: min-max across runs", ha="right", va="bottom", fontsize=6.5, color="#6b6a66")
    fig.tight_layout()
    save_fig(fig, "fig_repro")
    plt.close(fig)


def lakehouse_checklist(chk):
    p = read(A, "p2_checklist.csv")
    p = p[p["area"] == "Storage"]
    rows = []
    for feat_it, feat_en in FEATURES.items():
        g = p[p["feature"] == feat_it].set_index("configurazione")
        cells = []
        for c in CONFIGS:
            r = g.loc[c]
            cells.append(STATE[r["stato"]] + ("$^{m}$" if r["evidenza"] == "misurata" else ""))
        rows.append([feat_en] + cells)
    write_table("tab_lakehouse_checklist", rows,
                ["Feature", "SQLite", "DuckDB", r"Parquet\(^{\dagger}\)", r"Delta Lake\(^{\dagger}\)"],
                r"Lakehouse features by storage configuration (\checkmark{} present, $\sim$ partial, -- absent; "
                r"$^{m}$ demonstrated in the benchmark, otherwise documented).", "tab:lakehouse_checklist",
                note=r"\(^{\dagger}\)queried with DuckDB.")
    lk = read(A, "repro_lakehouse.csv")
    chk.eq("lakehouse operations ok", f"{int(lk.n_ok.min())}/{int(lk.n.max())}", "9/9")
    chk.eq("checklist Delta time travel", rows[5][4], r"\checkmark$^{m}$")
    chk.eq("checklist SQLite columnar", rows[1][1], r"--$^{m}$")
    chk.eq("checklist Parquet ACID", rows[2][3], "--")


def lake_load(chk):
    s = read(LAKE, "misura_lake__sintesi.csv").set_index("MISURA")["VALORE"]
    v = {k.strip(): float(x) for k, x in s.items()}
    tot = v[next(k for k in v if k.startswith("Load sul lake, tempo totale"))]
    bronze = v[next(k for k in v if k.startswith("di cui bronze"))]
    silver = v[next(k for k in v if k.startswith("di cui silver"))]
    gold = v[next(k for k in v if k.startswith("di cui gold"))]
    lake1 = v["Lake nuovo (una versione): byte totali"]
    sql = v["DB.sql + DB_ts.sql: byte"]
    rows = [["First complete Load (s)", f(tot, 1)], ["  raw zone: catalogue and SHA-256 of the raw files (s)", f(bronze, 1)],
            ["  harmonized zone (s)", f(silver, 1)], ["  curated zone (s)", f(gold, 1)],
            ["Lakehouse, one version per table (GB)", f(lake1 / 1e9, 2)],
            ["Relational database of the previous release (GB)", f(sql / 1e9, 2)],
            ["Relational / lakehouse", f(sql / lake1, 1)]]
    write_table("lake_load", rows, ["Measure", "Value"], "Load into the lakehouse: time and footprint (one run).",
                "tab:lake_load", colspec="lr", note="figures quoted in the text, not a table of the paper.")
    chk.eq("lake Load s", f(tot, 0), "216")
    chk.eq("lake bronze s", f(bronze, 0), "35")
    chk.eq("lake silver s", f(silver, 0), "132")
    chk.eq("lake GB", f(lake1 / 1e9, 2), "1.24")
    chk.eq("relational GB", f(sql / 1e9, 2), "9.06")
    chk.eq("ratio", f(sql / lake1, 1), "7.3")


def main():
    chk = Checks("A storage")
    storage_benchmark(chk)
    m = storage_latency(chk)
    fig_repro(m)
    lakehouse_checklist(chk)
    lake_load(chk)
    chk.done()


if __name__ == "__main__":
    main()
