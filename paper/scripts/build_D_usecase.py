# -*- coding: utf-8 -*-
"""Experiment D (use case): tables tab:usecase_matching, tab:usecase_join, tab:missingness and figures
fig:usecase_matching (d14_fig2_abbinamenti.pdf), fig:missingness (d15_fig1_heatmap.pdf).

Input : results/experiments/D_case_study/d14_integrazione__{2_abbinamenti,7_join_A,7_join_B}.csv
        (pipeline/experiments/D_case_study/d14_integrazione_descrittiva.ipynb)
        results/experiments/D_case_study/d15_missingness__{dominio,comparabilita_dominio,dominio_x_regione,
        controlli}.csv (pipeline/experiments/D_case_study/d15_missingness.ipynb)
        pipeline/config/codregione_map.json (region names)
Output: tables/tab_usecase_matching, tab_usecase_join_keys, tab_usecase_join_values, tab_missingness (.csv/.tex)
        figures/d14_fig2_abbinamenti, d15_fig1_heatmap (.pdf/.png)
"""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import REPO
from exp_common import Checks, f, read, save_fig, write_table

D = "D_case_study"
PAIRS = [("AIFA", "MINIS"), ("AIFA", "ISTAT_DECESSI"), ("AIFA", "ISTAT_AVQ"), ("MINIS", "ISTAT_DECESSI"),
         ("MINIS", "ISTAT_AVQ"), ("ISTAT_DECESSI", "ISTAT_AVQ")]
SRC_EN = {"AIFA": "AIFA", "MINIS": "MINIS", "ISTAT_DECESSI": "ISTAT deaths", "ISTAT_AVQ": "ISTAT daily-life survey"}
PATHS = [("R0 codici originali", "R0 original codes", "#eb6834"), ("R1 nomi normalizzati", "R1 normalised names", "#1baf7a"),
         ("H MEDITA", "H MEDITA", "#2a78d6")]
DOMAINS = [  # (source, TAG in the data, label in the paper), in the order of tab:missingness
    ("AIFA", "Farmaceutica", "Pharmaceuticals"), ("ISTAT", "Educazione e Disabilità", "Education and disability"),
    ("ISTAT", "Salute e Mortalità", "Health and mortality"), ("ISTAT", "Dati Ospedalieri", "Hospital data"),
    ("ISTAT", "Previdenza Sociale", "Social security"), ("ISTAT", "Indicatori Sociodemografici", "Sociodemographic indicators"),
    ("ISTAT", "Violenza", "Violence"), ("MINIS", "Dati Ospedalieri", "Hospital data"),
    ("MINIS", "Personale del SSN", "NSS personnel"), ("MINIS", "Salute Mentale", "Mental health"),
    ("MINIS", "Dispositivi Medici", "Medical devices"), ("MINIS", "Sistema Sanitario Nazionale", "National health system")]
