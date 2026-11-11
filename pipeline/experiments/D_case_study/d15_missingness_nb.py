# -*- coding: utf-8 -*-
# Versione script di d15_missingness.ipynb (stesse celle, generata automaticamente).
# Uso (dalla cartella MEDITA):  python experiments\D_case_study\d15_missingness_nb.py
import os as _os, sys as _sys
_os.chdir(_os.path.dirname(_os.path.abspath(__file__)))   # come il notebook: cartella experiments/D_case_study
try:
    _sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import pandas as _pd
def _show(x):
    if x is None:
        return
    print(x.to_string() if isinstance(x, (_pd.DataFrame, _pd.Series)) else x)
    print()


# ====================================================================================================
# # D15 – Missingness: pattern per dominio, regione e anno e impatto sulla comparabilità tra regioni
# 
# **Snapshot del paper:** AIFA e MINIS 20261025, ISTAT 20261027 (tabelle armonizzate `data/output/<FONTE>/<snapshot>/`).
# Analisi descrittiva più un test di permutazione. Il notebook legge solo file di MEDITA e scrive in `out/`.
# 
# **Universo.** Si analizzano le *tabelle statistiche*: hanno `CODICE_REGIONE`, `ANNO` e almeno una misura numerica
# (ISTAT: `OBS_VALUE`; AIFA e MINIS: colonne numeriche osservate del dizionario `config/cols_attributes.json`).
# Le altre (anagrafiche senza territorio, elenchi senza anno o senza misure) sono elencate con il motivo.
# 
# **Unità e periodo.** 21 unità di rilevazione (19 regioni + Bolzano `ITH1` e Trento `ITH2`); per una tabella, tutti gli
# anni dal primo all'ultimo pubblicato. Per la comparabilità tra regioni si usano le 20 regioni: il Trentino-Alto Adige è
# `ITH0` se la tabella lo contiene, altrimenti Bolzano e Trento insieme.
# 
# **Tipi di mancanza, per cella (tabella, unità, anno):**
# 
# | Tipo | Definizione |
# |---|---|
# | anno non pubblicato | nessuna unità ha righe in quell'anno (buco nell'intervallo della tabella) |
# | regione assente | l'anno è pubblicato, ma non per quell'unità |
# | valori mancanti | righe presenti, ma con almeno una misura vuota o non numerica, tra le misure pubblicate nell'anno |
# | (misura non pubblicata) | misura vuota per tutte le unità in un anno (cambio di schema della fonte): non è contata, è elencata a parte |
# | convenzione di formato (AIFA) | misura vuota in AIFA: la fonte scrive `0` nel 2018 e lascia vuoto dal 2019 (verificato sui grezzi); non è contata come mancante |
# | completa | righe presenti e tutte le misure valorizzate |
# 
# Le regioni assenti sono contate come *assenti nella fonte*, senza distinguere tra dato non trasmesso e fenomeno
# inesistente (vedi Limiti).
# 
# **Comparabilità.** Una tabella-anno pubblicata è *confrontabile* se tutte le 20 regioni hanno la cella completa.
# 
# **Test di permutazione.** H0: in ogni tabella-anno le regioni incomplete sono un sottoinsieme casuale (della stessa
# numerosità) delle 20 regioni. Statistica: varianza tra regioni del numero di tabelle-anno in cui la regione è incompleta.
# Le permutazioni rimescolano le regioni *dentro* ogni tabella-anno, quindi conservano quante regioni mancano in ciascuna.
# ====================================================================================================
# ---- cella 1
import json, re, time, platform
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path.cwd()                              # experiments/D_case_study
HOME = HERE.parents[1]                         # MEDITA
OUT = HERE / "out"; OUT.mkdir(exist_ok=True)
STAMP = time.strftime("%Y%m%d_%H%M%S")
SNAP = {"AIFA": "20261025", "MINIS": "20261025", "ISTAT": "20261027"}
HRM = {s: HOME / "data" / "output" / s / SNAP[s] for s in SNAP}
CHUNK = 500_000
N_PERM, SEED = 10_000, 20261031
pd.set_option("display.width", 200, "display.max_columns", 30, "display.max_colwidth", 70)

CMAP = json.loads((HOME / "config" / "codregione_map.json").read_text(encoding="utf-8"))
NAME = {k: v["REGIONE"] for k, v in CMAP.items()}
U21 = sorted(k for k in CMAP if k != "ITH0")
R20 = sorted(k for k in CMAP if k not in ("ITH1", "ITH2"))
CODES22 = set(U21) | {"ITH0"}
ATTR = json.loads((HOME / "config" / "cols_attributes.json").read_text(encoding="utf-8"))
NUM_OBS = {a["name_out"] for a in ATTR if a.get("dtype") == "numeric" and a.get("is_obs")}

