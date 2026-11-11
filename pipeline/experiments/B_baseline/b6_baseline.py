# -*- coding: utf-8 -*-
r"""
b6 - Confronto del fuzzy matching di MEDITA con baseline di schema matching sullo stesso gold standard
(tasks_MPP n.8). Conteggi e punteggi, non tempi: puo' girare di giorno.

Gold standard: experiments/B_fuzzy_eval/out/fuzzy_annotato_2026.xlsx (foglio Annotazione, validato).
Unita' di valutazione come b4_stats.py: la coppia distinta (step, item_a, item_b, decision, LABEL); INCERTO escluse.
Step valutati: canonical (colonna -> nome canonico piu' simile) e files (colonna nuova -> colonne del file precedente).
  sheets (foglio -> gruppo di fogli) non e' schema matching tra colonne: escluso (vedi README del risultato).

Metodi: ogni metodo assegna un punteggio di similarita' a ciascuna coppia del gold standard (stesse coppie per tutti).
  fuzzy         fuzz.ratio della pipeline (colonna ratio del log, riferimento)
  embedding     sentence-transformers, coseno tra i nomi (underscore -> spazio, minuscolo); modello multilingue
  coma          Valentine COMA (Python, solo schema), selezione disattivata (delta=0): similarita' per ogni coppia
  cupid         Valentine Cupid, th_accept=0: similarita' per ogni coppia, configurazione standard (WordNet inglese)
  cupid_ita     come cupid, ma con il WordNet italiano dell'Open Multilingual Wordnet di NLTK (lang='ita',
                MultiWordNet) e le stopword italiane; ricerca dei lemmi insensibile agli accenti (QUANTITA -> quantita').
                Il pacchetto Valentine non viene modificato: le tre funzioni linguistiche di Cupid sono sostituite
                solo dentro questo processo. Nessuna lemmatizzazione italiana (plurali come 'utenti' non trovati:
                Cupid passa alla distanza di Levenshtein, come fa con le parole assenti da WordNet)
  sflooding     Valentine Similarity Flooding
  jaro_winkler  variante lessicale (rapidfuzz), contesto
  token_set     variante lessicale insensibile all'ordine delle parole (rapidfuzz), contesto
  Valentine lavora su due schemi: canonical = tutte le colonne valutate x vocabolario canonico (cols_attributes.json,
  name_out); files = per VAR_CODE, colonne nuove x colonne del file precedente. Solo i nomi: i valori non sono usati
  (tabelle di una riga vuota, stesso tipo per tutte le colonne). Coppia non restituita dal matcher = 0.

Metriche (per step e metodo):
  AUC e AP senza soglia, con intervallo bootstrap al 95% (ricampionamento stratificato delle coppie);
  differenza di AUC rispetto al fuzzy con intervallo bootstrap appaiato;
  P/R/F1 con soglia scelta in cross-validation (RepeatedStratifiedKFold: sulla parte di addestramento la soglia che
  massimizza F1, applicata alla parte di test; media e deviazione standard sulle ripetizioni). La rinomina resta
  bloccata dove la pipeline l'ha bloccata per un altro motivo (nome gia' nella tabella), come in b4_stats.py.
  In piu' il fuzzy alla soglia della piattaforma (decisione reale del log), da confrontare con b2.

Scrive solo experiments/B_baseline/out/b6_baseline_<data_ora>.xlsx
(README, ambiente, coppie, punteggi, metriche, cv_soglie, controllo_b2, errori).

Uso (da MEDITA):
  python experiments/B_baseline/b6_baseline.py
Opzioni: --gold <xlsx>  --metodi fuzzy,embedding,coma,cupid,cupid_ita,sflooding,jaro_winkler,token_set
         --modello paraphrase-multilingual-MiniLM-L12-v2  --bootstrap 2000  --ripetizioni-cv 20  --seed 0
Al primo uso il modello di embedding (Hugging Face) e i dati NLTK (WordNet, omw per l'italiano, stopword) si
scaricano: serve la rete. Foglio copertura_wordnet: quante parole dei nomi di colonna sono in WordNet inglese / italiano.
"""
import argparse
import contextlib
import functools
import os
import platform
import sys
import time
import traceback
import unicodedata
import warnings