DOM_EN_FIG = {"Salute e Mortalità": "Health & mortality", "Previdenza Sociale": "Social security",
              "Indicatori Sociodemografici": "Socio-demographic", "Educazione e Disabilità": "Education & disability",
              "Violenza": "Violence", "Dati Ospedalieri": "Hospital data", "Salute Mentale": "Mental health",
              "Personale del SSN": "NHS staff", "Dispositivi Medici": "Medical devices",
              "Sistema Sanitario Nazionale": "National health service", "Farmaceutica": "Pharmaceutical"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
STYLE = {"font.size": 8, "axes.titlesize": 9, "axes.labelsize": 8, "xtick.labelsize": 7, "ytick.labelsize": 7,
         "legend.fontsize": 7, "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2,
         "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False, "pdf.fonttype": 42,
         "savefig.bbox": "tight"}


def usecase_matching(chk):
    a = read(D, "d14_integrazione__2_abbinamenti.csv")
    w = a.pivot_table(index=["FONTE_A", "FONTE_B"], columns="PERCORSO", values="QUOTA_%")
    rows = [[f"{SRC_EN[x]} -- {SRC_EN[y]}"] + [f(w.loc[(x, y), p], 1) for p, _, _ in PATHS] for x, y in PAIRS]
    write_table("tab_usecase_matching", rows, ["Pair of sources", "R0 original codes", "R1 normalized names", "H MEDITA"],
                "Comparability between sources: percentage of (unit, year) cells matched on the years common to each "
                "pair of sources, by matching strategy.", "tab:usecase_matching",
                note="21 reporting units (19 regions and the autonomous provinces of Bolzano and Trento).")
    paper = ["100.0 82.5 100.0", "0.0 79.4 100.0", "0.0 80.3 100.0", "0.0 85.7 100.0", "0.0 85.7 100.0", "100.0 100.0 100.0"]
    for r, e in zip(rows, paper):
        chk.eq(f"usecase matching {r[0]}", " ".join(r[1:]), e)
    return w


def fig_matching(w):
    """Same figure as d14_integrazione_descrittiva (cell 8), with the shares of 2_abbinamenti."""
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(7, 2.4))
        bw, y = 0.26, np.arange(len(PAIRS))
        for j, (p, lab, col) in enumerate(PATHS):
            v = np.array([w.loc[pr, p] for pr in PAIRS])
            ax.barh(y + (j - 1) * bw, v, height=bw - 0.03, color=col, label=lab)
            for yi, vi in zip(y + (j - 1) * bw, v):
                ax.text(vi + 1, yi, f"{vi:.0f}", va="center", fontsize=6, color=INK2)
        ax.set_yticks(y, [f"{a} – {b}".replace("ISTAT_", "ISTAT ") for a, b in PAIRS])
        ax.invert_yaxis()
        ax.set_xlim(0, 112)
        ax.set_xlabel("linked (unit, year) cells, %")
        ax.grid(axis="x", color=GRID, lw=0.6)
        ax.set_axisbelow(True)
        ax.legend(loc="lower right", frameon=False, ncol=3, bbox_to_anchor=(1, 1.0))
        save_fig(fig, "d14_fig2_abbinamenti")
        plt.close(fig)


def usecase_join(chk):
    ka = read(D, "d14_integrazione__7_join_A.csv", dtype=str)
    kb = read(D, "d14_integrazione__7_join_B.csv")
    it = lambda s: "--" if s in ("—", "", "nan") else s.split(" / ")[0]
    yes = lambda s: r"$\checkmark$" if s.strip().lower() in ("sì", "si", "yes") else r"$\times$"
    rows = []
    for _, r in ka.iterrows():
        nuts = r["MEDITA_CODICE_REGIONE"].split(" ")[0]
        rows.append([r.REGIONE, it(r.AIFA_CODICE_GREZZO), it(r.AIFA_NOME_GREZZO), it(r.MINIS_CODICE_GREZZO),
                     it(r.MINIS_NOME_GREZZO), it(r.ISTAT_CODICE_GREZZO), it(r.ISTAT_NOME_GREZZO), nuts,
                     yes(r["JOIN_R0 codici originali"]), yes(r["JOIN_R1 nomi normalizzati"]), yes(r["JOIN_H MEDITA"])])
    year = ka.ANNO.iloc[0]
    write_table("tab_usecase_join_keys", rows, ["Region", "AIFA code", "AIFA name", "MINIS code", "MINIS name",
                                                "ISTAT code", "ISTAT name", "MEDITA NUTS", "R0", "R1", "H"],
                f"Example of cross-source join, {year}: territorial keys in the raw sources and in MEDITA.",
                "tab:usecase_join", colspec="lllllllcccc",
                note="ISTAT names are bilingual in the source; only the Italian part is shown.")
    num = lambda x, d=0: "--" if pd.isna(x) else f"{x:,.{d}f}"
    rows_v = [[r.REGIONE, num(r.H_N06A_CONF), num(r.H_POSTI_LETTO), num(r.H_POPOLAZIONE), num(r.H_N06A_X1000, 1),
               num(r.R1_N06A_CONF), num(r.R1_POSTI_LETTO), num(r.R1_POPOLAZIONE), num(r.R1_N06A_X1000, 1)]
              for _, r in kb.iterrows()]
    write_table("tab_usecase_join_values", rows_v, ["Region", "H: N06A packs", "H: beds", "H: population", "H: per 1,000",
                                                    "R1: N06A packs", "R1: beds", "R1: population", "R1: per 1,000"],
                f"Example of cross-source join, {year}: joined values (H MEDITA, R1 normalized names).",
                "tab:usecase_join_values", colspec="lrrrrrrrr",
                note="N06A packs: antidepressants, class A, reimbursed (AIFA); beds: hospital beds (MINIS); population "
                     "estimated from ISTAT deaths and mortality rates. R1 is a star join on AIFA.")
    chk.eq("join year", year, "2019")
    paper_keys = {"Lombardia": "030 LOMBARDI 030 LOMBARDIA ITC4 ITC4 x x v", "Valle d'Aosta": "020 VALLE D' 020 VALLE D`AOSTA ITC2 ITC2 x x v",
                  "P.A. Bolzano": "041 PA BOLZA 041 PROV. AUTON. BOLZANO ITD1 ITH1 x x v",
                  "Trentino-Alto Adige": "-- -- -- -- ITDA ITH0 x x v", "Lazio": "120 LAZIO 120 LAZIO ITE4 ITI4 x v v"}
    sym = {r"$\checkmark$": "v", r"$\times$": "x"}
    for r in rows:
        got = " ".join([r[1], r[2], r[3], r[4], r[5], r[7]] + [sym[x] for x in r[8:]])
        chk.eq(f"join keys {r[0]}", got, paper_keys[r[0]])
    paper_vals = {"Lombardia": "5,920,242 37,817 9,998,300 592.1 5,920,242 -- -- --",
                  "Valle d'Aosta": "73,544 485 125,405 586.5 73,544 -- -- --",
                  "P.A. Bolzano": "381,632 1,912 530,238 719.7 381,632 -- -- --",
                  "Trentino-Alto Adige": "712,614 4,052 1,070,562 665.6 -- -- -- --",
                  "Lazio": "3,289,127 20,818 5,736,970 573.3 3,289,127 20,818 5,736,970 573.3"}
    for r in rows_v:
        chk.eq(f"join values {r[0]}", " ".join(r[1:]), paper_vals[r[0]])


