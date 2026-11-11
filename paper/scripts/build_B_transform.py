# -*- coding: utf-8 -*-
"""Experiment B (Transform): tables tab:matching_quality, tab:threshold, tab:baselines, tab:ablation,
tab:superkey_times, tab:scalability and figures fig:threshold (b2_threshold_curve.pdf),
fig:baselines (b6_baselines.pdf).

Input : results/experiments/B_fuzzy_eval/b4_risultati__{confusione,curva}.csv (b4_stats.py)
        results/experiments/B_baseline/b6_baseline__metriche.csv (b6_baseline.py)
        results/experiments/B_ablation/b3_sintesi_ablation__{sintesi,controllo_full}.csv (ablation_transform.py)
        results/experiments/B_superkey/superkey_tests__{tempi_sintetici,tempi_reali}.csv (superkey_tests.py)
        results/experiments/B_scalabilita/b5_scalabilita__{sintesi,pulizia}.csv (b5_scalabilita.py)
Output: tables/tab_matching_quality, tab_threshold, tab_baselines, tab_ablation, tab_superkey_times,
        tab_scalability (.csv/.tex); figures/b2_threshold_curve, b6_baselines (.pdf/.png)
The 95% intervals of precision, recall and F1 are recomputed here (bootstrap of the pairs as a
multinomial draw on the confusion cells, B = 10,000, seed 20261101).
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from exp_common import Checks, ci, f, read, rnd, save_fig, write_table

FZ, BL, AB, SK, SC = "B_fuzzy_eval", "B_baseline", "B_ablation", "B_superkey", "B_scalabilita"
PLATFORM = 90
METHODS = {"fuzzy": "Fuzzy (MEDITA)", "coma": "COMA", "jaro_winkler": "Jaro-Winkler", "embedding": "Embedding",
           "cupid": "Cupid (EN WordNet)", "token_set": "Token-set ratio", "sflooding": "Similarity Flooding",
           "cupid_ita": "Cupid (IT WordNet)"}
SEED, B = 20261101, 10_000


# ---------------------------------------------------------------- matching quality and threshold
def bootstrap_prf(tp, fp, fn, tn):
    """Same computation as experiments/paper_rev/b2_bootstrap_prf.py (01/11/2026)."""
    rng = np.random.default_rng(SEED)
    n = tp + fp + fn + tn
    s = rng.multinomial(n, np.array([tp, fp, fn, tn]) / n, size=B)
    TP, FP, FN = s[:, 0], s[:, 1], s[:, 2]
    out = {}
    with np.errstate(all="ignore"):
        for k, v in {"P": TP / (TP + FP), "R": TP / (TP + FN), "F1": 2 * TP / (2 * TP + FP + FN)}.items():
            v = v[~np.isnan(v)]
            out[k] = tuple(np.percentile(v, [2.5, 97.5]))
    return out


def matching_quality(chk):
    c = read(FZ, "b4_risultati__confusione.csv").set_index("step")
    m = read(BL, "b6_baseline__metriche.csv")
    fz = m[m["metodo"] == "fuzzy"].set_index("step")
    can, fil = c.loc["canonical"], c.loc["files"]
    bs = bootstrap_prf(int(can.TP), int(can.FP), int(can.FN), int(can.TN))
    sci = lambda lo, hi: r"{\scriptsize " + ci(lo, hi) + "}"
    rows = [["Pairs", int(can.coppie), "", int(fil.coppie), ""]]
    for k in ("TP", "FP", "FN", "TN"):
        rows.append([k, int(can[k]), "", int(fil[k]), ""])
    for k, lab in (("P", "Precision"), ("R", "Recall"), ("F1", "F1")):
        rows.append([lab, f(can[k]), sci(*bs[k]), f(fil[k]), ""])
    for k in ("AUC", "AP"):
        rows.append([k, f(fz.loc["canonical", k]), sci(fz.loc["canonical", f"{k}_ci_low"], fz.loc["canonical", f"{k}_ci_high"]),
                     f(fz.loc["files", k]), sci(fz.loc["files", f"{k}_ci_low"], fz.loc["files", f"{k}_ci_high"])])
    write_table("tab_matching_quality", rows,
                ["Step", "Canonical renaming", "95% CI", "Between files (MS)", "95% CI"],
                "Attribute matching performance on the gold standard", "tab:matching_quality",
                note="distinct pairs of the gold standard; precision, recall and F1: 10,000 bootstrap resamples "
                     "of the pairs; AUC and AP: 2,000 stratified resamples.")
    paper = {"Pairs": ("330", "138"), "TP": ("24", "0"), "FP": ("2", "0"), "FN": ("9", "7"), "TN": ("295", "131"),
             "Precision": ("0.923", "--"), "Recall": ("0.727", "0.000"), "F1": ("0.814", "0.000"),
             "AUC": ("0.955", "0.933"), "AP": ("0.666", "0.356")}
    for r in rows:
        chk.eq(f"matching {r[0]} canonical", str(r[1]), paper[r[0]][0])
        chk.eq(f"matching {r[0]} files", str(r[3]), paper[r[0]][1])
    for lab, exp in (("Precision", "[0.800, 1.000]"), ("Recall", "[0.571, 0.871]"), ("F1", "[0.694, 0.912]"),
                     ("AUC", "[0.925, 0.979]"), ("AP", "[0.520, 0.838]")):
        chk.eq(f"matching CI {lab}", next(r for r in rows if r[0] == lab)[2], r"{\scriptsize " + exp + "}")
    chk.eq("matching CI AUC files", rows[-2][4], r"{\scriptsize [0.876, 0.977]}")
    chk.eq("matching CI AP files", rows[-1][4], r"{\scriptsize [0.234, 0.678]}")


def threshold(chk):
    c = read(FZ, "b4_risultati__curva.csv")
    c = c[c["step"] == "canonical"].sort_values("soglia")
    t = c[c["soglia"].between(84, 92)]
    b = lambda s, v: rf"\textbf{{{v}}}" if s == PLATFORM else v
    rows = [["Precision"] + [b(s, f(v)) for s, v in zip(t.soglia, t.P)],
            ["Recall"] + [b(s, f(v)) for s, v in zip(t.soglia, t.R)],
            ["F1"] + [b(s, f(v)) for s, v in zip(t.soglia, t.F1)]]
    write_table("tab_threshold", rows, ["Threshold"] + [str(s) for s in t.soglia],
                "Sensitivity of the canonical renaming to the similarity threshold.", "tab:threshold",
                note=f"330 distinct pairs; F1 is {f(c[c.soglia == 80].F1.iloc[0])} at 80 and "
                     f"{f(c[c.soglia == 95].F1.iloc[0])} at 95. The platform threshold is in bold.")
    exp_f1 = {84: 0.776, 85: 0.776, 86: 0.812, 87: 0.825, 88: 0.839, 89: 0.833, 90: 0.814, 91: 0.786, 92: 0.717}
    exp_p = {84: 0.765, 86: 0.839, 88: 0.897, 90: 0.923, 92: 0.950}
    for _, r in t.iterrows():
        chk.eq(f"threshold F1 {r.soglia}", rnd(r.F1, 3), exp_f1[int(r.soglia)])
        if int(r.soglia) in exp_p:
            chk.eq(f"threshold P {r.soglia}", rnd(r.P, 3), exp_p[int(r.soglia)])
    chk.eq("F1 at 80", rnd(c[c.soglia == 80].F1.iloc[0], 3), 0.675)
    chk.eq("F1 at 95", rnd(c[c.soglia == 95].F1.iloc[0], 3), 0.455)
    return c


def fig_threshold(c):
    """Same figure as experiments/paper_rev/b2_soglia_grafico.py (09/11/2026)."""
    c = c[c["soglia"].between(80, 95)].sort_values("soglia")
    series = [("P", "Precision", "#2a78d6", "o", "-"), ("R", "Recall", "#eb6834", "s", "--"),
              ("F1", "F1", "#1baf7a", "^", "-.")]
    with plt.rc_context({"font.family": "serif", "font.size": 8, "axes.titlesize": 8, "axes.labelsize": 8,
                         "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7, "pdf.fonttype": 42}):
        fig, ax = plt.subplots(figsize=(119 / 25.4, 2.5))
        x = c["soglia"].to_numpy()
        ax.axvline(PLATFORM, color="#8a8984", lw=0.8, ls=(0, (3, 2)), zorder=1)
        ax.text(PLATFORM + 0.15, 1.015, f"platform threshold ({PLATFORM})", color="#5f5e5a", fontsize=7,
                va="bottom", ha="left")
        for col, lab, colr, mk, ls in series:
            y = c[col].to_numpy()
            ax.plot(x, y, color=colr, lw=1.5, ls=ls, marker=mk, ms=3.5, label=lab, zorder=3)
            ax.annotate(lab, (x[-1], y[-1]), xytext=(5, 0), textcoords="offset points", va="center", ha="left",
                        fontsize=7, color="#333333")
        ax.set_xlim(x.min() - 0.5, x.max() + 0.5)
        ax.set_ylim(0, 1.0)
        ax.set_xticks(x)
        ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
        ax.set_xlabel("Similarity threshold (fuzz.ratio)")
        ax.set_ylabel("Score")
        ax.grid(axis="y", color="#e6e5e0", lw=0.6)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color("#8a8984")
            ax.spines[s].set_linewidth(0.6)
        ax.tick_params(color="#8a8984", width=0.6, length=2.5)
        ax.legend(loc="lower left", frameon=False, ncol=3, handlelength=2.6)
        fig.tight_layout(pad=0.3)
        fig.subplots_adjust(right=0.90)
        save_fig(fig, "b2_threshold_curve", dpi=200)
        plt.close(fig)


# ---------------------------------------------------------------- baselines
def baselines(chk):
    m = read(BL, "b6_baseline__metriche.csv")
    m = m[(m["step"] == "canonical") & m["metodo"].isin(METHODS)].copy()
    m["_ord"] = np.where(m["metodo"] == "fuzzy", 9.0, m["AUC"])
    m = m.sort_values("_ord", ascending=False).reset_index(drop=True)
    sci = lambda lo, hi, sign=False: r"{\scriptsize[" + f(lo, 3, sign) + ", " + f(hi, 3, sign) + "]}"
    rows = []
    for _, r in m.iterrows():
        fzr = r["metodo"] == "fuzzy"
        rows.append([METHODS[r["metodo"]], f(r.AUC), f(r.AP), "--" if fzr else f(r.dAUC_vs_fuzzy, 3, True),
                     f(r.P_cv), f(r.R_cv), f(r.F1_cv)])
        rows.append(["", sci(r.AUC_ci_low, r.AUC_ci_high), sci(r.AP_ci_low, r.AP_ci_high),
                     "" if fzr else sci(r.dAUC_ci_low, r.dAUC_ci_high, True), "", "", ""])
    write_table("tab_baselines", rows, ["Method", "AUC", "AP", r"\(\Delta\)AUC", "P (cv)", "R (cv)", "F1 (cv)"],
                "Fuzzy matching versus schema matching baselines on the canonical renaming", "tab:baselines",
                note="95% bootstrap confidence intervals below the values; P, R and F1 with the threshold selected "
                     "by 5-fold stratified cross-validation repeated 20 times (mean over repetitions).")
    paper = {"Fuzzy (MEDITA)": ("0.955", "0.666", "--", "0.819"), "COMA": ("0.962", "0.712", "+0.008", "0.755"),
             "Jaro-Winkler": ("0.920", "0.571", "$-$0.035", "0.662"), "Embedding": ("0.903", "0.643", "$-$0.052", "0.624"),
             "Cupid (EN WordNet)": ("0.901", "0.525", "$-$0.053", "0.466"),
             "Token-set ratio": ("0.895", "0.409", "$-$0.060", "0.620"),
             "Similarity Flooding": ("0.888", "0.542", "$-$0.066", "0.480"),
             "Cupid (IT WordNet)": ("0.885", "0.487", "$-$0.070", "0.455")}
    chk.eq("baselines order", ",".join(r[0] for r in rows[::2]), ",".join(paper))
    for r in rows[::2]:
        for got, exp, what in zip((r[1], r[2], r[3], r[6]), paper[r[0]], ("AUC", "AP", "dAUC", "F1cv")):
            chk.eq(f"baselines {r[0]} {what}", got, exp)
    chk.eq("baselines COMA dAUC CI", rows[3][3], r"{\scriptsize[$-$0.012, +0.029]}")
    chk.eq("baselines Jaro AP CI", rows[5][2], r"{\scriptsize[0.445, 0.767]}")
    return m


def fig_baselines(m):
    """Same figure as experiments/paper_rev/b6_baseline_grafico.py (09/11/2026)."""
    BLU, INK, MUTED, GRID = "#2a78d6", "#333333", "#8a8984", "#e6e5e0"
    m = m.copy()
    m["label"] = m["metodo"].map(METHODS)
    is_fz = (m["metodo"] == "fuzzy").to_numpy()
    m.loc[is_fz, ["dAUC_vs_fuzzy", "dAUC_ci_low", "dAUC_ci_high"]] = 0.0
    with plt.rc_context({"font.family": "serif", "font.size": 8, "axes.titlesize": 8, "axes.labelsize": 8,
                         "xtick.labelsize": 7, "ytick.labelsize": 7, "pdf.fonttype": 42}):
        fig, (ax1, ax2) = plt.subplots(1, 2, sharey=True, figsize=(119 / 25.4, 2.7),
                                       gridspec_kw={"width_ratios": [1.35, 1], "wspace": 0.14})
        y = np.arange(len(m))[::-1]
        ax1.axvline(0, color=MUTED, lw=0.8, ls=(0, (3, 2)), zorder=1)
        for yi, (_, r), fz in zip(y, m.iterrows(), is_fz):
            if fz:
                ax1.plot(0, yi, marker="D", ms=4.5, color=INK, zorder=3)
                ax1.annotate("reference", (0, yi), xytext=(5, 0), textcoords="offset points", va="center",
                             fontsize=6.5, color=MUTED)
                continue
            lo, hi, d = r["dAUC_ci_low"], r["dAUC_ci_high"], r["dAUC_vs_fuzzy"]
            excl = hi < 0 or lo > 0
            ax1.plot([lo, hi], [yi, yi], color=BLU, lw=1.5, solid_capstyle="round", zorder=2)
            ax1.plot(d, yi, marker="o", ms=4.5, zorder=3, color=BLU, markerfacecolor=BLU if excl else "white",
                     markeredgewidth=1.2)
        ax1.set_xlim(-0.14, 0.05)
        ax1.set_xticks([-0.12, -0.08, -0.04, 0, 0.04])
        ax1.set_xlabel(r"$\Delta$AUC vs fuzzy [95% CI]")
        ax1.set_title("(a) Ranking quality", loc="left")
        for yi, (_, r), fz in zip(y, m.iterrows(), is_fz):
            col = INK if fz else BLU
            ax2.plot([r["F1_cv"] - r["F1_cv_sd"], r["F1_cv"] + r["F1_cv_sd"]], [yi, yi], color=col, lw=1.5,
                     solid_capstyle="round", zorder=2)
            ax2.plot(r["F1_cv"], yi, marker="D" if fz else "o", ms=4.5, color=col, zorder=3)
            ax2.annotate(f"{r['F1_cv']:.3f}", (r["F1_cv"] + r["F1_cv_sd"], yi), xytext=(4, 0),
                         textcoords="offset points", va="center", fontsize=6.5, color=INK)
        ax2.set_xlim(0.4, 0.95)
        ax2.set_xticks([0.4, 0.5, 0.6, 0.7, 0.8, 0.9])
        ax2.set_xlabel("F1 (cross-validated)")
        ax2.set_title("(b) Decision quality", loc="left")
        ax1.set_yticks(y)
        ax1.set_yticklabels(m["label"])
        for t, fz in zip(ax1.get_yticklabels(), is_fz):
            t.set_fontweight("bold" if fz else "normal")
        ax1.set_ylim(-0.6, len(m) - 0.4)
        for ax in (ax1, ax2):
            ax.grid(axis="x", color=GRID, lw=0.6)
            ax.set_axisbelow(True)
            for s in ("top", "right", "left"):
                ax.spines[s].set_visible(False)
            ax.spines["bottom"].set_color(MUTED)
            ax.spines["bottom"].set_linewidth(0.6)
            ax.tick_params(axis="x", color=MUTED, width=0.6, length=2.5)
            ax.tick_params(axis="y", length=0)
        fig.subplots_adjust(left=0.255, right=0.975, top=0.92, bottom=0.16)
        save_fig(fig, "b6_baselines", dpi=200)
        plt.close(fig)


# ---------------------------------------------------------------- ablation
CONFIG_EN = [("no_structure", "w/o structure mapping"), ("no_fuzzy", "w/o fuzzy matching"),
             ("no_dictionary", "w/o vocabulary"), ("no_dictionary_no_fuzzy", "w/o vocabulary and fuzzy"),
             ("no_harmonization", "w/o harmonization"), ("no_numfmt", "w/o number format")]
NOT_APPLIED = {("ISTAT", "no_structure"), ("ISTAT", "no_fuzzy")}  # structure mapping and fuzzy are not ISTAT steps


def human(x, sign=True):
    """+35, +2,608, -135.0 k, +25.3 M (rows of tab:ablation)."""
    if pd.isna(x):
        return "--"
    x = float(x)
    a = abs(x)
    s = "" if x == 0 or not sign else ("+" if x > 0 else "$-$")
    if a >= 1e6:
        return f"{s}{rnd(a / 1e6, 1):.1f} M"
    if a >= 1e4:
        return f"{s}{rnd(a / 1e3, 1):.1f} k"
    return f"{s}{int(a):,}"


def ablation(chk):
    s = read(AB, "b3_sintesi_ablation__sintesi.csv")
    full_ok = read(AB, "b3_sintesi_ablation__controllo_full.csv")
    rows = []
    for src in ("MINIS", "AIFA", "ISTAT"):
        g = s[s["fonte"] == src].set_index("config")
        fu = g.loc["full"]
        rows.append(r"\multicolumn{7}{@{}l}{\textit{" + src + "} (full pipeline: " + f"{int(fu.tabelle)} "
                    + ("table" if int(fu.tabelle) == 1 else "tables") + f", {rnd(fu.righe / 1e6, 1):.1f} M rows)" + r"} \\")
        for cfg, lab in CONFIG_EN:
            r = g.loc[cfg]
            if (src, cfg) in NOT_APPLIED:
                rows.append([lab, r"\multicolumn{6}{c}{no effect (step not applied to ISTAT)}", "", "", "", "", ""])
                continue
            a = r"\(^{a}\)" if int(r.var_code_errore) > 0 else ""
            dv = r["delta_valori_num_%"]
            dvs = ("+" if dv > 0 else "") + f(dv, 1) + (r"\(^{b}\)" if src == "ISTAT" and dv > 0 else "")
            rows.append([lab + a, human(r.delta_righe), "--" if cfg == "no_structure" else human(r.dup_chiave, False),
                         human(r.righe_cod_non_valido, False), int(r.senza_codice_regione), int(r.indicatori_persi), dvs])
        if src != "ISTAT":
            rows.append(r"\midrule")
    write_table("tab_ablation", rows, ["Configuration", r"\(\Delta\)Rows", "Dup. key", "Non-NUTS rows", "No region",
                                       "Ind. lost", r"\(\Delta\)Values (\%)"],
                "Ablation study of the Transform phase: downstream effects when disabling each step, with respect "
                "to the full pipeline", "tab:ablation", colspec="lrrrrrr",
                note=r"\(^{a}\)Two MINIS indicators stop the Transform with an error; deltas on the other 59. "
                     r"\(^{b}\)More values because national, macro-area and provincial records are not discarded.")
    by = {}
    src = None
    for r in rows:
        if isinstance(r, str):
            for k in ("MINIS", "AIFA", "ISTAT"):
                if r"\textit{" + k + "}" in r:
                    src = k
            continue
        by[(src, r[0].replace(r"\(^{a}\)", ""))] = r
    paper = {("MINIS", "w/o fuzzy matching"): ["+2", "716.8 k", "0", 0, 3, "$-$51.0"],
             ("MINIS", "w/o vocabulary"): ["+2,608", "31", "0", 4, 16, "$-$5.2"],
             ("MINIS", "w/o vocabulary and fuzzy"): ["+2,251", "31", "0", 4, 19, "$-$6.6"],
             ("MINIS", "w/o harmonization"): ["$-$135.0 k", "0", "6.9 M", 0, 0, "$-$1.3"],
             ("MINIS", "w/o number format"): ["$-$194.1 k", "0", "0", 0, 0, "$-$67.9"],
             ("MINIS", "w/o structure mapping"): ["+35", "--", "0", 0, 0, "0.0"],
             ("AIFA", "w/o vocabulary"): ["$-$54.5 k", "0", "0", 1, 0, "$-$4.2"],
             ("AIFA", "w/o harmonization"): ["$-$54.5 k", "0", "1.2 M", 0, 0, "$-$4.2"],
             ("ISTAT", "w/o vocabulary"): ["+25.3 M", "0", "0", 17, 0, r"+306.5\(^{b}\)"],
             ("ISTAT", "w/o harmonization"): ["+25.3 M", "2,546", "29.2 M", 0, 0, r"+306.5\(^{b}\)"],
             ("ISTAT", "w/o number format"): ["0", "0", "0", 0, 0, "0.0"]}
    for k, exp in paper.items():
        for got, e, col in zip(by[k][1:], exp, ("rows", "dup", "nonnuts", "noregion", "lost", "values")):
            chk.eq(f"ablation {k[0]} {k[1]} {col}", got, e)
    chk.eq("ablation control: full = production (tables)",
           f"{int(full_ok.righe_uguali.sum())}/{int(full_ok.tabelle.sum())}", "81/81")
    chk.eq("ablation MINIS tables w/o structure", int(s[(s.fonte == "MINIS") & (s.config == "no_structure")].tabelle.iloc[0]), 242)


# ---------------------------------------------------------------- superkey
def secs(x):
    if x < 1:
        return f"{rnd(x, 2):.2f} s"
    if x < 100:
        return f"{rnd(x, 1):.1f} s"
    return f"{rnd(x, 0):.0f} s"


def superkey(chk):
    t = read(SK, "superkey_tests__tempi_sintetici.csv", dtype={"secondi": str})
    t["s"] = pd.to_numeric(t["secondi"].str.replace(">", "", regex=False), errors="coerce")
    t["timeout"] = t["secondi"].str.startswith(">")
    Ns = [1000, 10000, 100000]
    first = t[t.tipo == "chiave_prima"]
    rows = [[r"Key in the first column (any \(n\))", r"\multicolumn{3}{c}{\(\leq\) "
             + f"{rnd(first.s.max() * 1000, 1):.1f} ms" + "}", "", ""]]
    last = t[(t.tipo == "chiave_ultime_2") & (t.n_colonne == 16)].set_index("n_righe")
    rows.append([r"Key in the last two columns, \(n = 16\)"] + [secs(last.loc[n, "s"]) for n in Ns])
    none = t[t.tipo == "nessuna"]
    for n in (10, 12, 14, 16):
        g = none[none.n_colonne == n].set_index("n_righe")
        rows.append([rf"No key, \(n = {n}\)"] + [(r"\(>\) " + g.loc[N, "secondi"].lstrip(">") + " s (time-out)")
                                                 if g.loc[N, "timeout"] else secs(g.loc[N, "s"]) for N in Ns])
    write_table("tab_superkey_times", rows, ["Case", r"\(N = 1{,}000\)", r"\(N = 10{,}000\)", r"\(N = 100{,}000\)"],
                r"Superkey search time on synthetic tables, by number of descriptive columns \(n\), number of rows "
                r"\(N\) and position of the key.", "tab:superkey_times", colspec="lccc",
                note=r"\texttt{find\_super\_key} only (file reading excluded), controlled session.")
    paper = {(16, 1000): 24, (16, 10000): 54, (14, 100000): 104, (12, 100000): 24.5, (10, 100000): 5.1,
             (10, 1000): 0.26, (12, 1000): 1.2, (14, 10000): 11.9}
    for (n, N), exp in paper.items():
        got = none[(none.n_colonne == n) & (none.n_righe == N)].s.iloc[0]
        tol = 0.5 if exp >= 20 and float(exp).is_integer() else 0.5 * 10 ** -(len(str(exp).split(".")[1]) if "." in str(exp) else 0)
        chk.eq(f"superkey no key n={n} N={N}", got, exp, tol)
    chk.eq("superkey key in first column <= 1.5 ms", bool(first.s.max() <= 0.0015), True)
    chk.eq("superkey timeout n=16 N=100k", bool(none[(none.n_colonne == 16) & (none.n_righe == 100000)].timeout.iloc[0]), True)
    for N, exp in zip(Ns, (0.03, 0.06, 0.32)):
        chk.eq(f"superkey last two N={N}", rnd(last.loc[N, "s"], 2), exp)


# ---------------------------------------------------------------- scalability
MODES = [("python", "pandas (Python)"), ("c", "pandas (C)"), ("dask_sync", "Dask (1 thread)"), ("dask", "Dask")]


def scalability(chk):
    s = read(SC, "b5_scalabilita__sintesi.csv")
    p = read(SC, "b5_scalabilita__pulizia.csv")
    s = s[s["fonte"] == "ISTAT"]
    p = p[p["fonte"] == "ISTAT"].set_index("volume_mb_reale")
    rows = []
    for vol, g in s.groupby("volume_mb_reale", sort=True):
        g = g.set_index("modo")
        pipe = dict(MODES)[g["modo_della_pipeline"].iloc[0]]
        clean = f"{rnd(p.loc[vol, 'secondi_pulizia'], 1):,.1f}" if vol in p.index else "--"
        rows.append([f"{rnd(vol, 0):,.0f}"] + [f(g.loc[m, "mediana_s"], 2) for m, _ in MODES] + [pipe, clean])
    full = s[s.volume_mb_reale == s.volume_mb_reale.max()].set_index("modo")
    peaks = "; ".join(f"{lab} {rnd(full.loc[m, 'picco_mb_mediana'], 0):,.0f}" for m, lab in MODES)
    rows.append(r"\midrule")
    rows.append(r"\multicolumn{7}{l}{Peak memory on the whole file (MiB): " + peaks + r"} \\")
    write_table("tab_scalability", rows, ["Volume (MiB)"] + [lab for _, lab in MODES] + ["Pipeline mode", "Cleaning"],
                "Reading and cleaning time (s) on growing prefixes of the ISTAT death file, by reading mode.",
                "tab:scalability", colspec="rrrrrlr",
                note="median of three repetitions, each in a separate process; cleaning measured once per volume. "
                     "The paper table shows the cleaning time for 50, 300, 1,200 MiB and the whole file only.")
    paper = {"50": ["1.03", "0.31", "0.58", "0.57", "pandas (Python)", "42.5"],
             "300": ["7.20", "1.77", "3.34", "2.72", "Dask", "277.0"],
             "1,200": ["33.97", "7.01", "14.02", "11.54", "Dask", "1,203.4"],
             "2,932": ["484.61", "17.46", "34.48", "28.04", "Dask", "3,105.6"],
             "150": ["3.61", "0.89", "1.70", "1.45", "pandas (Python)", None],
             "600": ["15.79", "3.57", "6.93", "5.52", "Dask", None]}
    for r in rows:
        if isinstance(r, str):
            continue
        for got, e, i in zip(r[1:], paper[r[0]], range(6)):
            if e is not None:
                chk.eq(f"scalability {r[0]} col{i}", got, e)
    # paper: 12,086; 3,010; 5,826; 6,370 MiB. pandas (C) is 3,010.5 MiB: half-up rounding gives 3,011,
    # the paper printed 3,010 (round-half-even), hence the tolerance of 0.5 MiB
    for (m_, _), e in zip(MODES, (12086, 3010, 5826, 6370)):
        chk.eq(f"scalability peak {m_}", full.loc[m_, "picco_mb_mediana"], e, 0.5)
    chk.eq("harmonization whole file s", f(p.loc[p.index.max(), "secondi_armonizzazione"], 1), "19.4")


def main():
    chk = Checks("B transform")
    matching_quality(chk)
    c = threshold(chk)
    fig_threshold(c)
    m = baselines(chk)
    fig_baselines(m)
    ablation(chk)
    superkey(chk)
    scalability(chk)
    chk.done()


if __name__ == "__main__":
    main()