def label_en(u):
    """Nome della regione per le figure (nomi propri in italiano)."""
    special = {"ITH1": "P.A. Bolzano", "ITH2": "P.A. Trento", "ITH0": "Trentino-Alto Adige", "ITC2": "Valle d'Aosta",
               "ITH4": "Friuli-Venezia Giulia", "ITH5": "Emilia-Romagna"}
    return special.get(u, NAME[u].title())
DOM_EN = {"Salute e Mortalità": "Health & mortality", "Previdenza Sociale": "Social security",
          "Indicatori Sociodemografici": "Socio-demographic", "Educazione e Disabilità": "Education & disability",
          "Violenza": "Violence", "Dati Ospedalieri": "Hospital data", "Salute Mentale": "Mental health",
          "Personale del SSN": "NHS staff", "Dispositivi Medici": "Medical devices",
          "Sistema Sanitario Nazionale": "National health service", "Farmaceutica": "Pharmaceutical",
          "Farmaci": "Medicines", "Logistica": "Logistics", "Importazioni Alimentari": "Food imports"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
SRC_COL = {"AIFA": "#2a78d6", "MINIS": "#eb6834", "ISTAT": "#1baf7a"}     # palette validata (dataviz)
SRC_MRK = {"AIFA": "o", "MINIS": "s", "ISTAT": "^"}
plt.rcParams.update({"font.size": 8, "axes.titlesize": 9, "axes.labelsize": 8, "xtick.labelsize": 7,
                     "ytick.labelsize": 7, "legend.fontsize": 7, "axes.edgecolor": INK2, "axes.labelcolor": INK,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
                     "pdf.fonttype": 42, "savefig.bbox": "tight"})
FIGS, CTRL = [], []
def savefig(fig, name):
    for ext in ("pdf", "png"):
        fig.savefig(OUT / f"{name}_{STAMP}.{ext}", dpi=300)
    FIGS.append(name); plt.close(fig)
def ctrl(voce, valore, esito=""):
    CTRL.append({"voce": voce, "valore": str(valore), "esito": esito}); print(f"{voce}: {valore} {esito}")
print("MEDITA:", HOME); print("snapshot:", SNAP)


# ====================================================================================================
# ## 1. Universo delle tabelle e lettura
# 
# Per ogni tabella si legge prima la sola intestazione; le tabelle statistiche si leggono a blocchi, solo nelle colonne
# `CODICE_REGIONE`, `ANNO`, misure (e `OBS_STATUS` per ISTAT).
# ====================================================================================================
# ---- cella 3
def catalog(src):
    info = json.loads((HOME / "config" / f"info_{src}.json").read_text(encoding="utf-8"))
    cat = {}
    for x in info:
        fo = x.get("file_out")
        if fo:
            v = cat.setdefault(fo, {"VAR_CODE": set(), "TAG": set()})
            v["VAR_CODE"].add(x.get("VAR_CODE", "")); v["TAG"].add(x.get("TAG") or "")
    return {k: {"VAR_CODE": "; ".join(sorted(v["VAR_CODE"])), "TAG": "; ".join(sorted(t for t in v["TAG"] if t)) or "(senza TAG)"}
            for k, v in cat.items()}

tabs, aggs, status_rows = [], [], []
t0 = time.time()
for src in SNAP:
    cat = catalog(src)
    for f in sorted(HRM[src].glob("*.txt")):
        meta = cat.get(f.name, {"VAR_CODE": "(non nel catalogo)", "TAG": "(senza TAG)"})
        cols = list(pd.read_csv(f, sep="|", nrows=0).columns)
        meas = (["OBS_VALUE"] if "OBS_VALUE" in cols else []) if src == "ISTAT" else [c for c in cols if c in NUM_OBS]
        row = {"FONTE": src, "TABELLA": f.stem, **meta, "MB": round(f.stat().st_size / 1e6, 1), "MISURE": ", ".join(meas)}
        if "CODICE_REGIONE" not in cols:
            row["STATO"] = "esclusa: senza CODICE_REGIONE"
        elif "ANNO" not in cols:
            row["STATO"] = "esclusa: senza ANNO (elenco)" + ("; colonne anno: " + ", ".join(c for c in cols if "ANNO" in c)
                                                            if any("ANNO" in c for c in cols) else "")
        elif not meas:
            row["STATO"] = "esclusa: nessuna misura numerica (elenco)"
        else:
            row["STATO"] = "analizzata"
        tabs.append(row)
        if row["STATO"] != "analizzata":
            continue
        use = ["CODICE_REGIONE", "ANNO"] + meas + (["OBS_STATUS"] if src == "ISTAT" and "OBS_STATUS" in cols else [])
        parts, nrows, nout, nbady = [], 0, 0, 0
        for ch in pd.read_csv(f, sep="|", dtype=str, usecols=use, chunksize=CHUNK, low_memory=False):
            nrows += len(ch)
            ok = ch.CODICE_REGIONE.isin(CODES22)
            y = ch.ANNO.str.strip()
            oky = y.str.fullmatch(r"\d{4}").fillna(False)
            nout += int((~ok).sum()); nbady += int((ok & ~oky).sum())
            ch, y = ch[ok & oky], y[ok & oky]
            if ch.empty:
                continue
            v = ch[meas].apply(pd.to_numeric, errors="coerce")
            miss = v.isna().sum(axis=1)
            g = pd.DataFrame({"COD": ch.CODICE_REGIONE.to_numpy(), "ANNO": y.astype(int).to_numpy(), "RIGHE": 1,
                              "ZERI": (v == 0).sum(axis=1).to_numpy()})
            for m_ in meas:                               # vuoti per misura: serve a riconoscere le misure non pubblicate
                g["NA::" + m_] = v[m_].isna().astype(int).to_numpy()
            parts.append(g.groupby(["COD", "ANNO"], as_index=False).sum())
            if "OBS_STATUS" in ch:
                st = ch.OBS_STATUS.fillna("(vuoto)")
                status_rows.append(pd.DataFrame({"TABELLA": f.stem, "OBS_STATUS": st, "VALORE_MANCANTE": miss.to_numpy() > 0})
                                   .value_counts().rename("RIGHE").reset_index())
        a = pd.concat(parts).groupby(["COD", "ANNO"], as_index=False).sum()
        a.insert(0, "TABELLA", f.stem); a.insert(0, "FONTE", src); a.insert(2, "TAG", meta["TAG"])
        aggs.append(a)
        row.update({"RIGHE": nrows, "RIGHE_CODICE_FUORI_MAPPA": nout, "RIGHE_ANNO_NON_VALIDO": nbady,
                    "ANNI": f"{a.ANNO.min()}-{a.ANNO.max()}", "ANNI_PUBBLICATI": a.ANNO.nunique(),
                    "ANNI_NON_PUBBLICATI": a.ANNO.max() - a.ANNO.min() + 1 - a.ANNO.nunique(),
                    "ITH0": "presente" if (a.COD == "ITH0").any() else "assente"})
        print(f"  {src} {f.stem}: {nrows:,} righe")
T = pd.DataFrame(tabs)
A = pd.concat(aggs, ignore_index=True)
OBS = (pd.concat(status_rows).groupby(["TABELLA", "OBS_STATUS", "VALORE_MANCANTE"]).RIGHE.sum().reset_index()
       if status_rows else pd.DataFrame(columns=["TABELLA", "OBS_STATUS", "VALORE_MANCANTE", "RIGHE"]))
ctrl("tabelle per stato", T.groupby(["FONTE", "STATO"]).size().to_dict())
ctrl("lettura (s)", round(time.time() - t0))
_show(
T[T.STATO == "analizzata"][["FONTE", "TABELLA", "TAG", "ANNI", "ANNI_PUBBLICATI", "ANNI_NON_PUBBLICATI", "ITH0", "MISURE"]]
)


# ====================================================================================================
# ## 2. Griglia delle celle e classificazione
# ====================================================================================================
# ---- cella 5
rows, unpub_rows = [], []
for (src, tab, tag), a in A.groupby(["FONTE", "TABELLA", "TAG"]):
    years = list(range(a.ANNO.min(), a.ANNO.max() + 1))
    pub = set(a.ANNO)
    nacols = [c for c in a.columns if c.startswith("NA::") and a[c].notna().any()]
    # una misura e' "non pubblicata nell'anno" se e' vuota in tutte le righe di tutte le unita' di quell'anno
    # (cambio di schema della fonte): non conta come valore mancante delle regioni
    yr = a.groupby("ANNO")[["RIGHE"] + nacols].sum()
    pubm = yr[nacols].lt(yr["RIGHE"], axis=0)
    pub = pub - set(pubm.index[pubm.sum(axis=1) == 0])    # righe presenti ma nessun valore: anno non pubblicato
    for y_, r_ in pubm.iterrows():
        nonpub = [c[4:] for c in nacols if not r_[c]]
        if nonpub:
            unpub_rows.append({"FONTE": src, "TABELLA": tab, "ANNO": y_, "MISURE_NON_PUBBLICATE": ", ".join(nonpub),
                               "MISURE_PUBBLICATE": int(r_.sum()), "MISURE_TOTALI": len(nacols)})
    a = a.copy()
    a["VALORI"] = a.RIGHE * a.ANNO.map(pubm.sum(axis=1))
    a["MANCANTI"] = sum(a[c].fillna(0) * a.ANNO.map(pubm[c]).astype(int) for c in nacols)
    g = pd.MultiIndex.from_product([U21 + ["ITH0"], years], names=["COD", "ANNO"]).to_frame(index=False)
    g = g.merge(a[["COD", "ANNO", "RIGHE", "VALORI", "MANCANTI", "ZERI"]], on=["COD", "ANNO"], how="left").fillna(0)
    g[["RIGHE", "VALORI", "MANCANTI", "ZERI"]] = g[["RIGHE", "VALORI", "MANCANTI", "ZERI"]].astype(int)
    g["ANNO_PUBBLICATO"] = g.ANNO.isin(pub)
    fmt = src == "AIFA"                                   # convenzione di formato: vuoto = 0 (verificato sui grezzi)
    g["TIPO"] = np.select(
        [~g.ANNO_PUBBLICATO, g.RIGHE == 0, (g.MANCANTI > 0) & fmt, g.MANCANTI > 0],
        ["anno non pubblicato", "regione assente", "completa (vuoti di formato AIFA)", "valori mancanti"], "completa")
    g.insert(0, "TAG", tag); g.insert(0, "TABELLA", tab); g.insert(0, "FONTE", src)
    rows.append(g)
G = pd.concat(rows, ignore_index=True)
G["COMPLETA"] = G.TIPO.str.startswith("completa")
G["DOMINIO"] = G.FONTE + ": " + G.TAG
UNPUB = pd.DataFrame(unpub_rows, columns=["FONTE", "TABELLA", "ANNO", "MISURE_NON_PUBBLICATE", "MISURE_PUBBLICATE", "MISURE_TOTALI"])
ctrl("tabelle-anno con misure non pubblicate (cambio di schema della fonte)", len(UNPUB))
U = G[G.COD.isin(U21)].copy()
ctrl("celle (21 unita')", len(U))
ctrl("celle per tipo (21 unita')", U.TIPO.value_counts().to_dict())
_show(
pd.crosstab(U.FONTE, U.TIPO, margins=True)
)


# ====================================================================================================
# ## 3. Pattern per dominio, regione e anno
# ====================================================================================================
# ---- cella 7
def summ(x):
    pub = x[x.ANNO_PUBBLICATO]
    return pd.Series({
        "tabelle": x.TABELLA.nunique() if "TABELLA" in x else 1,
        "celle": len(x),
        "anni_non_pubblicati_%": 100 * (~x.ANNO_PUBBLICATO).mean(),
        "regione_assente_%": 100 * (pub.TIPO == "regione assente").mean() if len(pub) else np.nan,
        "celle_con_valori_mancanti_%": 100 * (pub.TIPO == "valori mancanti").mean() if len(pub) else np.nan,
        "valori_mancanti_%": 100 * pub.loc[pub.TIPO == "valori mancanti", "MANCANTI"].sum() / pub.VALORI.sum() if pub.VALORI.sum() else np.nan,
        "celle_complete_%": 100 * pub.COMPLETA.mean() if len(pub) else np.nan})
by_dom = U.groupby(["FONTE", "TAG"]).apply(summ, include_groups=False).reset_index()
by_reg = U.groupby("COD").apply(summ, include_groups=False).reset_index()
by_reg.insert(1, "NOME", by_reg.COD.map(NAME))
by_year = U.groupby(["FONTE", "ANNO"]).apply(summ, include_groups=False).reset_index()
by_dom_reg = U[U.ANNO_PUBBLICATO].assign(INCOMPLETA=lambda d: ~d.COMPLETA) \
    .pivot_table(index="COD", columns="DOMINIO", values="INCOMPLETA", aggfunc="mean") * 100
by_dom_year = U[U.ANNO_PUBBLICATO].assign(INCOMPLETA=lambda d: ~d.COMPLETA) \
    .pivot_table(index="ANNO", columns="DOMINIO", values="INCOMPLETA", aggfunc="mean") * 100
_show(
by_dom.round(2)
)

# ---- cella 8
_show(
by_reg.sort_values("celle_complete_%").round(2)
)


# ====================================================================================================
# ## 4. Comparabilità tra regioni
# 
# Vista a 20 regioni, solo anni pubblicati. Una tabella-anno è confrontabile se tutte le 20 regioni hanno la cella completa.
# ====================================================================================================
# ---- cella 10
def r20(g):
    """Una riga per regione: Trentino-Alto Adige = ITH0 se presente nella tabella-anno, altrimenti ITH1 e ITH2."""
    x = g.set_index("COD")
    out = x.loc[[c for c in R20 if c != "ITH0"], ["COMPLETA", "TIPO"]].copy()
    if x.loc["ITH0", "RIGHE"] > 0:
        t = x.loc["ITH0", ["COMPLETA", "TIPO"]].copy(); t["DA"] = "ITH0"
    else:
        p1, p2 = x.loc["ITH1"], x.loc["ITH2"]
        t = pd.Series({"COMPLETA": bool(p1.COMPLETA and p2.COMPLETA),
                       "TIPO": p1.TIPO if not p1.COMPLETA else p2.TIPO, "DA": "ITH1+ITH2"})
    out.loc["ITH0"] = t[["COMPLETA", "TIPO"]]
    out["DA"] = ""; out.loc["ITH0", "DA"] = t["DA"]
    return out.reset_index()

V = (G[G.ANNO_PUBBLICATO].groupby(["FONTE", "TABELLA", "TAG", "DOMINIO", "ANNO"])
     .apply(r20, include_groups=False).reset_index(level=-1, drop=True).reset_index())
V["COMPLETA"] = V.COMPLETA.astype(bool)
comp = V.groupby(["FONTE", "TABELLA", "TAG", "DOMINIO", "ANNO"]).agg(
    REGIONI_COMPLETE=("COMPLETA", "sum"),
    REGIONI_INCOMPLETE=("COMPLETA", lambda s: int((~s).sum()))).reset_index()
comp["CONFRONTABILE_20"] = comp.REGIONI_COMPLETE == len(R20)
inc = V[~V.COMPLETA].groupby(["TABELLA", "ANNO"]).agg(
    NOMI_INCOMPLETE=("COD", lambda s: ", ".join(label_en(c) for c in s)),
    TIPI=("TIPO", lambda s: ", ".join(sorted(set(s))))).reset_index()
comp = comp.merge(inc, on=["TABELLA", "ANNO"], how="left")
comp_dom = comp.groupby(["FONTE", "TAG", "DOMINIO"]).agg(
    TABELLE=("TABELLA", "nunique"), TABELLE_ANNO=("ANNO", "size"), CONFRONTABILI=("CONFRONTABILE_20", "sum"),
    REGIONI_COMPLETE_MEDIA=("REGIONI_COMPLETE", "mean")).reset_index()
comp_dom["CONFRONTABILI_%"] = 100 * comp_dom.CONFRONTABILI / comp_dom.TABELLE_ANNO
# regioni che, da sole, rendono una tabella-anno non confrontabile
solo = comp[comp.REGIONI_INCOMPLETE == 1].merge(V[~V.COMPLETA][["TABELLA", "ANNO", "COD"]], on=["TABELLA", "ANNO"])
block = V.groupby("COD").agg(TABELLE_ANNO_INCOMPLETA=("COMPLETA", lambda s: int((~s).sum())), TABELLE_ANNO=("COMPLETA", "size")).reset_index()
block["UNICA_INCOMPLETA"] = block.COD.map(solo.COD.value_counts()).fillna(0).astype(int)
block.insert(1, "NOME", block.COD.map(label_en))
ctrl("tabelle-anno pubblicate (20 regioni)", len(comp))
ctrl("tabelle-anno confrontabili su 20 regioni", f"{int(comp.CONFRONTABILE_20.sum())} ({100 * comp.CONFRONTABILE_20.mean():.1f}%)")
_show(
comp_dom.round(1)
)

# ---- cella 11
_show(
block.sort_values("TABELLE_ANNO_INCOMPLETA", ascending=False)
)


# ====================================================================================================
# ## 5. Test di permutazione: la mancanza è concentrata su alcune regioni?
# 
# Per ogni tabella-anno con *k* regioni incomplete, sotto H0 le *k* regioni sono estratte a caso tra le 20. Statistica:
# varianza tra regioni del numero di tabelle-anno incomplete. P-value = (1 + #{T\* ≥ T}) / (1 + B), B = 10.000,
# seme fisso. Per ogni regione: conteggio osservato contro intervallo 2,5%-97,5% della distribuzione sotto H0.
# Il test si ripete su tutte le fonti e per fonte.
# ====================================================================================================
# ---- cella 13
def perm_test(vv, label, rng):
    vv = vv.copy()
    vv["INC"] = ~vv.COMPLETA
    obs = vv.groupby("COD").INC.sum().reindex(R20, fill_value=0).to_numpy()
    ks = vv.groupby(["TABELLA", "ANNO"]).INC.sum().to_numpy()
    ks = ks[(ks > 0) & (ks < len(R20))]                 # k = 0 o k = 20 non sono informative
    sims = np.zeros((N_PERM, len(R20)))
    for k in np.unique(ks):
        n_k = int((ks == k).sum())
        # per ogni permutazione, n_k estrazioni di k regioni senza ripetizione: conteggio per regione
        for start in range(0, N_PERM, 1000):              # a blocchi per contenere la memoria
            nb = min(1000, N_PERM - start)
            pick = np.argsort(rng.random((nb, n_k, len(R20))), axis=2)[:, :, :k].reshape(nb, -1)
            np.add.at(sims, (np.repeat(np.arange(start, start + nb), pick.shape[1]), pick.ravel()), 1)
    # le tabelle-anno con tutte le 20 regioni incomplete aggiungono 1 a ogni regione (costante)
    full = int(vv.groupby(["TABELLA", "ANNO"]).INC.sum().eq(len(R20)).sum())
    sims += full
    t_obs = obs.var(); t_sim = sims.var(axis=1)
    p = (1 + (t_sim >= t_obs - 1e-12).sum()) / (1 + N_PERM)
    lo, hi = np.percentile(sims, [2.5, 97.5], axis=0)
    reg = pd.DataFrame({"AMBITO": label, "COD": R20, "NOME": [label_en(c) for c in R20], "OSSERVATO": obs,
                        "ATTESO_H0": sims.mean(axis=0), "P2_5": lo, "P97_5": hi})
    reg["SOPRA_INTERVALLO"] = reg.OSSERVATO > reg.P97_5
    return {"AMBITO": label, "TABELLE_ANNO_INFORMATIVE": len(ks), "T_OSSERVATA": t_obs,
            "T_MEDIA_H0": t_sim.mean(), "P_VALUE": p, "B": N_PERM, "SEME": SEED}, reg

rng = np.random.default_rng(SEED)
pt, preg = [], []
for label, vv in [("tutte le fonti", V)] + [(s, V[V.FONTE == s]) for s in SNAP]:
    if (~vv.COMPLETA).sum() == 0:
        pt.append({"AMBITO": label, "TABELLE_ANNO_INFORMATIVE": 0, "NOTA": "nessuna cella incompleta"}); continue
    a, b = perm_test(vv, label, rng); pt.append(a); preg.append(b)
perm = pd.DataFrame(pt); perm_reg = pd.concat(preg, ignore_index=True)
_show(
perm
)

# ---- cella 14
_show(
perm_reg[perm_reg.AMBITO == "tutte le fonti"].sort_values("OSSERVATO", ascending=False).round(2)
)


# ====================================================================================================
# ## 6. Figure (in inglese, per il paper)
# ====================================================================================================
# ---- cella 16
# Figura 1: % di celle incomplete (anni pubblicati) per unita' e dominio
m = by_dom_reg.reindex(U21)
m.index = [label_en(u) for u in m.index]
cols = sorted(m.columns, key=lambda c: (c.split(": ")[0], c))
m = m[cols]
xl = [f"{c.split(': ')[0]} · {DOM_EN.get(c.split(': ', 1)[1], c.split(': ', 1)[1])}" for c in cols]
fig, ax = plt.subplots(figsize=(0.42 * len(cols) + 2.2, 5.2))
im = ax.imshow(m.to_numpy(dtype=float), cmap="Blues", vmin=0, vmax=100, aspect="auto")
ax.set_xticks(range(len(cols)), xl, rotation=50, ha="right"); ax.set_yticks(range(len(m)), m.index)
for i in range(m.shape[0]):
    for j in range(m.shape[1]):
        v = m.iat[i, j]
        if pd.notna(v) and v >= 0.5:
            ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=5.5, color="white" if v > 55 else INK)