def pct(x):
    """100 and 0 without decimals, small shares with two, the rest with one (as in tab:missingness)."""
    if x == 100 or x == 0:
        return f"{x:.0f}"
    return f(x, 2) if x < 0.1 else f(x, 1)


def missingness(chk):
    d = read(D, "d15_missingness__dominio.csv").set_index(["FONTE", "TAG"])
    c = read(D, "d15_missingness__comparabilita_dominio.csv").set_index(["FONTE", "TAG"])
    rows = []
    for src, tag, lab in DOMAINS:
        r, k = d.loc[(src, tag)], c.loc[(src, tag)]
        rows.append([src, f"{lab} ({int(r.tabelle)})", pct(r["celle_complete_%"]), pct(r["regione_assente_%"]),
                     f"{int(k.CONFRONTABILI)}/{int(k.TABELLE_ANNO)} ({pct(k['CONFRONTABILI_%'])}\\%)"])
    pub = d.celle * (1 - d["anni_non_pubblicati_%"] / 100)
    complete_pub = (d["celle_complete_%"] * pub).sum() / pub.sum()
    complete_all = (d["celle_complete_%"] * pub).sum() / d.celle.sum()
    comp, tot = int(c.CONFRONTABILI.sum()), int(c.TABELLE_ANNO.sum())
    rows.append(r"\midrule")
    rows.append([r"\multicolumn{2}{l}{\textbf{All sources (" + f"{int(d.tabelle.sum())} tables)" + "}}", "",
                 r"\textbf{" + f(complete_pub, 1) + "}", "", r"\textbf{" + f"{comp}/{tot} ({f(100 * comp / tot, 1)}\\%)" + "}"])
    write_table("tab_missingness", rows, ["Source", "Domain (tables)", "Complete cells (%)", "Region absent (%)",
                                          "Comparable table-years"],
                "Missingness by source and domain: complete cells and table-years comparable across all 20 regions "
                "(published years only).", "tab:missingness", colspec="llccc",
                note=f"cells are (table, unit, year) over 21 reporting units. Counting also the years a table was not "
                     f"published, {f(complete_all, 1)}\\% of all cells are complete.")
    paper = {"Pharmaceuticals (1)": ("100", "0", "7/7 (100\\%)"), "Education and disability (2)": ("95.2", "0", "2/2 (100\\%)"),
             "Health and mortality (7)": ("99.9", "0.07", "136/136 (100\\%)"), "Social security (3)": ("100", "0", "44/44 (100\\%)"),
             "Sociodemographic indicators (3)": ("89.0", "0", "33/88 (37.5\\%)"), "NSS personnel (8)": ("89.6", "10.4", "49/81 (60.5\\%)"),
             "Mental health (14)": ("83.7", "4.1", "13/51 (25.5\\%)"), "Medical devices (1)": ("98.6", "1.4", "7/10 (70.0\\%)"),
             "National health system (4)": ("98.8", "0", "3/4 (75.0\\%)"), "Violence (1)": ("100", "0", "1/1 (100\\%)")}
    for r in rows:
        if not isinstance(r, str) and r[1] in paper:
            chk.eq(f"missingness {r[0]} {r[1]}", " | ".join(r[2:]), " | ".join(paper[r[1]]))
    hosp = [r for r in rows if not isinstance(r, str) and r[1] == "Hospital data (4)"][0]
    chk.eq("missingness MINIS hospital", " | ".join(hosp[2:]), "99.9 | 0 | 42/43 (97.7\\%)")
    chk.eq("missingness comparable table-years", f"{comp}/{tot} ({f(100 * comp / tot, 1)}%)", "340/470 (72.3%)")
    # The paper prints 91.0 in the 'All sources' row: that is the share of complete cells over ALL cells (10,227,
    # also the years in which a table was not published: D15_risultati_riunione.txt, 9,305/10,227). The rows of the
    # table, and this row here, use the published years only: 94.3.
    chk.eq("missingness complete cells, all cells (paper: 91.0)", f(complete_all, 1), "91.0")
    chk.eq("missingness complete cells, published years", f(complete_pub, 1), "94.3")
    ctl = read(D, "d15_missingness__controlli.csv").set_index("voce")["valore"]
    chk.eq("cells (21 units)", int(ctl["celle (21 unita')"]), 10227)