HOME = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")).replace("\\", "/") + "/"
sys.path.insert(0, HOME)
warnings.filterwarnings("ignore", category=SyntaxWarning)

import numpy as np
import pandas as pd

GOLD = f"{HOME}experiments/B_fuzzy_eval/out/fuzzy_annotato_2026.xlsx"
OUT_DIR = f"{HOME}experiments/B_baseline/out/"
STEPS = ("canonical", "files")
# come b4_stats.py
BLOCKED = {"not_renamed_suffix", "not_renamed_target_already_in_table", "above_threshold_not_in_dictionary",
           "target_already_in_table", "above_threshold_in_dictionary"}
POSITIVE_DEC = {"renamed", "joined"}
ALL_METHODS = ["fuzzy", "embedding", "coma", "cupid", "cupid_ita", "sflooding", "jaro_winkler", "token_set"]
DEF_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def norm(s):
    return " ".join(str(s).replace("_", " ").split()).lower()


# ------------------------------------------------------------------------------------------- gold standard
def load_gold(path):
    a = pd.read_excel(path, sheet_name="Annotazione", dtype=str).fillna("")
    a["LABEL"] = a["LABEL"].str.strip().str.upper()
    tot = a.groupby(["step", "LABEL"]).size().rename("righe").reset_index()
    a = a[a["step"].isin(STEPS) & a["LABEL"].isin(["MATCH", "NON_MATCH"])].copy()
    a["y"] = (a["LABEL"] == "MATCH").astype(int)
    key = ["step", "item_a", "item_b", "decision", "y"]
    g = (a.groupby(key, sort=False)
         .agg(ratio=("ratio", "first"), occorrenze=("ratio", "size"),
              var_codes=("var_code", lambda s: "; ".join(sorted(set(s)))),
              fonti=("source", lambda s: "; ".join(sorted(set(s)))))
         .reset_index())
    g["ratio"] = g["ratio"].astype(float)
    g["bloccata"] = g["decision"].isin(BLOCKED).astype(int)
    g["pred_piattaforma"] = g["decision"].isin(POSITIVE_DEC).astype(int)
    return g, a, tot


# ------------------------------------------------------------------------------------------- metodi
def score_lexical(g, kind):
    from rapidfuzz import fuzz
    from rapidfuzz.distance import JaroWinkler
    if kind == "jaro_winkler":
        return np.array([100 * JaroWinkler.normalized_similarity(a, b) for a, b in zip(g.item_a, g.item_b)])
    return np.array([fuzz.token_set_ratio(norm(a), norm(b)) for a, b in zip(g.item_a, g.item_b)])


def score_embedding(g, model_name):
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(model_name)
    names = sorted(set(g.item_a) | set(g.item_b))
    emb = model.encode([norm(n) for n in names], normalize_embeddings=True, batch_size=64, show_progress_bar=False)
    idx = {n: i for i, n in enumerate(names)}
    return np.array([float(np.dot(emb[idx[a]], emb[idx[b]])) for a, b in zip(g.item_a, g.item_b)])


def _matcher(kind):
    from valentine.algorithms import Coma, Cupid, SimilarityFlooding
    if kind == "coma":
        return Coma(use_schema=True, use_instances=False, delta=0.0, threshold=0.0, max_n=0)
    if kind in ("cupid", "cupid_ita"):
        return Cupid(th_accept=0.0)
    if kind == "sflooding":
        return SimilarityFlooding()
    raise ValueError(kind)