for sp in ax.spines.values(): sp.set_visible(False)
fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02, label="incomplete (table, year) cells, %")
ax.set_title("Incomplete cells by unit and source domain (published years)", loc="left", color=INK)
_show(
savefig(fig, "d15_fig1_heatmap")
)

# ---- cella 17
# Figura 2: tabelle-anno confrontabili su tutte le 20 regioni, per dominio
c = comp_dom.sort_values(["FONTE", "CONFRONTABILI_%"]).reset_index(drop=True)
fig, ax = plt.subplots(figsize=(3.5, 0.22 * len(c) + 0.8))
y = np.arange(len(c))
ax.barh(y, c["CONFRONTABILI_%"], height=0.62, color=[SRC_COL[s] for s in c.FONTE])
for yi, (v, n) in enumerate(zip(c["CONFRONTABILI_%"], c.TABELLE_ANNO)):
    ax.text(v + 1.5, yi, f"{v:.0f}% of {n}", va="center", fontsize=6, color=INK2)
ax.set_yticks(y, [f"{s} · {DOM_EN.get(t, t)}" for s, t in zip(c.FONTE, c.TAG)])
ax.set_xlim(0, 125); ax.set_xticks([0, 25, 50, 75, 100])
ax.set_xlabel("(table, year) pairs comparable across all 20 regions, %")
ax.grid(axis="x", color=GRID, lw=0.6); ax.set_axisbelow(True)
_show(
savefig(fig, "d15_fig2_comparabilita")
)

