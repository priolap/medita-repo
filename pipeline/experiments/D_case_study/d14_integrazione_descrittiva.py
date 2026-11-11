# -*- coding: utf-8 -*-
# Versione script di d14_integrazione_descrittiva.ipynb (stesse celle, generata automaticamente).
# Uso (dalla cartella MEDITA):  python experiments\D_case_study\d14_integrazione_descrittiva.py
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
# # D14 – Valore dell'integrazione: grezzi vs MEDITA (statistiche descrittive)
# 
# **Snapshot del paper:** AIFA e MINIS 20261025, ISTAT 20261027. Nessun modello inferenziale: il notebook misura,
# sugli stessi dati, quanto i dati grezzi e quelli armonizzati da MEDITA sono utilizzabili per un'analisi statistica
# regionale. Le sezioni seguono le dimensioni di qualità del quadro ESS per la statistica ufficiale
# (*coherence and comparability*, *accuracy*, completezza):
# 
# | Sez. | Domanda | Dimensione |
# |---|---|---|
# | 1 | Le colonne di territorio e anno hanno lo stesso nome nelle fonti? | coerenza dello schema |
# | 2 | Quante coppie (unità, anno) si abbinano tra due fonti? | comparabilità tra fonti |
# | 3 | Quali unità e anni si perdono? | completezza, selezione non casuale |
# | 4 | Le serie mensili restano continue nel tempo? | coerenza temporale |
# | 5 | La Transform conserva i valori? Il Trentino-Alto Adige è disponibile come regione? | accuratezza, completezza |
# | 6 | Quanto cambia un indicatore semplice (confezioni di antidepressivi per 1000 abitanti)? | effetto sull'indicatore |
# 
# **Tre modi di abbinare le unità territoriali**, sugli stessi dati:
# - **R0 – codici originali**: le chiavi come pubblicate (AIFA e MINIS codice ministeriale `010`…, ISTAT `REF_AREA` `ITC1`, `ITD5`…);
# - **R1 – nomi normalizzati**: nome della regione con una normalizzazione generica (maiuscole, accenti, punteggiatura, spazi);
# - **H – MEDITA**: `CODICE_REGIONE` NUTS2-2024 della Transform (con la riga `ITH0` del Trentino-Alto Adige).
# 
# Fonti: AIFA `FARM_ACQUISTI_AIFA`; MINIS `DISP_POSLETTO_REGI` (posti letto per regione); ISTAT `DCIS_DECESSI`
# (popolazione stimata) e `DCCV_AVQ_PERSONE`. Il notebook legge solo file di MEDITA e scrive in `out/`.
# ====================================================================================================
# ---- cella 1
import json, re, time, platform, codecs, csv
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from unidecode import unidecode

HERE = Path.cwd()                              # experiments/D_case_study
HOME = HERE.parents[1]                         # MEDITA
OUT = HERE / "out"; OUT.mkdir(exist_ok=True)
STAMP = time.strftime("%Y%m%d_%H%M%S")
SNAP = {"AIFA": "20261025", "MINIS": "20261025", "ISTAT": "20261027"}
RAW = {s: HOME / "data" / "input" / s / SNAP[s] for s in SNAP}
HRM = {s: HOME / "data" / "output" / s / SNAP[s] for s in SNAP}
CHUNK = 500_000
pd.set_option("display.width", 200, "display.max_columns", 30, "display.max_colwidth", 80)
for s in SNAP:
    assert RAW[s].is_dir() and HRM[s].is_dir(), f"cartella mancante per {s}"

CMAP = json.loads((HOME / "config" / "codregione_map.json").read_text(encoding="utf-8"))
NAME = {k: v["REGIONE"] for k, v in CMAP.items()}
MIN2NUTS = {v["ASL_CODE"]: k for k, v in CMAP.items() if v.get("ASL_CODE") and k != "ITH0"}
ISTAT_OLD = {"ITD1": "ITH1", "ITD2": "ITH2", "ITD3": "ITH3", "ITD4": "ITH4", "ITD5": "ITH5", "ITDA": "ITH0",
             "ITE1": "ITI1", "ITE2": "ITI2", "ITE3": "ITI3", "ITE4": "ITI4"}
U21 = sorted(k for k in CMAP if k != "ITH0")                 # 19 regioni + 2 province autonome
R20 = sorted(k for k in CMAP if k not in ("ITH1", "ITH2"))   # 20 regioni (Trentino-Alto Adige = ITH0)
SHORT = {"ITC1": "PIE", "ITC2": "VDA", "ITC3": "LIG", "ITC4": "LOM", "ITF1": "ABR", "ITF2": "MOL", "ITF3": "CAM",
         "ITF4": "PUG", "ITF5": "BAS", "ITF6": "CAL", "ITG1": "SIC", "ITG2": "SAR", "ITH0": "TAA", "ITH1": "BZ",
         "ITH2": "TN", "ITH3": "VEN", "ITH4": "FVG", "ITH5": "EMR", "ITI1": "TOS", "ITI2": "UMB", "ITI3": "MAR", "ITI4": "LAZ"}