def fig_heatmap():
    """Same figure as d15_missingness (cell 16), from the sheet dominio_x_regione."""
    cmap = json.loads((REPO / "pipeline" / "config" / "codregione_map.json").read_text(encoding="utf-8"))
    name = {k: v["REGIONE"] for k, v in cmap.items()}
    u21 = sorted(k for k in cmap if k != "ITH0")
    special = {"ITH1": "P.A. Bolzano", "ITH2": "P.A. Trento", "ITH0": "Trentino-Alto Adige", "ITC2": "Valle d'Aosta",
               "ITH4": "Friuli-Venezia Giulia", "ITH5": "Emilia-Romagna"}
    m = read(D, "d15_missingness__dominio_x_regione.csv").set_index("COD").reindex(u21)
    m.index = [special.get(u, name[u].title()) for u in m.index]
    cols = sorted(m.columns, key=lambda c: (c.split(": ")[0], c))
    m = m[cols]
    xl = [f"{c.split(': ')[0]} · {DOM_EN_FIG.get(c.split(': ', 1)[1], c.split(': ', 1)[1])}" for c in cols]
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(0.42 * len(cols) + 2.2, 5.2))
        im = ax.imshow(m.to_numpy(dtype=float), cmap="Blues", vmin=0, vmax=100, aspect="auto")
        ax.set_xticks(range(len(cols)), xl, rotation=50, ha="right")
        ax.set_yticks(range(len(m)), m.index)
        for i in range(m.shape[0]):
            for j in range(m.shape[1]):
                v = m.iat[i, j]
                if pd.notna(v) and v >= 0.5:
                    ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=5.5, color="white" if v > 55 else INK)
        for sp in ax.spines.values():
            sp.set_visible(False)
        fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02, label="incomplete (table, year) cells, %")
        ax.set_title("Incomplete cells by unit and source domain (published years)", loc="left", color=INK)
        save_fig(fig, "d15_fig1_heatmap")
        plt.close(fig)


def main():
    chk = Checks("D use case")
    w = usecase_matching(chk)
    fig_matching(w)
    usecase_join(chk)
    missingness(chk)
    fig_heatmap()
    chk.done()


if __name__ == "__main__":
    main()