# ---- cella 18
# Figura 3: % di celle incomplete per anno e fonte (anni con almeno 3 tabelle pubblicate per la fonte)
fig, ax = plt.subplots(figsize=(3.5, 2.3))
for s in SNAP:
    b = by_year[(by_year.FONTE == s) & (by_year.tabelle >= 3)]
    if len(b):
        ax.plot(b.ANNO, 100 - b["celle_complete_%"], color=SRC_COL[s], marker=SRC_MRK[s], ms=3.5, lw=1.4, label=s)
ax.set_ylabel("incomplete cells, %"); ax.set_xlabel("year")
ax.grid(axis="y", color=GRID, lw=0.6); ax.legend(frameon=False)
ax.set_title("sources with at least 3 tables published in the year", loc="left", fontsize=7, color=INK2)
_show(
savefig(fig, "d15_fig3_anni")
)

# ---- cella 19
# Figura 4: test di permutazione, conteggio osservato vs intervallo sotto H0 (tutte le fonti)
r = perm_reg[perm_reg.AMBITO == "tutte le fonti"].sort_values("OSSERVATO").reset_index(drop=True)
p_all = perm.loc[perm.AMBITO == "tutte le fonti", "P_VALUE"].iloc[0]
fig, ax = plt.subplots(figsize=(3.5, 3.8))
y = np.arange(len(r))
ax.hlines(y, r.P2_5, r.P97_5, color="#86b6ef", lw=4, label="95% interval under H0")
ax.scatter(r.OSSERVATO, y, s=18, color=np.where(r.SOPRA_INTERVALLO, "#eb6834", "#2a78d6"), zorder=3,
           label="observed (orange: above interval)")
