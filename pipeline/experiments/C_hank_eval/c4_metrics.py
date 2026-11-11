# -*- coding: utf-8 -*-
"""
C4 - Metriche (task C11) e analisi dell'astensione (task C12) sulle 300 domande, con lo stesso
protocollo del DKE.

Metriche per ogni risposta (Gemma-2 e Llama-3) rispetto alla gold HUMAN:
  - EM: uguaglianza esatta (spazi iniziali/finali esclusi), come 01_get_metrics_RAG.py
  - ROUGE-1/2/L (P, R, F1), METEOR, BLEU-4 e le versioni NMISS: pacchetto RAG/github/nmiss.
    BLEU come nei risultati pubblicati (metrics_ALL.xlsx del DKE, verificato 200/200 coppie):
    f_ref = BLEU con brevity penalty; f_cxt con brevity penalty = 1;
    BLEU-NMISS = max(f_ref, (l1*f_ref + l2*f_cxt) / (l1 + l2)).
    (Con il pacchetto non ancora corretto, la brevity penalty su f_ref viene applicata qui.)
  - BERTScore P/R/F1 (bert-score, lang="it", modello di default, senza rescaling), solo con --bertscore
Statistiche come nel DKE (03_agg_metrics_by_lev_mod.py, 04_get_metrics_hallucinations.py, 06_get_CI_intervals.py):
  - medie delle metriche classiche su tutte le risposte, per modello e livello
  - NMISS solo sui casi validi: IS_HALL = 0 e 0,01 < metrica di riferimento < 0,99;
    outperformance = % di casi validi con NMISS > metrica, con intervallo di Wilson al 95%
C12: matrice di confusione tra astensione del modello (risposta che contiene la formula; variante
"solo formula") e gold di astensione (= contesto insufficiente).

Input : annotation/qa_rag_models_comparison_v3.xlsx (foglio questions), pacchetto nmiss
Output: out/c4_metrics.xlsx

Uso:  python c4_metrics.py [--workbook X] [--nmiss DIR] [--out X] [--bertscore]
"""
import argparse
import json
import math
import platform
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
CFG = json.load(open(HERE / "config_c.json", encoding="utf-8"))
MODELS = list(CFG["generators"].keys())
LEVELS = ["LOW", "MID", "HIGH"]
ABS = CFG["abstention_text"].lower()
TAU_MIN, TAU_MAX = 0.01, 0.99
NMISS_PAIRS = [  # (etichetta, colonna metrica, colonna NMISS)
    ("BLEU-4", "BLEU", "BLEU_NMISS"),
    ("METEOR", "METEOR", "METEOR_NMISS"),
    ("ROUGE-1 P", "ROUGE1_REF_PREC", "ROUGE1_NMISS_PREC"),
    ("ROUGE-1 R", "ROUGE1_REF_REC", "ROUGE1_NMISS_REC"),
    ("ROUGE-1 F1", "ROUGE1_REF_F1", "ROUGE1_NMISS_F1"),
    ("ROUGE-2 P", "ROUGE2_REF_PREC", "ROUGE2_NMISS_PREC"),
    ("ROUGE-2 R", "ROUGE2_REF_REC", "ROUGE2_NMISS_REC"),
    ("ROUGE-2 F1", "ROUGE2_REF_F1", "ROUGE2_NMISS_F1"),
    ("ROUGE-L P", "ROUGEL_REF_PREC", "ROUGEL_NMISS_PREC"),
    ("ROUGE-L R", "ROUGEL_REF_REC", "ROUGEL_NMISS_REC"),
    ("ROUGE-L F1", "ROUGEL_REF_F1", "ROUGEL_NMISS_F1"),
]
CLASSIC = ["EM", "ROUGE1_REF_PREC", "ROUGE1_REF_REC", "ROUGE1_REF_F1", "ROUGE2_REF_PREC",
           "ROUGE2_REF_REC", "ROUGE2_REF_F1", "ROUGEL_REF_PREC", "ROUGEL_REF_REC", "ROUGEL_REF_F1",
           "BLEU", "METEOR", "BERT_P", "BERT_R", "BERT_F1"]