PATHS = ["K_R0", "K_R1", "K_H"]
LAB = {"K_R0": "R0 codici originali", "K_R1": "R1 nomi normalizzati", "K_H": "H MEDITA"}
LABF = {"K_R0": "R0 original codes", "K_R1": "R1 normalised names", "K_H": "H MEDITA"}  # PATCH_D14I_EN_261031
COL = {"K_R0": "#eb6834", "K_R1": "#1baf7a", "K_H": "#2a78d6"}     # palette validata (dataviz), + marcatori diversi
MRK = {"K_R0": "s", "K_R1": "^", "K_H": "o"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
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

def sniff(path):
    with open(path, "rb") as f:
        head = f.read(4 << 20)
    try:
        codecs.getincrementaldecoder("utf-8")().decode(head, final=False); enc = "utf-8"
    except UnicodeDecodeError:
        enc = "latin1"
    first = head.split(b"\n", 1)[0].decode(enc, errors="replace")
    return max(["|", ";", ","], key=first.count), enc

def norm(s):
    """R1: normalizzazione generica del nome della regione, senza regole di dominio."""
    s = unidecode(str(s)).upper()
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def norm_col(c):
    """Normalizzazione dei nomi di colonna come datatable_cleaner.input_cleaner (righe 170-184)."""
    c = re.sub(r"[^\w\d_\s]", "", unidecode(str(c)).strip())
    return c.upper().replace(" ", "_").replace("\n", "_").replace("__", "_")
print("MEDITA:", HOME); print("snapshot:", SNAP)


# ====================================================================================================
# ## 1. Coerenza dello schema: nomi delle colonne di territorio e anno
# 
# Per ogni file grezzo del catalogo (`config/info_<FONTE>.json`, campo `file_in`) si legge la sola intestazione
# (file CSV; i fogli di calcolo sono contati a parte, la loro intestazione non è sempre nella prima riga) e si
# individuano le colonne che MEDITA trasforma in `CODICE_REGIONE`, `REGIONE`, `ANNO`:
# - per normalizzazione del nome (come `datatable_cleaner.input_cleaner`), oppure
# - per rinomina del dizionario, registrata nel catalogo (`parsing`: «harmonized column: X replaced w Y»).
# ====================================================================================================
# ---- cella 3
ROLES = ["CODICE_REGIONE", "REGIONE", "ANNO"]
rows, skipped = [], []
for s in SNAP:
    cat = json.loads((HOME / "config" / f"info_{s}.json").read_text(encoding="utf-8"))
    for x in cat:
        ren = {}
        for l in x.get("parsing") or []:
            m = re.match(r"harmonized column: (.+) replaced w (CODICE_REGIONE|REGIONE|ANNO)$", l)
            if m:
                ren[m.group(1)] = m.group(2)
        for fn in x.get("file_in") or []:
            f = RAW[s] / Path(fn).name
            if not f.exists():
                skipped.append({"FONTE": s, "FILE": Path(fn).name, "MOTIVO": "non trovato nel grezzo dello snapshot"}); continue
            if f.suffix.lower() not in (".csv", ".txt"):
                skipped.append({"FONTE": s, "FILE": f.name, "MOTIVO": f"foglio di calcolo ({f.suffix})"}); continue
            sep, enc = sniff(f)
            with open(f, encoding=enc, errors="replace", newline="") as fh:
                header = next(csv.reader(fh, delimiter=sep))
            for raw in header:
                n = norm_col(raw)
                role, via = (n, "normalizzazione") if n in ROLES else (ren.get(n), "dizionario")
                if role in ROLES:
                    rows.append({"FONTE": s, "VAR_CODE": x.get("VAR_CODE"), "FILE": f.name, "RUOLO": role,
                                 "NOME_GREZZO": raw.strip(), "NOME_NORMALIZZATO": n, "VIA": via})
schema = pd.DataFrame(rows).drop_duplicates()
skipped = pd.DataFrame(skipped, columns=["FONTE", "FILE", "MOTIVO"]).drop_duplicates()
files_read = schema.groupby("FONTE").FILE.nunique()
schema_sum = schema.groupby(["FONTE", "RUOLO"]).agg(
    FILE=("FILE", "nunique"), NOMI_GREZZI_DISTINTI=("NOME_GREZZO", "nunique"),
    NOMI_GREZZI=("NOME_GREZZO", lambda v: " | ".join(sorted(set(v)))),
    VIA_DIZIONARIO=("VIA", lambda v: int((v == "dizionario").sum()))).reset_index()
schema_sum["NOMI_IN_MEDITA"] = 1
ctrl("schema: file CSV letti per fonte", files_read.to_dict())
ctrl("schema: file non letti (fogli di calcolo o assenti)", skipped.groupby("MOTIVO").size().to_dict())
ctrl("schema: nomi grezzi distinti, tutte le fonti",
     {r: int(schema[schema.RUOLO == r].NOME_GREZZO.nunique()) for r in ROLES})
_show(
schema_sum
)

# ---- cella 4
# Figura 1: nomi distinti delle colonne di territorio e anno: grezzi (tutte le fonti) vs MEDITA
t = {r: schema[schema.RUOLO == r].NOME_GREZZO.nunique() for r in ROLES}
fig, ax = plt.subplots(figsize=(3.5, 1.9))
y = np.arange(len(ROLES)); w = 0.36
ax.barh(y - w / 2, [t[r] for r in ROLES], height=w - 0.04, color="#eb6834", label="raw sources")
ax.barh(y + w / 2, [1] * len(ROLES), height=w - 0.04, color="#2a78d6", label="MEDITA")
for i, r in enumerate(ROLES):
    ax.text(t[r] + 0.2, i - w / 2, str(t[r]), va="center", fontsize=7, color=INK)
    ax.text(1.2, i + w / 2, "1", va="center", fontsize=7, color=INK)
ax.set_yticks(y, ROLES); ax.invert_yaxis()
ax.set_xlabel("distinct column names")
ax.grid(axis="x", color=GRID, lw=0.6); ax.set_axisbelow(True)
ax.set_xlim(0, max(t.values()) * 1.2 + 1); ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(1.0, 1.0))
_show(
savefig(fig, "d14_fig1_schema")
)


# ====================================================================================================
# ## 2. Comparabilità tra fonti: coppie (unità, anno) abbinate
# 
# Dai file **grezzi** si leggono codice e nome territoriale per anno. L'unità «vera» di ogni chiave è quella del codice
# ufficiale (ministeriale per AIFA e MINIS, `REF_AREA` per ISTAT). Unità: 19 regioni + 2 province autonome = 21 (AIFA e
# MINIS pubblicano solo le province). Una cella (unità, anno) è abbinata tra due fonti in un percorso se le chiavi del
# percorso coincidono; gli anni sono quelli comuni alle due fonti.
# ====================================================================================================
# ---- cella 6
def read_raw(f, cols, rename):
    sep, enc = sniff(f)
    return pd.read_csv(f, sep=sep, dtype=str, encoding=enc, usecols=cols).rename(columns=rename)

AIFA_FILES = sorted(RAW["AIFA"].glob("*.csv"))
MINIS_FILES = sorted(RAW["MINIS"].glob("posti_letto_per_regione_e_disciplina_*.csv"))

def keys_aifa():
    d = pd.concat([read_raw(f, ["anno", "codreg", "regione"], {"anno": "ANNO", "codreg": "CODE", "regione": "NAME"})
                   .drop_duplicates() for f in AIFA_FILES]).drop_duplicates()
    d["UNIT"] = d.CODE.str.strip().str.zfill(3).map(MIN2NUTS); return d

def keys_minis():
    d = pd.concat([read_raw(f, ["Anno", "Codice Regione", "Descrizione Regione"],
                            {"Anno": "ANNO", "Codice Regione": "CODE", "Descrizione Regione": "NAME"})
                   .drop_duplicates() for f in MINIS_FILES]).drop_duplicates()
    d["UNIT"] = d.CODE.str.strip().str.zfill(3).map(MIN2NUTS); return d