ax.set_yticks(y, r.NOME); ax.set_xlabel("incomplete (table, year) pairs")
ax.grid(axis="x", color=GRID, lw=0.6); ax.set_axisbelow(True)
p_txt = f"p < {1 / (N_PERM + 1) * 10:.0e}".replace("e-0", "e-") if p_all <= 1 / (N_PERM + 1) else f"p = {p_all:.4f}"
p_txt = "p < 0.001" if p_all < 0.001 else p_txt
ax.set_title(f"Permutation test (B = {N_PERM:,}), {p_txt}", loc="left", fontsize=7, color=INK2)
ax.legend(frameon=False, loc="lower right", fontsize=6.5)
_show(
savefig(fig, "d15_fig4_permutazioni")
)


# ====================================================================================================
# ## Limiti (da dichiarare)
# 
# - **Assenza strutturale non distinta**: una regione assente è contata come *assente nella fonte*. In due famiglie di
#   tabelle MINIS l'assenza potrebbe dipendere dal fenomeno (nessuna struttura in regione) e non da un dato non trasmesso:
#   `AASL_STAFFUNI_TIPO1/2` (personale universitario) e `DDSM_STAFFALL_CONV` (personale delle strutture convenzionate
#   con i DSM). Non verificato.
# - **Vuoti AIFA**: trattati come convenzione di formato (0 nel 2018, vuoto dal 2019, verificato sui grezzi), non come
#   mancanti.
# - **Combinazioni non pubblicate**: dentro una cella presente, le combinazioni di categorie senza eventi (es. decessi per
#   paese di nascita) non sono pubblicate dalla fonte; non sono contate come mancanti (sparsità, non mancanza).
# - **Tabelle escluse**: senza `CODICE_REGIONE`, senza `ANNO` o senza misure numeriche (foglio `tabelle`).
# - **Test**: la permutazione è dentro la tabella-anno; le tabelle-anno sono trattate come scambiabili tra loro e con lo
#   stesso peso.
# ====================================================================================================
# ---- cella 21
env = pd.DataFrame([("python", platform.python_version()), ("pandas", pd.__version__),
                    ("matplotlib", matplotlib.__version__), ("eseguito", time.strftime("%Y-%m-%d %H:%M")),
                    ("snapshot", json.dumps(SNAP)), ("MEDITA", str(HOME)), ("permutazioni", f"B = {N_PERM}, seme {SEED}"),
                    ("figure", ", ".join(f"{n}_{STAMP}.pdf/.png" for n in FIGS))], columns=["voce", "valore"])
