# -*- coding: utf-8 -*-
"""Figure 2.2 (observations per year and domain) and Table 2.4 (statistics by domain).

Input : results/data/table_stats.csv, yearly_obs.csv, features.csv, snapshot.json
        (produced by data_topic_stats.py)
Output: figures/fig_2_2_data_topics_over_time.{pdf,png}
        tables/tab_2_4_topic_stats.tex, tables/tab_2_4_topic_stats.csv
"""
import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter, MultipleLocator

from common import NEUTRAL, PALETTE, RESULTS, TABLES, save, set_style

N_SLOTS = len(PALETTE) - 1   # 7 largest domains get a colour, the rest is "Other"


def topic_table(stats, feats):
    g = stats.groupby("topic").agg(records=("records", "sum"), observations=("observations", "sum"),
                                   missing=("missing", "sum"), cells=("cells", "sum"))
    g["features"] = feats.drop_duplicates(["topic", "feature"]).groupby("topic").size()
    g["na_pct"] = 100 * g["missing"] / g["cells"]
    g = g.sort_index()
    total = pd.DataFrame({"records": [g.records.sum()], "observations": [g.observations.sum()],
                          "missing": [g.missing.sum()], "cells": [g.cells.sum()],
                          "features": [g.features.sum()]}, index=["Total"])
    total["na_pct"] = 100 * total.missing / total.cells
    return pd.concat([g, total])[["features", "observations", "records", "na_pct"]]


def write_tex(t, snapshot, n_tables):
    fmt = lambda v: f"{int(v):,}"
    lines = [r"\begin{table}[t]", r"\centering",
             r"\caption{Topic distribution statistics}", r"\label{tab:topic-stats}",
             r"\begin{tabular}{lrrrr}", r"\toprule",
             r"Topic & No. Features & No. Obs & No. Records & NAs (\%) \\", r"\midrule"]
    for topic, r in t.iterrows():
        if topic == "Total":
            lines.append(r"\midrule")
        lines.append(f"{topic} & {fmt(r.features)} & {fmt(r.observations)} & {fmt(r.records)} & {r.na_pct:.2f} \\\\")
    snaps = ", ".join(f"{s} {v['input_snapshot']}" for s, v in snapshot["sources"].items())
    lines += [r"\bottomrule", r"\end{tabular}",
              r"\par\smallskip\footnotesize Note: features are column-level attributes counted once per topic; "
              r"observations are non-missing cells; NAs (\%) = missing cells / all cells. "
              f"{n_tables} harmonised tables; snapshots: {snaps}.",
              r"\end{table}"]
    return "\n".join(lines) + "\n"


def main():
    d = RESULTS / "data"
    if not (d / "table_stats.csv").exists():
        raise SystemExit(f"{d / 'table_stats.csv'} missing: run 'python paper/make_all.py --from-data' "
                         "once with MEDITA_HOME pointing to the data snapshot.")
    stats = pd.read_csv(d / "table_stats.csv")
    yearly = pd.read_csv(d / "yearly_obs.csv")
    feats = pd.read_csv(d / "features.csv")
    snapshot = json.loads((d / "snapshot.json").read_text(encoding="utf-8"))

    TABLES.mkdir(parents=True, exist_ok=True)
    t = topic_table(stats, feats)
    t.to_csv(TABLES / "tab_2_4_topic_stats.csv")
    (TABLES / "tab_2_4_topic_stats.tex").write_text(write_tex(t, snapshot, len(stats)), encoding="utf-8")

    # ---- Figure 2.2: stacked bars, 7 largest domains + Other --------------------------
    pivot = yearly.pivot_table(index="year", columns="topic", values="observations",
                               aggfunc="sum", fill_value=0)
    pivot = pivot.reindex(range(pivot.index.min(), pivot.index.max() + 1), fill_value=0)
    order = pivot.sum().sort_values(ascending=False).index.tolist()
    keep, rest = order[:N_SLOTS], order[N_SLOTS:]
    plot = pivot[keep].copy()
    if rest:
        plot["Other (" + ", ".join(rest) + ")" if len(rest) <= 2 else "Other"] = pivot[rest].sum(axis=1)
    colors = PALETTE[:len(keep)] + ([NEUTRAL] if rest else [])

    set_style()
    fig, ax = plt.subplots(figsize=(7.0, 3.4))
    bottom = np.zeros(len(plot))
    x = plot.index.values
    for col, c in zip(plot.columns, colors):
        v = plot[col].values / 1e6
        ax.bar(x, v, bottom=bottom, width=0.8, color=c, edgecolor="white", linewidth=0.4, label=col)
        bottom += v
    ax.set_xlabel("Year")
    ax.set_ylabel("Observations (millions)")
    ax.set_xlim(x.min() - 0.8, x.max() + 0.8)
    ax.xaxis.set_major_locator(MultipleLocator(5))
    ax.xaxis.set_minor_locator(MultipleLocator(1))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    ax.tick_params(axis="x", which="minor", length=1.5)
    ax.legend(ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.17), handlelength=1.0,
              columnspacing=1.2)
    paths = save(fig, "fig_2_2_data_topics_over_time")
    plt.close(fig)
    if rest:
        print("Folded into Other:", rest)
    print("Wrote", *paths, TABLES / "tab_2_4_topic_stats.tex")


if __name__ == "__main__":
    main()