def keys_istat(fname):
    f = RAW["ISTAT"] / fname
    sep, enc = sniff(f)
    seen = set()
    for ch in pd.read_csv(f, sep=sep, dtype=str, encoding=enc, chunksize=CHUNK, low_memory=False,
                          usecols=["REF_AREA", "REF_AREA_DESC", "TIME_PERIOD"]):
        seen.update(map(tuple, ch[["TIME_PERIOD", "REF_AREA", "REF_AREA_DESC"]].drop_duplicates().values.tolist()))
    d = pd.DataFrame(sorted(seen, key=lambda t: tuple("" if pd.isna(v) else str(v) for v in t)),
                     columns=["ANNO", "CODE", "NAME"])
    d["UNIT"] = d.CODE.map(lambda c: ISTAT_OLD.get(c, c)).where(lambda s: s.isin(U21)); return d

t0 = time.time()
RK = {"AIFA": keys_aifa(), "MINIS": keys_minis(),
      "ISTAT_DECESSI": keys_istat("DCIS_DECESSI.csv"), "ISTAT_AVQ": keys_istat("DCCV_AVQ_PERSONE.csv")}
for k in list(RK):
    d = RK[k].reset_index(drop=True)
    d["ANNO"] = pd.to_numeric(d.ANNO, errors="coerce")
    d = d[d.ANNO.notna() & d.UNIT.isin(U21)].copy()
    d["ANNO"] = d.ANNO.astype(int)
    d["K_R0"] = d.CODE.str.strip(); d["K_R1"] = d.NAME.map(norm).where(d.NAME.notna()); d["K_H"] = d.UNIT
    RK[k] = d
    ctrl(f"chiavi grezze {k}", f"{d.UNIT.nunique()} unita', anni {d.ANNO.min()}-{d.ANNO.max()}, "
                               f"nomi vuoti {int(d.NAME.isna().sum())}")
print(f"chiavi grezze lette in {time.time() - t0:.0f} s")

ex = pd.concat([d.assign(FONTE=k) for k, d in RK.items()])
chiavi_es = ex.groupby(["UNIT", "FONTE"]).agg(
    CODICI=("CODE", lambda s: ", ".join(sorted(set(s)))),
    NOMI=("NAME", lambda s: " | ".join(sorted(set(map(str, s.dropna())))))).reset_index()
chiavi_es.insert(1, "NOME_MEDITA", chiavi_es.UNIT.map(NAME))
_show(
chiavi_es[chiavi_es.UNIT.isin(["ITC2", "ITC4", "ITH1", "ITH2", "ITH5"])]
)

# ---- cella 7
PAIRS = [("AIFA", "MINIS"), ("AIFA", "ISTAT_DECESSI"), ("AIFA", "ISTAT_AVQ"), ("MINIS", "ISTAT_DECESSI"),
         ("MINIS", "ISTAT_AVQ"), ("ISTAT_DECESSI", "ISTAT_AVQ")]
def linked(a, b, key, years=None):
    A = RK[a][["UNIT", "ANNO", key]].drop_duplicates(); B = RK[b][["UNIT", "ANNO", key]].drop_duplicates()
    yrs = sorted(set(A.ANNO) & set(B.ANNO)) if years is None else years
    cells = pd.MultiIndex.from_product([U21, yrs], names=["UNIT", "ANNO"]).to_frame(index=False)
    m = cells.merge(A, on=["UNIT", "ANNO"], how="left").merge(B, on=["UNIT", "ANNO"], how="left", suffixes=("_A", "_B"))
    m["OK"] = m[f"{key}_A"].notna() & (m[f"{key}_A"] == m[f"{key}_B"])
    return m.groupby(["UNIT", "ANNO"], as_index=False).OK.any(), yrs

rows, lost = [], []
for a, b in PAIRS:
    for k in PATHS:
        m, yrs = linked(a, b, k)
        rows.append({"FONTE_A": a, "FONTE_B": b, "PERCORSO": LAB[k], "ANNI": f"{yrs[0]}-{yrs[-1]}", "CELLE": len(m),
                     "ABBINATE": int(m.OK.sum()), "QUOTA_%": round(100 * m.OK.mean(), 1),
                     "UNITA_SEMPRE_ABBINATE": int(m.groupby("UNIT").OK.all().sum())})
        for u, g in m[~m.OK].groupby("UNIT"):
            lost.append({"FONTE_A": a, "FONTE_B": b, "PERCORSO": LAB[k], "UNITA": u, "NOME": NAME[u],
                         "ANNI_PERSI": ", ".join(map(str, sorted(g.ANNO)))})
link = pd.DataFrame(rows)
lost = pd.DataFrame(lost, columns=["FONTE_A", "FONTE_B", "PERCORSO", "UNITA", "NOME", "ANNI_PERSI"])
link_w = link.assign(COPPIA=link.FONTE_A + " – " + link.FONTE_B).pivot(index="COPPIA", columns="PERCORSO", values="QUOTA_%") \
             .reindex(columns=[LAB[k] for k in PATHS])
_show(
link_w
)

# ---- cella 8
# Figura 2: % di celle (unita', anno) abbinate per coppia di fonti e percorso
pairs_lab = [f"{a} – {b}" for a, b in PAIRS]
fig, ax = plt.subplots(figsize=(7, 2.4))
w = 0.26; y = np.arange(len(PAIRS))
for j, k in enumerate(PATHS):
    v = link_w.loc[pairs_lab, LAB[k]].to_numpy()
    ax.barh(y + (j - 1) * w, v, height=w - 0.03, color=COL[k], label=LABF[k])
    for yi, vi in zip(y + (j - 1) * w, v):
        ax.text(vi + 1, yi, f"{vi:.0f}", va="center", fontsize=6, color=INK2)
ax.set_yticks(y, [p.replace("ISTAT_", "ISTAT ") for p in pairs_lab]); ax.invert_yaxis()
ax.set_xlim(0, 112); ax.set_xlabel("linked (unit, year) cells, %")
ax.grid(axis="x", color=GRID, lw=0.6); ax.set_axisbelow(True)
ax.legend(loc="lower right", frameon=False, ncol=3, bbox_to_anchor=(1, 1.0))
_show(
savefig(fig, "d14_fig2_abbinamenti")
)


# ====================================================================================================
# ## 3. Completezza: quali unità e anni si perdono
# 
# Una cella (unità, anno) è **integrabile** se si abbina in tutte e tre le coppie con AIFA (AIFA–MINIS, AIFA–ISTAT
# DECESSI, AIFA–ISTAT AVQ), sugli anni comuni alle quattro fonti. La griglia mostra se le perdite sono casuali o
# concentrate su alcune unità (selezione non casuale).
# ====================================================================================================
# ---- cella 10
YEARS4 = sorted(set.intersection(*[set(RK[k].ANNO) for k in RK]))
ctrl("anni comuni alle quattro fonti grezze", f"{YEARS4[0]}-{YEARS4[-1]}")
def integrable(key):
    ok = None
    for b in ["MINIS", "ISTAT_DECESSI", "ISTAT_AVQ"]:
        m, _ = linked("AIFA", b, key, YEARS4)
        s = m.set_index(["UNIT", "ANNO"]).OK
        ok = s if ok is None else (ok & s)
    return ok
