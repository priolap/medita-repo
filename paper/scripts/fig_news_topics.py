# -*- coding: utf-8 -*-
"""Figure 2.3: health-news documents per year and topic.

Input : results/news/news_year_topic.csv (aggregated, published)
Output: figures/fig_2_3_news_topics_over_time.{pdf,png}
The 8 largest topics get a colour; 'uncategorized' is always neutral grey.
"""
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import FuncFormatter, MultipleLocator

from common import NEUTRAL, PALETTE, RESULTS, save, set_style


def main():
    src = RESULTS / "news" / "news_year_topic.csv"
    if not src.exists():
        raise SystemExit(f"{src} missing: the aggregated news counts are part of the repository.")  # REPO_NEWS_261111
    df = pd.read_csv(src)
    pivot = df.pivot_table(index="YEAR", columns="TOPIC", values="documents", aggfunc="sum", fill_value=0)
    named = [c for c in pivot.sum().sort_values(ascending=False).index if c != "uncategorized"]
    if len(named) > len(PALETTE):
        raise SystemExit(f"{len(named)} topics: more than {len(PALETTE)} colour slots, fold into Other first")
    cols = named + (["uncategorized"] if "uncategorized" in pivot.columns else [])
    colors = PALETTE[:len(named)] + ([NEUTRAL] if "uncategorized" in pivot.columns else [])
    pivot = pivot[cols]

    set_style()
    fig, ax = plt.subplots(figsize=(7.0, 3.4))
    ax.stackplot(pivot.index, [pivot[c].values for c in cols], colors=colors, labels=cols,
                 edgecolor="white", linewidth=0.4)
    ax.set_xlabel("Year")
    ax.set_ylabel("Documents")
    ax.set_xlim(pivot.index.min(), pivot.index.max())
    ax.xaxis.set_major_locator(MultipleLocator(2))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.17), handlelength=1.0,
              columnspacing=1.2)
    paths = save(fig, "fig_2_3_news_topics_over_time")
    plt.close(fig)
    print("Wrote", *paths)


if __name__ == "__main__":
    main()