readme = pd.DataFrame({"voce": ["cella", "anno non pubblicato", "regione assente", "valori mancanti",
                                "completa (vuoti di formato AIFA)", "confrontabile", "Trentino", "test"],
                       "definizione": ["(tabella, unita', anno) su 21 unita' e su tutti gli anni dal primo all'ultimo pubblicato",
                                       "nessuna unita' ha righe nell'anno", "anno pubblicato ma non per l'unita'",
                                       "righe presenti con almeno una misura vuota o non numerica, tra le misure pubblicate nell'anno (una misura vuota "
                                       "per tutte le unita' dell'anno e' 'non pubblicata': foglio misure_non_pubblicate)",
                                       "AIFA: vuoto = 0 per convenzione della fonte dal 2019 (verificato sui grezzi)",
                                       "tabella-anno pubblicata con tutte le 20 regioni complete",
                                       "ITH0 se presente nella tabella-anno, altrimenti ITH1 e ITH2 entrambe complete",
                                       "permutazione delle regioni dentro ogni tabella-anno; statistica = varianza tra regioni "
                                       "del numero di tabelle-anno incomplete"]})
fout = OUT / f"d15_missingness_{STAMP}.xlsx"
with pd.ExcelWriter(fout, engine="openpyxl") as wr:
    readme.to_excel(wr, sheet_name="README", index=False)
    env.to_excel(wr, sheet_name="env", index=False)
    pd.DataFrame(CTRL).to_excel(wr, sheet_name="controlli", index=False)
    T.to_excel(wr, sheet_name="tabelle", index=False)
    by_dom.round(3).to_excel(wr, sheet_name="dominio", index=False)
    by_reg.round(3).to_excel(wr, sheet_name="regione", index=False)
    by_year.round(3).to_excel(wr, sheet_name="anno", index=False)
    by_dom_reg.round(2).reset_index().to_excel(wr, sheet_name="dominio_x_regione", index=False)
    by_dom_year.round(2).reset_index().to_excel(wr, sheet_name="dominio_x_anno", index=False)
    comp.to_excel(wr, sheet_name="comparabilita_tab_anno", index=False)
    comp_dom.round(2).to_excel(wr, sheet_name="comparabilita_dominio", index=False)
    block.to_excel(wr, sheet_name="regioni_bloccanti", index=False)
    perm.to_excel(wr, sheet_name="permutazioni", index=False)
    perm_reg.round(3).to_excel(wr, sheet_name="permutazioni_regioni", index=False)
    OBS.to_excel(wr, sheet_name="obs_status_istat", index=False)
    UNPUB.to_excel(wr, sheet_name="misure_non_pubblicate", index=False)
    U[U.TIPO.isin(["regione assente", "valori mancanti", "anno non pubblicato"])] \
        .assign(NOME=lambda d: d.COD.map(NAME))[["FONTE", "TABELLA", "TAG", "COD", "NOME", "ANNO", "TIPO", "MANCANTI", "VALORI"]] \
        .to_excel(wr, sheet_name="celle_incomplete", index=False)
print("Creato:", fout)

