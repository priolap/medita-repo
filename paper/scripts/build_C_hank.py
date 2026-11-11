# -*- coding: utf-8 -*-
"""Experiment C (HANK): tables tab:gemma2_all, tab:hank_comparison, tab:nmiss, tab:abstention and figure
fig:abstention (c12_confusion.pdf).

Input : results/experiments/C_hank_eval/c4_metrics__{per_answer,classic,nmiss,hallucinations,abstention_C12}.csv
        (pipeline/experiments/C_hank_eval/c4_metrics.py, run on Kaggle). The files hold per-question scores
        only: questions, retrieved contexts and answers come from the copyrighted news corpus and are not
        distributed.
Output: tables/tab_gemma2_all, tab_hank_comparison, tab_nmiss, tab_abstention (.csv/.tex);
        figures/c12_confusion.{pdf,png}
The bootstrap intervals of tab:hank_comparison are recomputed here: percentile bootstrap over the 300
questions, stratified by level and paired between models, B = 10,000, seed 20261101.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from exp_common import Checks, f, read, save_fig, write_table

C = "C_hank_eval"
MODELS = {"gemma2": "Gemma-2", "llama3": "Llama-3"}
B, SEED = 10_000, 20261101
CI_METRICS = {"EM": "EM", "ROUGE-1 F1": "ROUGE1_REF_F1", "ROUGE-L F1": "ROUGEL_REF_F1", "BLEU-4": "BLEU",
              "METEOR": "METEOR", "BERTScore F1": "BERT_F1", "Halluc. rate": "IS_HALL"}
# same order and seed as experiments/paper_rev/c11_bootstrap_ci.py (01/11/2026): the metric list of that
# script is replayed so that the random stream is identical
C11_ORDER = {"EM": "EM", "ROUGE-1 F1": "ROUGE1_REF_F1", "ROUGE-2 F1": "ROUGE2_REF_F1", "ROUGE-L F1": "ROUGEL_REF_F1",
             "BLEU-4": "BLEU", "METEOR": "METEOR", "BERTScore F1": "BERT_F1", "Hallucination rate": "IS_HALL"}
NMISS_ROWS = ["BLEU-4", "ROUGE-1 P", "ROUGE-2 P", "ROUGE-L P", "ROUGE-1 F1", "ROUGE-L F1", "ROUGE-1 R", "METEOR"]


def per_model(pa):
    g = pa[pa.MODEL == "gemma2"].set_index("ID").sort_index()
    l = pa[pa.MODEL == "llama3"].set_index("ID").sort_index()
    if not (g.index == l.index).all() or len(g) != 300:
        raise SystemExit("per_answer: the two models must have the same 300 questions")
    return g, l


def gemma2_all(chk, pa, classic, hall):
    g, l = per_model(pa)
    rows = []
    for lab, k in (("ROUGE-1", "ROUGE1"), ("ROUGE-2", "ROUGE2"), ("ROUGE-L", "ROUGEL")):
        rows.append([lab] + [f(d[f"{k}_REF_{x}"].mean()) for d in (g, l) for x in ("PREC", "REC", "F1")])
    rows.append(["BERTScore"] + [f(d[f"BERT_{x}"].mean()) for d in (g, l) for x in ("P", "R", "F1")])
    rows.append(r"\midrule")
    mc = lambda s: r"\multicolumn{3}{c}{" + s + "}"
    for lab, col in (("BLEU-4", "BLEU"), ("METEOR", "METEOR"), ("EM", "EM")):
        rows.append([lab, mc(f(g[col].mean())), "", "", mc(f(l[col].mean())), "", ""])
    h = hall[(hall.SET == "ALL") & (hall.LEVEL == "ALL")].set_index("MODEL")
    hh = {m: mc(f"{int(h.loc[m, 'HALL'])} ({f(h.loc[m, 'HALL_%'], 1)}\\%)") for m in MODELS}
    rows.append(["Hallucinated answers", hh["gemma2"], "", "", hh["llama3"], "", ""])
    write_table("tab_gemma2_all", rows, ["Metric", "P (Gemma-2)", "R (Gemma-2)", "F1 (Gemma-2)", "P (Llama-3)",
                                         "R (Llama-3)", "F1 (Llama-3)"],
                "Performance of Gemma-2 and Llama-3 on the 300-question benchmark.", "tab:gemma2_all",
                note="means over all 300 answers (100 per level).")
    c = classic[(classic.SET == "ALL") & (classic.LEVEL == "ALL")].set_index("MODEL")
    for m, d in (("gemma2", g), ("llama3", l)):
        for col in ("EM", "ROUGE1_REF_F1", "ROUGEL_REF_F1", "BLEU", "METEOR", "BERT_F1"):
            chk.eq(f"{m} {col}: per_answer mean = classic sheet", d[col].mean(), c.loc[m, col], 5e-5)
    paper = {"ROUGE-1": ["0.759", "0.741", "0.732", "0.323", "0.666", "0.383"],
             "ROUGE-2": ["0.688", "0.669", "0.668", "0.235", "0.560", "0.293"],
             # paper: ROUGE-L P of Gemma-2 = 0.733, from the 4-decimal sheet 'classic' (0.7325); the mean of the
             # 300 answers is 0.73249, i.e. 0.732 (double rounding in the paper)
             "ROUGE-L": ["0.732", "0.714", "0.707", "0.287", "0.621", "0.347"],
             "BERTScore": ["0.889", "0.887", "0.887", "0.718", "0.819", "0.762"]}
    for r in rows:
        if not isinstance(r, str) and r[0] in paper:
            for got, e in zip(r[1:], paper[r[0]]):
                chk.eq(f"gemma2_all {r[0]}", got, e)
    for lab, e in (("BLEU-4", ("0.629", "0.185")), ("METEOR", ("0.713", "0.489")), ("EM", ("0.517", "0.010")),
                   ("Hallucinated answers", ("24 (8.0\\%)", "90 (30.0\\%)"))):
        r = next(x for x in rows if not isinstance(x, str) and x[0] == lab)
        chk.eq(f"gemma2_all {lab} Gemma-2", r[1], r"\multicolumn{3}{c}{" + e[0] + "}")
        chk.eq(f"gemma2_all {lab} Llama-3", r[4], r"\multicolumn{3}{c}{" + e[1] + "}")
    lv = hall[(hall.SET == "ALL") & (hall.LEVEL != "ALL")].set_index(["MODEL", "LEVEL"])["HALL_%"]
    chk.eq("hallucinations per level Gemma-2", [int(lv[("gemma2", k)]) for k in ("LOW", "MID", "HIGH")].__str__(), "[9, 9, 6]")
    chk.eq("hallucinations per level Llama-3", [int(lv[("llama3", k)]) for k in ("LOW", "MID", "HIGH")].__str__(), "[28, 31, 31]")


def hank_comparison(chk, pa):
    g, l = per_model(pa)
    lev = g.LEVEL.values
    rng = np.random.default_rng(SEED)
    idx_by = {k: np.where(lev == k)[0] for k in np.unique(lev)}
    boot = np.stack([np.concatenate([rng.choice(v, len(v)) for v in idx_by.values()]) for _ in range(B)])
    res = {}
    for name, col in C11_ORDER.items():
        a = g[col].astype(float).values
        b = l[col].astype(float).values
        ba, bb = a[boot].mean(1), b[boot].mean(1)
        q = lambda x: np.percentile(x, [2.5, 97.5])
        res[col] = dict(g=(a.mean(), *q(ba)), l=(b.mean(), *q(bb)), d=(a.mean() - b.mean(), *q(ba - bb)))
    sci = lambda lo, hi, sign=False: r"{\scriptsize [" + f(lo, 3, sign) + ", " + f(hi, 3, sign) + "]}"
    rows = []
    for key, lab in (("g", "Gemma-2"), ("l", "Llama-3")):
        rows.append([lab] + [f(res[c][key][0]) for c in CI_METRICS.values()])
        rows.append([""] + [sci(*res[c][key][1:]) for c in CI_METRICS.values()])
    rows.append(r"\midrule")
    rows.append(["Difference"] + [f(res[c]["d"][0], 3, True) for c in CI_METRICS.values()])
    rows.append([""] + [sci(*res[c]["d"][1:]) for c in CI_METRICS.values()])
    write_table("tab_hank_comparison", rows, ["Model (RAG)"] + list(CI_METRICS),
                "HANK evaluation: model comparison with 95\\% bootstrap confidence intervals.", "tab:hank_comparison",
                colspec="lccccccc",
                note="300 questions; percentile bootstrap over questions, stratified by level and paired between "
                     "models (10,000 resamples). Identical protocol for both models.")
    paper = {"Gemma-2": "0.517 0.732 0.707 0.629 0.713 0.887 0.080", "Llama-3": "0.010 0.383 0.347 0.185 0.489 0.762 0.300",
             "Difference": "+0.507 +0.349 +0.361 +0.445 +0.224 +0.126 $-$0.220"}
    data = [r for r in rows if not isinstance(r, str)]
    for r in data:
        if r[0] in paper:
            chk.eq(f"hank_comparison {r[0]}", " ".join(r[1:]), paper[r[0]])
    chk.eq("hank_comparison Gemma-2 CI", " ".join(data[1][1:]), " ".join(r"{\scriptsize [" + x + "]}" for x in (
        "0.460, 0.573", "0.693, 0.769", "0.667, 0.747", "0.581, 0.676", "0.672, 0.753", "0.872, 0.902", "0.050, 0.113")))
    chk.eq("hank_comparison Llama-3 CI", " ".join(data[3][1:]), " ".join(r"{\scriptsize [" + x + "]}" for x in (
        "0.000, 0.023", "0.360, 0.407", "0.323, 0.370", "0.166, 0.205", "0.457, 0.521", "0.752, 0.772", "0.247, 0.353")))
    chk.eq("hank_comparison difference CI", " ".join(data[5][1:]), " ".join(r"{\scriptsize [" + x + "]}" for x in (
        "0.450, 0.563", "0.307, 0.389", "0.320, 0.402", "0.399, 0.490", "0.184, 0.264", "0.110, 0.142",
        "$-$0.273, $-$0.167")))


def nmiss(chk, nm):
    n = nm[(nm.SET == "ALL") & (nm.LEVEL == "ALL")].set_index(["METRIC", "MODEL"])
    cell = lambda r: f"{f(r['OUTPERF_%'], 1)} [{f(r.WILSON_LO, 1)}, {f(r.WILSON_HI, 1)}] ({int(r.VALID)})"
    rows = [[m] + [cell(n.loc[(m, mo)]) for mo in MODELS] for m in NMISS_ROWS]
    write_table("tab_nmiss", rows, ["Metric", "Gemma-2", "Llama-3"],
                "NMISS outperformance: percentage of valid cases in which NMISS scores higher than the classical "
                "metric, with 95\\% Wilson intervals.", "tab:nmiss", colspec="lcc",
                note="valid cases (in parentheses) are non-hallucinated answers with a classical score strictly "
                     "between 0.01 and 0.99.")
    paper = {"BLEU-4": ("88.8 [80.5, 93.8] (89)", "29.3 [23.2, 36.3] (184)"),
             "ROUGE-1 P": ("97.2 [92.1, 99.0] (107)", "82.8 [77.0, 87.3] (203)"),
             "ROUGE-2 P": ("92.7 [85.7, 96.4] (96)", "34.0 [27.8, 40.9] (197)"),
             "ROUGE-L P": ("97.2 [92.1, 99.1] (108)", "71.6 [65.0, 77.3] (204)"),
             "ROUGE-1 F1": ("17.5 [11.7, 25.6] (114)", "6.3 [3.7, 10.5] (206)"),
             "ROUGE-L F1": ("24.6 [17.6, 33.2] (114)", "6.3 [3.7, 10.5] (206)"),
             "ROUGE-1 R": ("6.2 [3.1, 12.3] (112)", "1.2 [0.2, 6.4] (85)"),
             "METEOR": ("13.4 [8.3, 20.9] (112)", "1.9 [0.8, 4.9] (206)")}
    # ROUGE-1 R of Gemma-2 is 7/112 = 6.25%: half-up rounding gives 6.3, the paper printed 6.2 (half-even)
    paper["ROUGE-1 R"] = ("6.3 [3.1, 12.3] (112)", paper["ROUGE-1 R"][1])
    for r in rows:
        chk.eq(f"nmiss {r[0]} Gemma-2", r[1], paper[r[0]][0])
        chk.eq(f"nmiss {r[0]} Llama-3", r[2], paper[r[0]][1])


def abstention(chk, ab):
    a = ab[(ab.SET == "ALL") & (ab.ASTENSIONE == "formula presente")]
    tot = a[a.LEVEL == "ALL"].set_index("MODEL")
    rows = [[MODELS[m], int(r.MOD_ABS), int(r.TP), int(r.FP), int(r.FN), int(r.TN), f(r.PRECISION), f(r.RECALL),
             f(r.F1), f(r.ACCURACY)] for m, r in tot.iterrows()]
    rec = a[a.LEVEL != "ALL"].set_index(["MODEL", "LEVEL"]).RECALL
    per_level = "; ".join(f"{MODELS[m]} " + "/".join(f(rec[(m, k)]) for k in ("LOW", "MID", "HIGH")) for m in MODELS)
    write_table("tab_abstention", rows, ["Model", "Abstentions", "TP", "FP", "FN", "TN", "Precision", "Recall", "F1",
                                         "Accuracy"],
                "Abstention analysis: model abstention versus insufficient retrieved context (300 questions, "
                f"{int(tot.GOLD_ABS.iloc[0])} with insufficient context).", "tab:abstention", colspec="lccccccccc",
                note="positive class = abstention. Recall by level (low/mid/high): " + per_level + ".")
    chk.eq("abstention Gemma-2", " ".join(map(str, rows[0][1:])), "160 156 4 24 116 0.975 0.867 0.918 0.907")
    chk.eq("abstention Llama-3", " ".join(map(str, rows[1][1:])), "165 137 28 43 92 0.830 0.761 0.794 0.763")
    chk.eq("abstention recall by level", per_level, "Gemma-2 0.890/0.873/0.827; Llama-3 0.753/0.836/0.692")
    chk.eq("insufficient contexts", int(tot.GOLD_ABS.iloc[0]), 180)
    return tot


def fig_confusion(tot):
    """Same figure as c4_metrics.py (C12)."""
    fig, axes = plt.subplots(1, len(MODELS), figsize=(4.2 * len(MODELS), 3.6))
    for ax, mo in zip(np.atleast_1d(axes), MODELS):
        r = tot.loc[mo]
        mat = np.array([[r.TP, r.FN], [r.FP, r.TN]], dtype=int)
        pct = mat / mat.sum(axis=1, keepdims=True)
        ax.imshow(pct, cmap="Blues", vmin=0, vmax=1)
        for i in range(2):
            for j in range(2):
                ax.text(j, i, f"{mat[i, j]}\n({100 * pct[i, j]:.1f}%)", ha="center", va="center", fontsize=11,
                        color="white" if pct[i, j] > 0.6 else "black")
        ax.set_xticks([0, 1], ["Abstains", "Answers"])
        ax.set_yticks([0, 1], ["Insufficient\ncontext", "Sufficient\ncontext"])
        ax.set_title(MODELS[mo])
    fig.tight_layout()
    save_fig(fig, "c12_confusion")
    plt.close(fig)


def main():
    chk = Checks("C HANK")
    pa = read(C, "c4_metrics__per_answer.csv")
    gemma2_all(chk, pa, read(C, "c4_metrics__classic.csv"), read(C, "c4_metrics__hallucinations.csv"))
    hank_comparison(chk, pa)
    nmiss(chk, read(C, "c4_metrics__nmiss.csv"))
    tot = abstention(chk, read(C, "c4_metrics__abstention_C12.csv"))
    fig_confusion(tot)
    chk.done()


if __name__ == "__main__":
    main()