GRID3 = {k: integrable(k) for k in PATHS}
compl = pd.DataFrame([{"PERCORSO": LAB[k], "CELLE": len(g), "INTEGRABILI": int(g.sum()), "QUOTA_%": round(100 * g.mean(), 1),
                       "UNITA_MAI_INTEGRABILI": ", ".join(NAME[u] for u, v in g.groupby(level=0).any().items() if not v),
                       "UNITA_PARZIALI": ", ".join(NAME[u] for u, v in g.groupby(level=0).mean().items() if 0 < v < 1)}
                      for k, g in GRID3.items()])
_show(
compl
)

# ---- cella 11
# Figura 3: griglia unita' x anno, per percorso (pieno = integrabile, vuoto = perso)
fig, axes = plt.subplots(1, 3, figsize=(7, 3.6), sharey=True)
for ax, k in zip(axes, PATHS):
    g = GRID3[k].unstack().reindex(U21)
    ax.imshow(g.to_numpy(dtype=float), cmap=matplotlib.colors.ListedColormap(["#f0efec", COL[k]]), vmin=0, vmax=1,
              aspect="auto")
    ax.set_xticks(range(len(YEARS4)), [str(y)[2:] for y in YEARS4])
    ax.set_title(f"{LABF[k]}\n{int(g.to_numpy().sum())}/{g.size} cells", color=INK)
    ax.set_xticks(np.arange(-.5, len(YEARS4)), minor=True); ax.set_yticks(np.arange(-.5, len(U21)), minor=True)
    ax.grid(which="minor", color="white", lw=1.5); ax.tick_params(which="minor", length=0)
    for sp in ax.spines.values(): sp.set_visible(False)
axes[0].set_yticks(range(len(U21)), [SHORT[u] for u in U21])
_show(
savefig(fig, "d14_fig3_griglia")
)


# ====================================================================================================
# ## 4. Coerenza temporale: serie mensili AIFA
# 
# Serie mensile delle confezioni (convenzionata, tutte le classi e gli ATC) per unità, costruita raggruppando per la
# chiave di ciascun percorso. Se il nome grezzo cambia nel tempo, la serie raggruppata per nome si spezza in più serie.
# ====================================================================================================
# ---- cella 13
def raw_aifa_monthly():
    parts = []
    for f in AIFA_FILES:
        d = read_raw(f, ["anno", "mese", "codreg", "regione", "numero_confezioni_convenzionata"], {})
        d["CONF"] = pd.to_numeric(d.numero_confezioni_convenzionata)
        parts.append(d.groupby(["anno", "mese", "codreg", "regione"], as_index=False).CONF.sum())
    d = pd.concat(parts, ignore_index=True)
    d["ANNO"] = d.anno.astype(int); d["MESE"] = d.mese.astype(int)       # '1' e '01' come nella fonte
    d["UNIT"] = d.codreg.str.strip().str.zfill(3).map(MIN2NUTS)
    d["K_R0"] = d.codreg.str.strip(); d["K_R1"] = d.regione.map(norm); d["K_H"] = d.UNIT
    d["T"] = d.ANNO * 12 + d.MESE - 1
    return d
rm = raw_aifa_monthly()
NMONTHS = rm["T"].nunique()
ctrl("AIFA grezzo: mesi", f"{NMONTHS} ({rm.ANNO.min()}-{rm.ANNO.max()})")

def longest_run(ts):
    ts = np.sort(np.unique(ts)); best = cur = 1
    for a, b in zip(ts[:-1], ts[1:]):
        cur = cur + 1 if b == a + 1 else 1; best = max(best, cur)
    return best if len(ts) else 0

serie = []
for u in U21:
    g = rm[rm.UNIT == u]
    for k in PATHS:
        keys = g[k].unique()
        runs = {key: longest_run(rm.loc[rm[k] == key, "T"]) for key in keys}
        best = max(runs, key=runs.get)
        serie.append({"UNITA": u, "NOME": NAME[u], "PERCORSO": LAB[k], "CHIAVI_DISTINTE": len(keys),
                      "CHIAVI": " | ".join(map(str, keys)), "MESI_SERIE_CONTINUA_PIU_LUNGA": runs[best], "SU": NMONTHS})
serie = pd.DataFrame(serie)
serie_sum = serie.groupby("PERCORSO").agg(UNITA_CON_SERIE_INTERA=("MESI_SERIE_CONTINUA_PIU_LUNGA", lambda v: int((v == NMONTHS).sum())),
                                          MESI_MEDIANI=("MESI_SERIE_CONTINUA_PIU_LUNGA", "median"),
                                          MESI_MINIMI=("MESI_SERIE_CONTINUA_PIU_LUNGA", "min")).reindex([LAB[k] for k in PATHS])
serie_sum["UNITA_SPEZZATE"] = [", ".join(serie[(serie.PERCORSO == LAB[k]) & (serie.MESI_SERIE_CONTINUA_PIU_LUNGA < NMONTHS)].NOME)
                               for k in PATHS]
_show(
serie_sum
)

# ---- cella 14
# Figura 4: periodi coperti da ciascuna chiave, per le unita' la cui serie per nome si spezza (R1) - una riga per
# chiave; H MEDITA e R0 hanno una sola chiave per unita' su tutti i mesi
broken = serie[(serie.PERCORSO == LAB["K_R1"]) & (serie.MESI_SERIE_CONTINUA_PIU_LUNGA < NMONTHS)].UNITA.tolist()
show = broken if broken else ["ITC4"]
rows_g = []
for u in show:
    g = rm[rm.UNIT == u]
    rows_g.append((u, "H", f"{SHORT[u]}  H  {u}", sorted(g["T"].unique())))
    for key, gg in g.groupby("K_R1"):
        rows_g.append((u, "R1", f"{SHORT[u]}  R1 «{key}»", sorted(gg["T"].unique())))
fig, ax = plt.subplots(figsize=(7, 0.22 * len(rows_g) + 0.8))
for i, (u, kind, lab, ts) in enumerate(rows_g):
    ts = np.array(ts); cuts = np.where(np.diff(ts) != 1)[0]
    for seg in np.split(ts, cuts + 1):
        ax.barh(i, seg[-1] - seg[0] + 1, left=seg[0], height=0.62,
                color=COL["K_H"] if kind == "H" else COL["K_R1"])