def _senza_accenti(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _wordnet_ita():
    """Lemmi e stopword italiane di NLTK (scaricati se mancano)."""
    import nltk
    from nltk.corpus import wordnet as wn, stopwords
    try:
        wn.synsets("casa", lang="ita")
    except LookupError:
        for r in ("wordnet", "omw-1.4", "omw-2.0"):
            nltk.download(r, quiet=True)
    try:
        stop = frozenset(stopwords.words("italian"))
    except LookupError:
        nltk.download("stopwords", quiet=True)
        stop = frozenset(stopwords.words("italian"))
    lemmi = {}
    for l in wn.all_lemma_names(lang="ita"):
        lemmi.setdefault(_senza_accenti(l.lower()), l)
    return wn, lemmi, stop


@contextlib.contextmanager
def cupid_italiano():
    """Cupid con WordNet italiano: sostituisce 3 funzioni di valentine.algorithms.cupid.linguistic_matching
    solo in questo processo (stopword, insieme dei lemmi, synset) e svuota le cache prima e dopo."""
    from valentine.algorithms.cupid import linguistic_matching as lm
    wn, lemmi, stop = _wordnet_ita()
    names = ("_english_stopwords", "_wordnet_lemma_names", "_cached_synsets")
    saved = {k: getattr(lm, k) for k in names}

    @functools.cache
    def synsets_ita(word):
        return tuple(wn.synsets(lemmi.get(word, word), lang="ita"))

    def pulisci():
        for f in ("_token_similarity_cached", "_wup_similarity_cached"):
            if hasattr(getattr(lm, f, None), "cache_clear"):
                getattr(lm, f).cache_clear()

    lm._english_stopwords = lambda: stop
    lm._wordnet_lemma_names = lambda: frozenset(lemmi)
    lm._cached_synsets = synsets_ita
    pulisci()
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(lm, k, v)
        pulisci()


def copertura_wordnet(g):
    """Parole dei nomi di colonna (separate da '_') presenti in WordNet inglese e italiano."""
    rows = []
    try:
        from nltk.corpus import wordnet as wn
        wn_, lemmi, _ = _wordnet_ita()
        eng = set(wn.all_lemma_names())
        for step in STEPS:
            d = g[g.step == step]
            parole = sorted({w for n in set(d.item_a) | set(d.item_b) for w in str(n).lower().split("_")
                             if w.isalpha() and len(w) > 1})
            in_eng = sum(w in eng for w in parole)
            in_ita = sum(_senza_accenti(w) in lemmi for w in parole)
            rows.append(dict(step=step, parole_distinte=len(parole), in_wordnet_inglese=in_eng,
                             quota_inglese=round(in_eng / len(parole), 3) if parole else None,
                             in_wordnet_italiano=in_ita, quota_italiano=round(in_ita / len(parole), 3) if parole else None,
                             assenti_in_entrambi="; ".join(w for w in parole
                                                          if w not in eng and _senza_accenti(w) not in lemmi)[:2000]))
    except Exception as e:
        rows.append(dict(step="errore", assenti_in_entrambi=repr(e)[:300]))
    return pd.DataFrame(rows)


def _schema_df(cols):
    return pd.DataFrame({c: [""] for c in cols}, dtype=object)


def _run_valentine(kind, src_cols, tgt_cols):
    from valentine import valentine_match
    res = valentine_match([_schema_df(src_cols), _schema_df(tgt_cols)], _matcher(kind), df_names=["source", "target"])
    out = {}
    for k, v in res.items():
        if hasattr(k, "source_column"):
            s, t = k.source_column, k.target_column
            if getattr(k, "source_table", "source") != "source":   # coppia restituita nell'altro verso
                s, t = t, s
        else:
            (ts, s), (tt, t) = k
            if ts != "source":
                s, t = t, s
        out[(s, t)] = max(float(v), out.get((s, t), 0.0))
    return out


def score_valentine(g, kind, canon):
    sc = np.zeros(len(g))
    info = []
    c = g[g.step == "canonical"]
    if len(c):
        src = sorted(set(c.item_a))
        tgt = sorted(set(canon) | set(c.item_b))
        t0 = time.time()
        m = _run_valentine(kind, src, tgt)
        info.append(dict(metodo=kind, step="canonical", contesto="tutte le colonne valutate x vocabolario canonico",
                         colonne_sorgente=len(src), colonne_destinazione=len(tgt), coppie_restituite=len(m),
                         secondi=round(time.time() - t0, 1)))
        for i in c.index:
            sc[g.index.get_loc(i)] = m.get((g.at[i, "item_a"], g.at[i, "item_b"]), 0.0)
    f = g[g.step == "files"]
    if len(f):
        rows = f.assign(vc=f.var_codes.str.split("; ")).explode("vc")
        t0, nret = time.time(), 0
        for vc, sub in rows.groupby("vc"):
            src, tgt = sorted(set(sub.item_a)), sorted(set(sub.item_b))
            m = _run_valentine(kind, src, tgt)
            nret += len(m)
            for i in sub.index.unique():
                pos = g.index.get_loc(i)
                sc[pos] = max(sc[pos], m.get((g.at[i, "item_a"], g.at[i, "item_b"]), 0.0))
        info.append(dict(metodo=kind, step="files", contesto="per VAR_CODE: colonne nuove x colonne del file precedente",
                         colonne_sorgente=None, colonne_destinazione=None, coppie_restituite=nret,
                         secondi=round(time.time() - t0, 1)))
    return sc, info


# ------------------------------------------------------------------------------------------- metriche
def auc_ap(y, s):
    from sklearn.metrics import roc_auc_score, average_precision_score
    if y.min() == y.max():
        return np.nan, np.nan
    return roc_auc_score(y, s), average_precision_score(y, s)


def strat_idx(y, rng):
    pos, neg = np.where(y == 1)[0], np.where(y == 0)[0]
    return np.concatenate([rng.choice(pos, len(pos)), rng.choice(neg, len(neg))])


def prf(y, pred):
    tp = int(((pred == 1) & (y == 1)).sum()); fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    p = tp / (tp + fp) if tp + fp else np.nan
    r = tp / (tp + fn) if tp + fn else np.nan
    f1 = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
    return tp, fp, fn, p, r, f1


def best_threshold(y, s, blocked):
    best_t, best_f = None, -1.0
    for t in np.unique(s):
        f1 = prf(y, ((s >= t) & (blocked == 0)).astype(int))[5]
        if f1 > best_f:
            best_t, best_f = t, f1
    return best_t


def cv_metrics(y, s, blocked, reps, seed):
    from sklearn.model_selection import RepeatedStratifiedKFold
    k = int(min(5, y.sum(), (1 - y).sum()))
    if k < 2:
        return None, []
    rskf = RepeatedStratifiedKFold(n_splits=k, n_repeats=reps, random_state=seed)
    per_rep, thr = {}, []
    for j, (tr, te) in enumerate(rskf.split(s.reshape(-1, 1), y)):
        t = best_threshold(y[tr], s[tr], blocked[tr])
        thr.append(t)
        pred = ((s[te] >= t) & (blocked[te] == 0)).astype(int)
        tp, fp, fn = prf(y[te], pred)[:3]
        acc = per_rep.setdefault(j // k, [0, 0, 0])
        acc[0] += tp; acc[1] += fp; acc[2] += fn
    P, R, F = [], [], []
    for tp, fp, fn in per_rep.values():
        P.append(tp / (tp + fp) if tp + fp else np.nan)
        R.append(tp / (tp + fn) if tp + fn else np.nan)
        F.append(2 * tp / (2 * tp + fp + fn) if tp else 0.0)
    return dict(folds=k, P_cv=np.nanmean(P), P_cv_sd=np.nanstd(P), R_cv=np.nanmean(R), R_cv_sd=np.nanstd(R),
                F1_cv=np.nanmean(F), F1_cv_sd=np.nanstd(F), soglia_cv_mediana=float(np.median(thr)),
                soglia_cv_min=float(np.min(thr)), soglia_cv_max=float(np.max(thr))), thr


def metrics(g, scores, methods, B, reps, seed):
    rows, thr_rows = [], []
    for step in STEPS:
        m = (g.step == step).values
        if not m.any():
            continue
        y, bl = g.y.values[m], g.bloccata.values[m]
        rng = np.random.default_rng(seed)
        boots = [strat_idx(y, rng) for _ in range(B)]
        fz = scores["fuzzy"][m] if "fuzzy" in scores else None
        for meth in methods:
            if meth not in scores:
                continue
            s = scores[meth][m]
            auc, ap = auc_ap(y, s)
            ba = np.array([auc_ap(y[i], s[i]) for i in boots])
            r = dict(step=step, metodo=meth, coppie=int(m.sum()), positivi=int(y.sum()),
                     AUC=auc, AUC_ci_low=np.nanpercentile(ba[:, 0], 2.5), AUC_ci_high=np.nanpercentile(ba[:, 0], 97.5),
                     AP=ap, AP_ci_low=np.nanpercentile(ba[:, 1], 2.5), AP_ci_high=np.nanpercentile(ba[:, 1], 97.5))
            if fz is not None and meth != "fuzzy":
                d = np.array([auc_ap(y[i], s[i])[0] - auc_ap(y[i], fz[i])[0] for i in boots])
                r.update(dAUC_vs_fuzzy=auc - auc_ap(y, fz)[0], dAUC_ci_low=np.nanpercentile(d, 2.5),
                         dAUC_ci_high=np.nanpercentile(d, 97.5))
            cv, thr = cv_metrics(y, s, bl, reps, seed)
            if cv:
                r.update(cv)
                thr_rows += [dict(step=step, metodo=meth, fold=i + 1, soglia=t) for i, t in enumerate(thr)]
            rows.append(r)
    return pd.DataFrame(rows), pd.DataFrame(thr_rows)


def controllo_b2(g):
    out = []
    for step in STEPS:
        d = g[g.step == step]
        if not len(d):
            continue
        tp, fp, fn, p, r, f1 = prf(d.y.values, d.pred_piattaforma.values)
        auc, ap = auc_ap(d.y.values, d.ratio.values)
        out.append(dict(step=step, coppie=len(d), TP=tp, FP=fp, FN=fn, TN=int(len(d) - tp - fp - fn), P=p, R=r, F1=f1,
                        AUC=auc, AP=ap, nota="fuzzy alla soglia della piattaforma: deve coincidere con b4_risultati.xlsx"))
    return pd.DataFrame(out)


# ------------------------------------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--gold", default=GOLD)
    p.add_argument("--metodi", default=",".join(ALL_METHODS))
    p.add_argument("--modello", default=DEF_MODEL)
    p.add_argument("--bootstrap", type=int, default=2000)
    p.add_argument("--ripetizioni-cv", type=int, default=20)
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args()
    methods = [m for m in a.metodi.split(",") if m]
    bad = [m for m in methods if m not in ALL_METHODS]
    if bad:
        sys.exit(f"Metodi sconosciuti: {bad}. Disponibili: {ALL_METHODS}")
    if "fuzzy" not in methods:
        methods.insert(0, "fuzzy")
    t_start = time.time()

    g, ann, tot = load_gold(a.gold)
    from scripts.modules.utils import json_handler as jh
    col_map = jh.JsonHandler(file_tgt=f"{HOME}config/cols_attributes.json", encoding="ISO-8859-1").json_reader()
    canon = list(dict.fromkeys(col_map["name_out"]))
    print(f"Gold standard: {len(g)} coppie distinte ({', '.join(f'{s} {int((g.step == s).sum())}' for s in STEPS)}); "
          f"vocabolario canonico {len(canon)} nomi")

    scores, info, err = {"fuzzy": g.ratio.values}, [], []
    for meth in methods[1:]:
        t0 = time.time()
        try:
            if meth in ("jaro_winkler", "token_set"):
                scores[meth] = score_lexical(g, meth)
            elif meth == "embedding":
                scores[meth] = score_embedding(g, a.modello)
            elif meth == "cupid_ita":
                with cupid_italiano():
                    scores[meth], inf = score_valentine(g, meth, canon)
                info += inf
            else:
                scores[meth], inf = score_valentine(g, meth, canon)
                info += inf
            print(f"  {meth}: ok ({time.time() - t0:.1f}s)", flush=True)
        except Exception as e:
            err.append(dict(metodo=meth, errore=repr(e)[:500], dove=traceback.format_exc().strip().splitlines()[-3][:300]))
            print(f"  {meth}: ERRORE {e!r}"[:300], flush=True)

    met, thr = metrics(g, scores, methods, a.bootstrap, a.ripetizioni_cv, a.seed)
    pun = g[["step", "item_a", "item_b", "y", "decision", "bloccata", "pred_piattaforma", "occorrenze", "var_codes",
             "fonti"]].copy()
    pun.insert(3, "LABEL", np.where(pun["y"] == 1, "MATCH", "NON_MATCH"))
    for meth, s in scores.items():
        pun[meth] = s
        pun[f"rango_{meth}"] = pun.groupby("step")[meth].rank(ascending=False, method="min")

    amb = dict(eseguito=time.strftime("%Y-%m-%d %H:%M"), durata_s=round(time.time() - t_start), python=platform.python_version(),
               gold=a.gold, metodi=", ".join(methods), modello_embedding=a.modello if "embedding" in methods else "",
               bootstrap=a.bootstrap, ripetizioni_cv=a.ripetizioni_cv, seed=a.seed, vocabolario_canonico=len(canon))
    for mod in ("pandas", "sklearn", "rapidfuzz", "valentine", "sentence_transformers", "torch"):
        try:
            amb[mod] = __import__(mod).__version__
        except Exception:
            amb[mod] = "non disponibile"
    readme = pd.DataFrame({"voce": ["esperimento", "unita'", "step", "metodi", "valentine", "metriche", "nota"], "valore": [
        "b6 - fuzzy matching di MEDITA contro baseline di schema matching sullo stesso gold standard (tasks_MPP n.8)",
        "coppia distinta (step, item_a, item_b, decision, LABEL) come b4_stats.py; INCERTO escluse",
        "canonical e files; sheets escluso: e' il raggruppamento di fogli dello stesso file, non schema matching tra colonne",
        "fuzzy = fuzz.ratio della pipeline; embedding = coseno tra i nomi; coma/cupid/sflooding = Valentine; "
        "cupid = WordNet inglese (standard), cupid_ita = WordNet italiano OMW (lang='ita') e stopword italiane; "
        "jaro_winkler e token_set = varianti lessicali di contesto",
        "solo nomi (nessun valore). canonical: colonne valutate x vocabolario canonico; files: per VAR_CODE. "
        "COMA delta=0 e Cupid th_accept=0 restituiscono la similarita' di ogni coppia; coppia non restituita = 0",
        "AUC/AP senza soglia con IC bootstrap 95%; dAUC_vs_fuzzy con IC bootstrap appaiato; P/R/F1 con soglia in "
        "cross-validation (media e sd sulle ripetizioni); rinomine bloccate dalla pipeline restano bloccate",
        "le coppie sono quelle su cui la pipeline ha chiamato il fuzzy (candidato migliore per canonical): il confronto "
        "valuta i punteggi sulle stesse coppie, non la ricerca del candidato"]})
    os.makedirs(OUT_DIR, exist_ok=True)
    out = f"{OUT_DIR}b6_baseline_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        readme.to_excel(w, sheet_name="README", index=False)
        pd.DataFrame(list(amb.items()), columns=["voce", "valore"]).to_excel(w, sheet_name="ambiente", index=False)
        tot.to_excel(w, sheet_name="coppie", index=False)
        pun.to_excel(w, sheet_name="punteggi", index=False)
        met.round(4).to_excel(w, sheet_name="metriche", index=False)
        pd.DataFrame(info).to_excel(w, sheet_name="valentine", index=False)
        thr.to_excel(w, sheet_name="cv_soglie", index=False)
        controllo_b2(g).round(4).to_excel(w, sheet_name="controllo_b2", index=False)
        if any(m in methods for m in ("cupid", "cupid_ita")):
            copertura_wordnet(g).to_excel(w, sheet_name="copertura_wordnet", index=False)
        pd.DataFrame(err, columns=["metodo", "errore", "dove"]).to_excel(w, sheet_name="errori", index=False)
    print(f"\nRisultati: {out}\nDurata: {time.time() - t_start:.0f}s")


if __name__ == "__main__":
    main()