def load_long(workbook):
    df = pd.read_excel(workbook, sheet_name="questions")
    need = ["ID", "LEVEL", "Question", "Context", "HUMAN"] + MODELS + [f"IS_HALL_{m}" for m in MODELS]
    miss = [c for c in need if c not in df.columns]
    if miss:
        sys.exit(f"[STOP] colonne mancanti nel workbook: {miss}")
    if df["HUMAN"].isna().any() or df[[f"IS_HALL_{m}" for m in MODELS]].isna().any().any():
        sys.exit("[STOP] HUMAN o IS_HALL non compilati in tutte le righe")
    df["SET"] = np.where(df["ID"].str[1:].astype(int) <= 100, "paper", "new")
    for c in ["Context", "HUMAN"] + MODELS:
        df[c] = df[c].fillna("").astype(str)
    return df


def lexical(df, nmiss_dir):
    sys.path.insert(0, str(nmiss_dir))
    from modules.scorer import NMISSScorer
    from utils.preprocessing import preprocess_text_bleu
    from modules import bleu as _bleu_mod
    pkg_bp = getattr(_bleu_mod, "BLEU_REF_BREVITY_PENALTY", False)
    m = NMISSScorer(models=MODELS, context_col="Context", ref_col="HUMAN").calculate_metrics_for_all_models(df)
    m = m.drop(columns=["DOMANDA", "CONTEXT", "HUMAN", "SYSTEM"])
    # BLEU come nei risultati pubblicati: brevity penalty solo su f_ref
    sysmap = {(r.ID, mo): r[mo] for _, r in df.iterrows() for mo in MODELS}
    refmap = dict(zip(df["ID"], df["HUMAN"]))
    bleu, bleu_n, bps = [], [], []
    for _, r in m.iterrows():
        c = len(preprocess_text_bleu(sysmap[(r.ID, r.MODEL)]))
        ref = len(preprocess_text_bleu(refmap[r.ID]))
        bp = 1.0 if c > ref else (math.exp(1 - ref / c) if c > 0 else 0.0)
        f_ref = r.BLEU_REF if pkg_bp else r.BLEU_REF * bp
        f_cxt, l1, l2 = r.BLEU_CXT, r.BLEU_LAMBDA1, r.BLEU_LAMBDA2
        bleu.append(f_ref)
        bleu_n.append(max(f_ref, (l1 * f_ref + l2 * f_cxt) / (l1 + l2)) if (l1 + l2) > 0 else f_ref)
        bps.append(bp)
    m["BLEU"], m["BLEU_NMISS"], m["BLEU_BP"] = bleu, bleu_n, bps
    return m


def bertscore(df):
    import bert_score
    pairs = [(r.ID, mo, r[mo], r.HUMAN) for _, r in df.iterrows() for mo in MODELS]
    P, R, F = bert_score.score([p[2] for p in pairs], [p[3] for p in pairs], lang="it",
                               verbose=False, batch_size=32)
    info = {"bert_score": bert_score.__version__, "model": bert_score.utils.lang2model["it"]}
    out = pd.DataFrame({"ID": [p[0] for p in pairs], "MODEL": [p[1] for p in pairs],
                        "BERT_P": P.numpy(), "BERT_R": R.numpy(), "BERT_F1": F.numpy()})
    return out, info


def wilson(k, n, z=1.96):
    if n == 0:
        return (np.nan, np.nan, np.nan)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (100 * p, 100 * (c - h), 100 * (c + h))