ax.set_yticks(range(len(rows_g)), [r[2] for r in rows_g], fontsize=6.5); ax.invert_yaxis()
yrs = sorted(rm.ANNO.unique())
ax.set_xticks([y * 12 for y in yrs], [str(y) for y in yrs]); ax.set_xlim(yrs[0] * 12, (yrs[-1] + 1) * 12)
ax.grid(axis="x", color=GRID, lw=0.6); ax.set_axisbelow(True)
ax.set_title("Months covered by each key (blue: MEDITA code; green: normalised raw name)", loc="left", color=INK)
_show(
savefig(fig, "d14_fig4_serie_mensili")
)


# ====================================================================================================
# ## 5. Accuratezza e completezza: conservazione dei valori e Trentino-Alto Adige
# 
# - **Conservazione**: per unità e anno, i totali dei grezzi (per codice ufficiale) devono coincidere con quelli della
#   tabella MEDITA. Una differenza indicherebbe righe perse, duplicate o valori alterati dalla Transform.
# - **Trentino-Alto Adige**: AIFA e MINIS pubblicano solo Bolzano e Trento; MEDITA aggiunge la riga regionale `ITH0`
#   (superkey). Si verifica `ITH0 = ITH1 + ITH2` e si contano le celle regionali disponibili prima e dopo.
# ====================================================================================================
# ---- cella 16
MEAS_AIFA = ["numero_confezioni_convenzionata", "spesa_convenzionata", "numero_confezioni_traccia", "spesa_flusso_tracciabilita"]
raw_a = []
for f in AIFA_FILES:
    d = read_raw(f, ["anno", "codreg"] + MEAS_AIFA, {})
    for c in MEAS_AIFA: d[c] = pd.to_numeric(d[c])
    d["UNIT"] = d.codreg.str.strip().str.zfill(3).map(MIN2NUTS); d["ANNO"] = d.anno.astype(int)
    raw_a.append(d.groupby(["UNIT", "ANNO"])[MEAS_AIFA].sum())
raw_a = pd.concat(raw_a).groupby(level=[0, 1]).sum()
raw_a.columns = [c.upper() for c in raw_a.columns]
h_a = pd.read_csv(HRM["AIFA"] / "FARM_ACQUISTI_AIFA.txt", sep="|", dtype=str, low_memory=False,
                  usecols=["ANNO", "CODICE_REGIONE", "NUMERO_CONFEZIONI_CONVENZIONATA", "SPESA_CONVENZIONATA",
                           "NUMERO_CONFEZIONI_TRACCIA", "SPESA_FLUSSO_TRACCIABILITA"])
for c in raw_a.columns: h_a[c] = pd.to_numeric(h_a[c])
h_a["ANNO"] = h_a.ANNO.astype(int)
h_a = h_a.groupby(["CODICE_REGIONE", "ANNO"])[list(raw_a.columns)].sum()
h_a.index.names = ["UNIT", "ANNO"]

