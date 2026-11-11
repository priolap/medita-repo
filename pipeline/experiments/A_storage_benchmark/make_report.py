#!/usr/bin/env python3
"""
make_report.py - tabella e figura del benchmark A1 a partire da results/.

Output in results/:
  summary_engines.csv / .tex   ingestion totale, footprint, rapporto sul testo
  summary_queries.csv / .tex   mediana e p95 (ripetizioni calde) e prima esecuzione, per query x engine
  fig_query_latency.pdf/.png   latenza mediana per query (scala log)
"""
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
R = HERE / "results"
ORDER = ["sqlite", "sqlite_ix", "duckdb", "parquet", "delta"]
LABEL = {"sqlite": "SQLite", "sqlite_ix": "SQLite+idx", "duckdb": "DuckDB",
         "parquet": "Parquet+DuckDB", "delta": "Delta+DuckDB"}


def main():
    ing = pd.read_csv(R / "ingestion.csv")
    foot = pd.read_csv(R / "footprint.csv").sort_values("measured").groupby("engine").tail(1)
    txt = pd.read_csv(R / "tables.csv")["bytes"].sum()

    ok = ing[ing.status == "ok"].drop_duplicates(["engine", "table"], keep="last")
    eng = ok.groupby("engine").agg(tables=("table", "count"), ingest_s=("seconds", "sum")).reset_index()
    eng = eng.merge(foot[["engine", "bytes"]], on="engine", how="outer")
    if "sqlite_ix" in set(eng.engine) and "sqlite" in set(eng.engine):   # tempo indici = load + indici
        base = eng.loc[eng.engine == "sqlite", "ingest_s"].iloc[0]
        eng.loc[eng.engine == "sqlite_ix", "ingest_s"] += base
        eng.loc[eng.engine == "sqlite_ix", "tables"] = eng.loc[eng.engine == "sqlite", "tables"].iloc[0]
    eng["footprint_GB"] = eng["bytes"] / 1e9
    eng["ratio_vs_txt"] = eng["bytes"] / txt
    eng["ingest_min"] = eng["ingest_s"] / 60
    eng = eng.set_index("engine").reindex([e for e in ORDER if e in set(eng.engine)]).reset_index()
    eng.to_csv(R / "summary_engines.csv", index=False)
    (R / "summary_engines.tex").write_text(
        eng.assign(engine=eng.engine.map(LABEL))[["engine", "tables", "ingest_min", "footprint_GB", "ratio_vs_txt"]]
        .to_latex(index=False, float_format="%.2f",
                  caption=f"Ingestion e footprint su {txt / 1e9:.2f} GB di testo trasformato.",
                  label="tab:storage_engines"), encoding="utf-8")

    q = pd.read_csv(R / "queries.csv")
    q = q[(q.status == "ok") & (q["query"] != "Q2")]      # Q2 (catalogo) non confrontabile tra engine  # PATCH_A1_V2
    # per tabella: mediana e p95 delle ripetizioni calde; poi somma sulle tabelle (S/M/L) per query x engine
    keys = ["query", "engine", "table"]
    warm = q[~q.cold].groupby(keys)["seconds"]
    per_t = pd.concat([warm.median().rename("median_s"), warm.quantile(0.95).rename("p95_s"),
                       q[q.cold].groupby(keys)["seconds"].sum().rename("first_s")], axis=1).reset_index()
    per_t.to_csv(R / "summary_queries_by_table.csv", index=False)
    summ = per_t.groupby(["query", "engine"])[["median_s", "p95_s", "first_s"]].sum().reset_index()
    summ.to_csv(R / "summary_queries.csv", index=False)
    piv = summ.pivot(index="query", columns="engine", values="median_s")
    piv = piv[[e for e in ORDER if e in piv.columns]].rename(columns=LABEL)
    (R / "summary_queries.tex").write_text(
        piv.to_latex(float_format="%.3f", caption="Latenza mediana (s) per query, somma sulle tabelle XS/S/M/L.",
                     label="tab:storage_queries"), encoding="utf-8")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        ax = piv.plot(kind="bar", figsize=(8, 4), logy=True, width=0.8)
        ax.set_ylabel("Latenza mediana (s, log)")
        ax.set_xlabel("")
        ax.legend(frameon=False, fontsize=8)
        plt.xticks(rotation=0)
        plt.tight_layout()
        for ext in ("pdf", "png"):
            plt.savefig(R / f"fig_query_latency.{ext}", dpi=300)
    except ImportError:
        print("matplotlib non installato: figura saltata")

    print(eng.to_string(index=False))
    print()
    print(piv.round(4).to_string())


if __name__ == "__main__":
    main()