def subsets(long):
    for st in ["ALL", "paper", "new"]:
        s1 = long if st == "ALL" else long[long["SET"] == st]
        for lv in ["ALL"] + LEVELS:
            s2 = s1 if lv == "ALL" else s1[s1["LEVEL"] == lv]
            if len(s2):
                yield st, lv, s2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workbook", default=str(HERE / "annotation" / "qa_rag_models_comparison_v3.xlsx"))
    ap.add_argument("--nmiss", default=str(Path(CFG["rag_root"]) / "github" / "nmiss"))
    ap.add_argument("--out", default=str(HERE / "out" / "c4_metrics.xlsx"))
    ap.add_argument("--bertscore", action="store_true")
    a = ap.parse_args()

    df = load_long(a.workbook)
    long = df.melt(id_vars=["ID", "LEVEL", "SET", "HUMAN"], value_vars=MODELS, var_name="MODEL", value_name="SYSTEM")
    hall = df.melt(id_vars=["ID"], value_vars=[f"IS_HALL_{m}" for m in MODELS], var_name="MODEL", value_name="IS_HALL")
    hall["MODEL"] = hall["MODEL"].str.replace("IS_HALL_", "", regex=False)
    long = long.merge(hall, on=["ID", "MODEL"], validate="one_to_one")
    long["IS_HALL"] = long["IS_HALL"].astype(int)
    long["EM"] = (long["SYSTEM"].str.strip() == long["HUMAN"].str.strip()).astype(int)
    long["GOLD_ABS"] = long["HUMAN"].str.lower().str.contains(ABS, regex=False)
    long["MOD_ABS"] = long["SYSTEM"].str.lower().str.contains(ABS, regex=False)
    long["MOD_ABS_ONLY"] = long["SYSTEM"].map(
        lambda s: ABS in s.lower() and len(s.lower().replace(ABS, "").strip(" .\n\"'")) < 5)

    t0 = time.time()
    lex = lexical(df, a.nmiss)
    long = long.merge(lex.drop(columns=["LEVEL"]), on=["ID", "MODEL"], validate="one_to_one")
    env = {"python": platform.python_version(), "pandas": pd.__version__,
           "nltk": __import__("nltk").__version__, "workbook": a.workbook, "nmiss": a.nmiss}
    if a.bertscore:
        bs, info = bertscore(df)
        long = long.merge(bs, on=["ID", "MODEL"], validate="one_to_one")
        env.update(info)
    else:
        for c in ["BERT_P", "BERT_R", "BERT_F1"]:
            long[c] = np.nan
        env["bert_score"] = "non calcolato (manca --bertscore)"
    env["seconds"] = round(time.time() - t0, 1)

    # --- metriche classiche: medie su tutte le risposte
    rows = []
    for st, lv, s in subsets(long):
        for mo in MODELS:
            x = s[s["MODEL"] == mo]
            rows.append({"SET": st, "LEVEL": lv, "MODEL": mo, "N": len(x),
                         **{c: x[c].mean() for c in CLASSIC}})
    classic = pd.DataFrame(rows)

    # --- NMISS sui casi validi, outperformance con Wilson
    rows = []
    for st, lv, s in subsets(long):
        for mo in MODELS:
            x = s[s["MODEL"] == mo]
            for lab, ref, nm in NMISS_PAIRS:
                v = x[(x["IS_HALL"] == 0) & (x[ref] > TAU_MIN) & (x[ref] < TAU_MAX)]
                k = int((v[nm] > v[ref]).sum())
                pct, lo, hi = wilson(k, len(v))
                rows.append({"SET": st, "LEVEL": lv, "MODEL": mo, "METRIC": lab,
                             "NON_HALL": int((x["IS_HALL"] == 0).sum()), "VALID": len(v),
                             "MEAN_METRIC": v[ref].mean() if len(v) else np.nan,
                             "MEAN_NMISS": v[nm].mean() if len(v) else np.nan,
                             "OUTPERF_N": k, "OUTPERF_%": pct, "WILSON_LO": lo, "WILSON_HI": hi})
    nmiss = pd.DataFrame(rows)

    # --- allucinazioni
    rows = []
    for st, lv, s in subsets(long):
        for mo in MODELS:
            x = s[s["MODEL"] == mo]
            rows.append({"SET": st, "LEVEL": lv, "MODEL": mo, "N": len(x),
                         "HALL": int(x["IS_HALL"].sum()), "HALL_%": 100 * x["IS_HALL"].mean()})
    halls = pd.DataFrame(rows)

    # --- C12 astensione
    rows = []
    for st, lv, s in subsets(long):
        for mo in MODELS:
            x = s[s["MODEL"] == mo]
            for defn, col in [("formula presente", "MOD_ABS"), ("solo formula", "MOD_ABS_ONLY")]:
                g, p = x["GOLD_ABS"], x[col]
                tp, fp = int((g & p).sum()), int((~g & p).sum())
                fn, tn = int((g & ~p).sum()), int((~g & ~p).sum())
                prec = tp / (tp + fp) if tp + fp else np.nan
                rec = tp / (tp + fn) if tp + fn else np.nan
                f1 = 2 * prec * rec / (prec + rec) if prec and rec and not np.isnan(prec + rec) else np.nan
                rows.append({"SET": st, "LEVEL": lv, "MODEL": mo, "ASTENSIONE": defn, "N": len(x),
                             "GOLD_ABS": int(g.sum()), "MOD_ABS": int(p.sum()),
                             "TP": tp, "FP": fp, "FN": fn, "TN": tn,
                             "PRECISION": prec, "RECALL": rec, "F1": f1, "ACCURACY": (tp + tn) / len(x),
                             "HALL_SE_RISPONDE_A_GOLD_ABS": int((g & ~p & (x["IS_HALL"] == 1)).sum())})
    absten = pd.DataFrame(rows)

    # --- C12 in forma di matrice di confusione 2x2
    rows = []
    for st, lv, s in subsets(long):
        for mo in MODELS:
            x = s[s["MODEL"] == mo]
            g, p = x["GOLD_ABS"], x["MOD_ABS"]
            for lab, mask in [("contesto insufficiente (gold = astensione)", g), ("contesto sufficiente", ~g)]:
                rows.append({"SET": st, "LEVEL": lv, "MODEL": mo, "CONTESTO": lab,
                             "SI_ASTIENE": int((mask & p).sum()), "RISPONDE": int((mask & ~p).sum()),
                             "TOTALE": int(mask.sum())})
            rows.append({"SET": st, "LEVEL": lv, "MODEL": mo, "CONTESTO": "totale",
                         "SI_ASTIENE": int(p.sum()), "RISPONDE": int((~p).sum()), "TOTALE": len(x)})
    conf = pd.DataFrame(rows)

    readme = pd.DataFrame([
        ("per_answer", "una riga per domanda x modello: tutte le metriche, IS_HALL, astensione"),
        ("classic", "medie su tutte le risposte (EM, ROUGE, BLEU-4 con brevity penalty, METEOR, BERTScore)"),
        ("nmiss", "NMISS solo sui validi: IS_HALL=0 e 0,01 < metrica < 0,99; outperformance % con Wilson 95%"),
        ("hallucinations", "conteggi e % di IS_HALL=1"),
        ("abstention_C12", "astensione del modello vs gold di astensione; due definizioni di astensione"),
        ("confusion_C12", "matrici 2x2: contesto insufficiente/sufficiente x si astiene/risponde; figura c12_confusion"),
        ("SET", "ALL = 300 domande, paper = Q001-Q100, new = Q101-Q300"),
    ], columns=["foglio / voce", "contenuto"])

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        readme.to_excel(w, sheet_name="README", index=False)
        classic.round(4).to_excel(w, sheet_name="classic", index=False)
        nmiss.round(4).to_excel(w, sheet_name="nmiss", index=False)
        halls.round(2).to_excel(w, sheet_name="hallucinations", index=False)
        absten.round(4).to_excel(w, sheet_name="abstention_C12", index=False)
        conf.to_excel(w, sheet_name="confusion_C12", index=False)
        long.drop(columns=["HUMAN", "SYSTEM"]).round(6).to_excel(w, sheet_name="per_answer", index=False)
        pd.DataFrame(list(env.items()), columns=["voce", "valore"]).to_excel(w, sheet_name="env", index=False)
    print(classic[(classic.SET == "ALL") & (classic.LEVEL == "ALL")].round(3).to_string(index=False))
    print(f"Creato: {out}")

    # --- figura C12: matrici di confusione sulle 300 domande
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        names = {"gemma2": "Gemma-2", "llama3": "Llama-3"}
        fig, axes = plt.subplots(1, len(MODELS), figsize=(4.2 * len(MODELS), 3.6))
        for ax, mo in zip(np.atleast_1d(axes), MODELS):
            r = absten[(absten.SET == "ALL") & (absten.LEVEL == "ALL") & (absten.MODEL == mo)
                       & (absten.ASTENSIONE == "formula presente")].iloc[0]
            mat = np.array([[r.TP, r.FN], [r.FP, r.TN]], dtype=int)
            pct = mat / mat.sum(axis=1, keepdims=True)
            ax.imshow(pct, cmap="Blues", vmin=0, vmax=1)
            for i in range(2):
                for j in range(2):
                    ax.text(j, i, f"{mat[i, j]}\n({100 * pct[i, j]:.1f}%)", ha="center", va="center",
                            fontsize=11, color="white" if pct[i, j] > 0.6 else "black")
            ax.set_xticks([0, 1], ["Abstains", "Answers"])
            ax.set_yticks([0, 1], ["Insufficient\ncontext", "Sufficient\ncontext"])
            ax.set_title(names.get(mo, mo))
        fig.tight_layout()
        for ext in ("png", "pdf"):
            fig.savefig(out.with_name(f"c12_confusion.{ext}"), dpi=300)
        print("Creato:", out.with_name("c12_confusion.pdf"))
    except Exception as e:
        print("[figura C12 non creata]", e)


if __name__ == "__main__":
    main()