pl_raw = []
for f in MINIS_FILES:
    sep, enc = sniff(f)
    d = pd.read_csv(f, sep=sep, dtype=str, encoding=enc)
    tot = [c for c in d.columns if norm_col(c) == "TOTALE_POSTI_LETTO"][0]
    d["V"] = pd.to_numeric(d[tot].str.strip().str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    d["UNIT"] = d["Codice Regione"].str.strip().str.zfill(3).map(MIN2NUTS); d["ANNO"] = d["Anno"].astype(int)
    pl_raw.append(d.groupby(["UNIT", "ANNO"]).V.sum())
pl_raw = pd.concat(pl_raw).groupby(level=[0, 1]).sum().rename("TOTALE_POSTI_LETTO").to_frame()
pl_h = pd.read_csv(HRM["MINIS"] / "DISP_POSLETTO_REGI.txt", sep="|", dtype=str)
pl_h["TOTALE_POSTI_LETTO"] = pd.to_numeric(pl_h.TOTALE_POSTI_LETTO); pl_h["ANNO"] = pl_h.ANNO.astype(int)
pl_h = pl_h.groupby(["CODICE_REGIONE", "ANNO"])[["TOTALE_POSTI_LETTO"]].sum(); pl_h.index.names = ["UNIT", "ANNO"]

cons = []
for fonte, r, h in [("AIFA FARM_ACQUISTI_AIFA", raw_a, h_a), ("MINIS DISP_POSLETTO_REGI", pl_raw, pl_h)]:
    hh = h[h.index.get_level_values(0).isin(U21)]
    j = r.join(hh, how="outer", lsuffix="_GREZZO", rsuffix="_MEDITA")
    for c in r.columns:
        a, b = j[f"{c}_GREZZO"], j[f"{c}_MEDITA"]
        diff = (a - b).abs()
        cons.append({"FONTE": fonte, "MISURA": c, "CELLE": len(j), "CELLE_SOLO_GREZZO": int(b.isna().sum()),
                     "CELLE_SOLO_MEDITA": int(a.isna().sum()), "TOTALE_GREZZO": a.sum(), "TOTALE_MEDITA": b.sum(),
                     "DIFF_ASSOLUTA_MAX": diff.max(), "DIFF_RELATIVA_MAX": (diff / a.abs().replace(0, np.nan)).max(),
                     "CELLE_DIVERSE": int((diff > 1e-6 * a.abs().clip(lower=1)).sum())})
    # Trentino: ITH0 = ITH1 + ITH2 nella tabella MEDITA
    for c in r.columns:
        x = h[c].unstack(0)
        if "ITH0" in x:
            d = (x["ITH0"] - x["ITH1"] - x["ITH2"]).abs().max()
            ctrl(f"{fonte}: max |ITH0 - (ITH1+ITH2)| {c}", float(d), "OK" if d < 1e-6 * x["ITH0"].abs().max() else "DA VERIFICARE")
cons = pd.DataFrame(cons)
trent = pd.DataFrame([
    {"FONTE": "AIFA", "CELLE_REGIONALI_TAA_GREZZI": 0, "CELLE_REGIONALI_TAA_MEDITA": int(h_a.loc["ITH0"].shape[0]),
     "NOTA": "il grezzo ha solo 041 Bolzano e 042 Trento"},
    {"FONTE": "MINIS posti letto", "CELLE_REGIONALI_TAA_GREZZI": int((pl_raw.index.get_level_values(0) == "ITH0").sum()),
     "CELLE_REGIONALI_TAA_MEDITA": int(pl_h.loc["ITH0"].shape[0]), "NOTA": "il grezzo ha solo 041 e 042"}])
_show(
cons
)

# ---- cella 17
_show(
trent
)


# ====================================================================================================
# ## 6. Effetto su un indicatore: confezioni di antidepressivi (ATC3 N06A, classe A) per 1000 abitanti
# 
# Numeratore AIFA (convenzionata), denominatore la popolazione stimata da ISTAT `DCIS_DECESSI` (morti / tasso di mortalità
# × 1000). I valori sono quelli di MEDITA in tutti i percorsi: cambia solo quali celle regione-anno si possono costruire,
# cioè quelle integrabili (sez. 3; per il Trentino-Alto Adige servono Bolzano e Trento entrambe). Si confrontano la
# disponibilità per regione e il valore nazionale calcolato sulle sole regioni disponibili.
# ====================================================================================================
# ---- cella 19
TOT = {"totale", "Totale", "World", "TOTALE", "total", "Mondo"}
keep = []
for ch in pd.read_csv(HRM["ISTAT"] / "DCIS_DECESSI.txt", sep="|", dtype=str, chunksize=CHUNK, low_memory=False,
                      usecols=["CODICE_REGIONE", "ANNO", "DATA_TYPE", "SEX", "AGE", "CITIZENSHIP", "OBS_VALUE",
                               "COUNTRY_BIRTH_DESC", "MARITAL_STATUS_DESC", "EDU_LEV_HIGHEST_DESC"]):
    m = ch.DATA_TYPE.isin(["DEATH", "DEATHRATE"]) & (ch.SEX == "9") & (ch.CITIZENSHIP == "TOTAL") & (ch.AGE == "TOTAL")
    for c in ["COUNTRY_BIRTH_DESC", "MARITAL_STATUS_DESC", "EDU_LEV_HIGHEST_DESC"]:
        m &= ch[c].isin(TOT)
    keep.append(ch.loc[m, ["CODICE_REGIONE", "ANNO", "DATA_TYPE", "OBS_VALUE"]])
dec = pd.concat(keep); dec["ANNO"] = dec.ANNO.astype(int); dec["OBS_VALUE"] = pd.to_numeric(dec.OBS_VALUE)
assert not dec.duplicated(["CODICE_REGIONE", "ANNO", "DATA_TYPE"]).any()
p = dec.pivot_table(index=["CODICE_REGIONE", "ANNO"], columns="DATA_TYPE", values="OBS_VALUE")
POP = (p.DEATH / p.DEATHRATE * 1000).rename("POP")
ctrl("popolazione stimata Italia (milioni), ultimo anno",
     round(POP[POP.index.get_level_values(0).isin(R20)].groupby(level=1).sum().iloc[-1] / 1e6, 2))

a = pd.read_csv(HRM["AIFA"] / "FARM_ACQUISTI_AIFA.txt", sep="|", dtype=str, low_memory=False,
                usecols=["ANNO", "CODICE_REGIONE", "CLASSE", "ATC3", "NUMERO_CONFEZIONI_CONVENZIONATA"])
a = a[(a.ATC3 == "N06A") & (a.CLASSE == "A")]
a["V"] = pd.to_numeric(a.NUMERO_CONFEZIONI_CONVENZIONATA); a["ANNO"] = a.ANNO.astype(int)
N06A = a.groupby(["CODICE_REGIONE", "ANNO"]).V.sum().rename("N06A")
ind = pd.concat([N06A, POP], axis=1, join="inner").reset_index().rename(columns={"level_0": "REG", "CODICE_REGIONE": "REG"})
ind = ind[ind.REG.isin(R20) & ind.ANNO.isin(YEARS4)]
ind["X1000"] = ind.N06A / ind.POP * 1000

def avail(k):
    g = GRID3[k].reset_index()
    g["REG"] = g.UNIT.replace({"ITH1": "ITH0", "ITH2": "ITH0"})
    return g.groupby(["REG", "ANNO"]).OK.all()
nat = []
for k in PATHS:
    av = avail(k)
    x = ind.merge(av.rename("OK").reset_index(), on=["REG", "ANNO"])
    for y, g in x.groupby("ANNO"):
        gg = g[g.OK]
        full = g.N06A.sum() / g.POP.sum() * 1000
        nat.append({"PERCORSO": LAB[k], "ANNO": y, "REGIONI": len(gg), "POP_COPERTA_%": 100 * gg.POP.sum() / g.POP.sum(),
                    "ITALIA_X1000": gg.N06A.sum() / gg.POP.sum() * 1000 if len(gg) else np.nan,
                    "ITALIA_X1000_COMPLETO": full,
                    "SCARTO_%": 100 * (gg.N06A.sum() / gg.POP.sum() * 1000 / full - 1) if len(gg) else np.nan})
nat = pd.DataFrame(nat)
ind_w = ind.pivot(index="REG", columns="ANNO", values="X1000")
_show(
nat.round(2)
)

# ---- cella 20
# Figura 5: indicatore per regione (ultimo anno comune) con la disponibilita' per percorso
Y = YEARS4[-1]
v = ind[ind.ANNO == Y].set_index("REG").X1000.sort_values()
fig, ax = plt.subplots(figsize=(3.5, 4.2))
yy = np.arange(len(v))
ax.hlines(yy, 0, v.values, color=GRID, lw=1)
ax.scatter(v.values, yy, s=22, color=COL["K_H"], marker=MRK["K_H"], zorder=3, label="H MEDITA (all)")
for k, dx in [("K_R1", 1.0), ("K_R0", 1.0)]:
    av = avail(k).xs(Y, level=1)
    ok = [r for r in v.index if av.get(r, False)]
    ax.scatter(v.loc[ok].values, [list(v.index).index(r) for r in ok], s=60, facecolors="none",
               edgecolors=COL[k], marker=MRK[k], lw=1, zorder=4, label=f"{LABF[k]} ({len(ok)} regions)")
ax.set_yticks(yy, [NAME[r].title().replace("D'Aosta", "d'Aosta") for r in v.index])  # PATCH_D14I_FIG2_261031; ax.set_xlabel(f"N06A packs per 1,000 inhabitants, {Y}")
ax.grid(axis="x", color=GRID, lw=0.6); ax.set_axisbelow(True)
ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=6.5)  # PATCH_D14I_FIG_261031
savefig(fig, "d14_fig5_indicatore_regioni")

# Figura 6: quota di popolazione coperta dalle regioni integrabili, per anno e percorso  # PATCH_D14I_FIG_261031
fig, ax = plt.subplots(figsize=(3.5, 2.3))
for k in PATHS:
    s = nat[nat.PERCORSO == LAB[k]]
    ax.plot(s.ANNO, s["POP_COPERTA_%"], color=COL[k], marker=MRK[k], ms=4, lw=2 if k == "K_H" else 1.2, label=LABF[k])
    for x_, y_, n_ in zip(s.ANNO, s["POP_COPERTA_%"], s.REGIONI):
        ax.annotate(str(n_), (x_, y_), textcoords="offset points", xytext=(0, -10 if k == "K_R1" else 5),  # PATCH_D14I_FIG2_261031
                    ha="center", fontsize=6, color=INK2)
ax.set_xticks(YEARS4); ax.set_ylim(-8, 112); ax.set_ylabel("population covered, %")
ax.set_title("label = usable regions (out of 20)", loc="left", fontsize=7, color=INK2)
ax.grid(axis="y", color=GRID, lw=0.6); ax.legend(frameon=False, fontsize=6.5, loc="center right")
_show(
savefig(fig, "d14_fig6_copertura")
)


# ====================================================================================================
# ## 7. Esempio di join (anno 2019): le chiavi come arrivano dalle fonti e il risultato dell'unione
# 
# **Tabella A**: per cinque unità (Lombardia, Valle d'Aosta, Bolzano, Trentino-Alto Adige, Lazio come controllo) codice e
# nome territoriale come compaiono nei file grezzi di AIFA, MINIS (posti letto) e ISTAT (`DCIS_DECESSI`), il codice MEDITA
# e l'esito del join a tre fonti con ciascun percorso. **Tabella B**: i valori uniti (confezioni N06A da AIFA, posti letto
# da MINIS, popolazione da ISTAT, confezioni per 1000 abitanti) con MEDITA e con i nomi normalizzati (join a stella su
# AIFA: un valore manca se la sua fonte non si abbina alla riga AIFA). Output: fogli `7_join_A` e `7_join_B` dell'xlsx e
# `d14_tab_join_A/B_<data>.tex` (booktabs, amssymb).
# ====================================================================================================
# ---- cella (PATCH_D14I_JOIN_261031)
# PATCH_D14I_JOIN_261031: sezione 7, esempio di join (tabelle A e B, xlsx + LaTeX)
EX_YEAR = 2019
EX_UNITS = ["ITC4", "ITC2", "ITH1", "ITH0", "ITI4"]      # Lombardia, Valle d'Aosta, Bolzano, Trentino-Alto Adige, Lazio
EX_SRC = [("AIFA", "AIFA"), ("MINIS", "MINIS"), ("ISTAT", "ISTAT_DECESSI")]
EX_LABEL = {"ITC4": "Lombardia", "ITC2": "Valle d'Aosta", "ITH1": "P.A. Bolzano", "ITH0": "Trentino-Alto Adige", "ITI4": "Lazio"}

# chiavi grezze ISTAT della regione Trentino-Alto Adige (ITDA): RK tiene solo le 21 unita' di rilevazione,
# quindi si rileggono le sole chiavi del grezzo AVQ (stessi codici e nomi di DECESSI: abbinamento R0 100%, sez. 2)
_f = RAW["ISTAT"] / "DCCV_AVQ_PERSONE.csv"; _sep, _enc = sniff(_f); _taa = set()
for ch in pd.read_csv(_f, sep=_sep, dtype=str, encoding=_enc, chunksize=CHUNK, low_memory=False,
                      usecols=["REF_AREA", "REF_AREA_DESC", "TIME_PERIOD"]):
    s = ch[(ch.REF_AREA == "ITDA") & (ch.TIME_PERIOD == str(EX_YEAR))]
    _taa.update(map(tuple, s[["REF_AREA", "REF_AREA_DESC"]].drop_duplicates().fillna("").values.tolist()))
ctrl(f"esempio join: chiave ISTAT del Trentino-Alto Adige nel {EX_YEAR}", sorted(_taa))

def raw_key(src, u):
    if src == "ISTAT_DECESSI" and u == "ITH0":
        return (", ".join(sorted({c for c, _ in _taa})) or "—", " | ".join(sorted({n for _, n in _taa})) or "—")
    d = RK[src][(RK[src].UNIT == u) & (RK[src].ANNO == EX_YEAR)]
    if d.empty:
        return ("—", "—")
    return (", ".join(sorted(set(d.CODE))), " | ".join(sorted(set(d.NAME.dropna()))))

def joins(key, u):
    """Il join a tre fonti (AIFA-MINIS-ISTAT) riesce per l'unita' nell'anno con la chiave del percorso?"""
    if key == "K_H":
        return all((u, EX_YEAR) in idx for idx in (N06A.index, pl_h.index, POP.index))
    if u == "ITH0":                       # AIFA e MINIS grezzi non hanno la riga regionale
        return False
    vals = [set(RK[s].loc[(RK[s].UNIT == u) & (RK[s].ANNO == EX_YEAR), key].dropna()) for _, s in EX_SRC]
    return bool(vals[0]) and bool(vals[0] & vals[1]) and bool(vals[0] & vals[2])

def pair_ok(key, u, b):
    """Il valore della fonte b si abbina alla riga AIFA (percorso R1, join a stella su AIFA)?"""
    if u == "ITH0":
        return False
    A = set(RK["AIFA"].loc[(RK["AIFA"].UNIT == u) & (RK["AIFA"].ANNO == EX_YEAR), key].dropna())
    B = set(RK[b].loc[(RK[b].UNIT == u) & (RK[b].ANNO == EX_YEAR), key].dropna())
    return bool(A & B)

YES, NO = "sì", "no"
tabA, tabB = [], []
for u in EX_UNITS:
    r = {"REGIONE": EX_LABEL.get(u, NAME[u]), "ANNO": EX_YEAR}
    for lab, src in EX_SRC:
        c, n = raw_key(src, u)
        r[f"{lab}_CODICE_GREZZO"], r[f"{lab}_NOME_GREZZO"] = c, n
    r["MEDITA_CODICE_REGIONE"] = u + (" (ITH1 + ITH2)" if u == "ITH0" else "")
    for k in PATHS:
        r[f"JOIN_{LAB[k]}"] = YES if joins(k, u) else NO
    tabA.append(r)

    n06 = N06A.get((u, EX_YEAR), np.nan); bed = pl_h["TOTALE_POSTI_LETTO"].get((u, EX_YEAR), np.nan)
    pop = POP.get((u, EX_YEAR), np.nan)
    b = {"REGIONE": EX_LABEL.get(u, NAME[u]), "ANNO": EX_YEAR,
         "H_N06A_CONF": n06, "H_POSTI_LETTO": bed, "H_POPOLAZIONE": pop, "H_N06A_X1000": n06 / pop * 1000}
    has_aifa = u != "ITH0"
    r1_n06 = n06 if has_aifa else np.nan
    r1_bed = bed if pair_ok("K_R1", u, "MINIS") else np.nan
    r1_pop = pop if pair_ok("K_R1", u, "ISTAT_DECESSI") else np.nan
    b.update({"R1_N06A_CONF": r1_n06, "R1_POSTI_LETTO": r1_bed, "R1_POPOLAZIONE": r1_pop,
              "R1_N06A_X1000": r1_n06 / r1_pop * 1000 if pd.notna(r1_n06) and pd.notna(r1_pop) else np.nan})
    tabB.append(b)
tabA, tabB = pd.DataFrame(tabA), pd.DataFrame(tabB)
print(tabA.to_string(index=False)); print()
print(tabB.to_string(index=False))

# LaTeX (booktabs + amssymb). Le celle senza valore sono "--".
def tex(s):
    s = str(s)
    for a, b in [("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"), ("_", r"\_"),
                 ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}"),
                 ("`", r"\textasciigrave{}")]:
        s = s.replace(a, b)
    return s.replace("—", "--")
def fnum(x, d=0):
    return "--" if pd.isna(x) else f"{x:,.{d}f}".replace(",", "\\,")
mark = {YES: r"$\checkmark$", NO: r"$\times$"}
LA = [r"% Tabella A - chiavi territoriali grezze e codice MEDITA (" + str(EX_YEAR) + r"); richiede booktabs, amssymb",
      r"\begin{tabular}{l ll ll ll l ccc}", r"\toprule",
      r" & \multicolumn{2}{c}{AIFA} & \multicolumn{2}{c}{MINIS} & \multicolumn{2}{c}{ISTAT} & MEDITA & \multicolumn{3}{c}{Join} \\",
      r"\cmidrule(lr){2-3}\cmidrule(lr){4-5}\cmidrule(lr){6-7}\cmidrule(lr){9-11}",
      r"Region & code & name & code & name & code & name & \texttt{CODICE\_REGIONE} & R0 & R1 & H \\", r"\midrule"]
for _, r in tabA.iterrows():
    LA.append(" & ".join([tex(r.REGIONE)] + [tex(r[f"{l}_{c}"]) for l, _ in EX_SRC for c in ("CODICE_GREZZO", "NOME_GREZZO")]
                         + [r"\texttt{" + tex(r.MEDITA_CODICE_REGIONE) + "}"] + [mark[r[f"JOIN_{LAB[k]}"]] for k in PATHS]) + r" \\")
LA += [r"\bottomrule", r"\end{tabular}"]
LB = [r"% Tabella B - risultato del join (" + str(EX_YEAR) + r"): H = MEDITA, R1 = nomi normalizzati (join a stella su AIFA)",
      r"\begin{tabular}{l rrrr rrrr}", r"\toprule",
      r" & \multicolumn{4}{c}{H (MEDITA)} & \multicolumn{4}{c}{R1 (normalised names)} \\",
      r"\cmidrule(lr){2-5}\cmidrule(lr){6-9}",
      r"Region & N06A packs & beds & population & per 1000 & N06A packs & beds & population & per 1000 \\", r"\midrule"]
for _, r in tabB.iterrows():
    LB.append(" & ".join([tex(r.REGIONE)] + [fnum(r[f"{p}_{c}"], d) for p in ("H", "R1") for c, d in
                         [("N06A_CONF", 0), ("POSTI_LETTO", 0), ("POPOLAZIONE", 0), ("N06A_X1000", 1)]]) + r" \\")
LB += [r"\bottomrule", r"\end{tabular}"]
(OUT / f"d14_tab_join_A_{STAMP}.tex").write_text("\n".join(LA) + "\n", encoding="utf-8")
(OUT / f"d14_tab_join_B_{STAMP}.tex").write_text("\n".join(LB) + "\n", encoding="utf-8")
print("Creati:", f"d14_tab_join_A_{STAMP}.tex", f"d14_tab_join_B_{STAMP}.tex")

# ====================================================================================================
# ## Limiti (da dichiarare)
# 
# - **Mese**: MEDITA non armonizza il mese (AIFA `MESE` `1`/`01`, ISTAT `MONTH_DEATH` `JAN`…): il join mensile va fatto
#   nell'analisi.
# - **Vuoti AIFA**: nel 2018 la fonte scrive `0`, dal 2019 lascia il campo vuoto; MEDITA lo conserva (principio: segue la
#   fonte). Le somme non cambiano.
# - **Popolazione**: stimata da `DCIS_DECESSI` (morti / tasso), non da una tabella di popolazione (non presente nel
#   catalogo): l'arrotondamento del tasso a una cifra decimale pesa per meno dell'1%.
# - **Schema (sez. 1)**: letti solo i CSV; i fogli di calcolo sono contati a parte (foglio `schema_non_letti`).
# ====================================================================================================
# ---- cella 22
env = pd.DataFrame([("python", platform.python_version()), ("pandas", pd.__version__),
                    ("matplotlib", matplotlib.__version__), ("eseguito", time.strftime("%Y-%m-%d %H:%M")),
                    ("snapshot", json.dumps(SNAP)), ("MEDITA", str(HOME)),
                    ("figure", ", ".join(f"{n}_{STAMP}.pdf/.png" for n in FIGS))], columns=["voce", "valore"])
fout = OUT / f"d14_integrazione_{STAMP}.xlsx"
with pd.ExcelWriter(fout, engine="openpyxl") as wr:
    env.to_excel(wr, sheet_name="env", index=False)
    pd.DataFrame(CTRL).to_excel(wr, sheet_name="controlli", index=False)
    schema_sum.to_excel(wr, sheet_name="1_schema_sintesi", index=False)
    schema.to_excel(wr, sheet_name="1_schema_colonne", index=False)
    skipped.to_excel(wr, sheet_name="1_schema_non_letti", index=False)
    chiavi_es.to_excel(wr, sheet_name="2_chiavi_grezze", index=False)
    link.to_excel(wr, sheet_name="2_abbinamenti", index=False)
    lost.to_excel(wr, sheet_name="2_unita_perse", index=False)
    compl.to_excel(wr, sheet_name="3_completezza", index=False)
    pd.concat({LAB[k]: g.unstack() for k, g in GRID3.items()}).reset_index() \
      .rename(columns={"level_0": "PERCORSO"}).to_excel(wr, sheet_name="3_griglia", index=False)
    serie_sum.reset_index().to_excel(wr, sheet_name="4_serie_sintesi", index=False)
    serie.to_excel(wr, sheet_name="4_serie_unita", index=False)
    cons.to_excel(wr, sheet_name="5_conservazione", index=False)
    trent.to_excel(wr, sheet_name="5_trentino", index=False)
    nat.to_excel(wr, sheet_name="6_italia", index=False)
    ind_w.reset_index().to_excel(wr, sheet_name="6_indicatore_H", index=False)
    tabA.to_excel(wr, sheet_name="7_join_A", index=False)  # PATCH_D14I_JOIN_261031
    tabB.to_excel(wr, sheet_name="7_join_B", index=False)
print("Creato:", fout)

