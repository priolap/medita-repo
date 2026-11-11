"""
queries.py - carico di lavoro del benchmark A1 (storage layer).

Ogni query e' legata a una funzione della piattaforma o a un esperimento del paper.
Le query per-tabella sono template: i parametri (anni, colonne di misura, colonna
categoriale) vengono ricavati una volta da DuckDB e salvati in results/params.json,
cosi' tutti gli engine eseguono esattamente la stessa SQL.
"""

# Regioni usate negli slice/dice (NUTS-2)
SLICE_REGION = "ITG2"                       # Sardegna
DICE_REGIONS = ("ITG2", "ITC4", "ITF3")     # Sardegna, Lombardia, Campania

# Join cross-source (Q7): una tabella MINIS e una ISTAT con ANNO e CODICE_REGIONE.
# J2_FILTER seleziona le righe di totale ISTAT per non sommare le sottocategorie.
J1_TABLE, J1_MEASURE = "DISP_POSLETTO_REGI", "TOTALE_POSTI_LETTO"
J2_TABLE, J2_MEASURE = "DCIS_DECESSI", "OBS_VALUE"
J2_FILTER = "CAST(SEX AS VARCHAR) = '9'"  # PATCH_BENCH_ALIM_261029: ID ISTAT 2026 (prima SESSO)

# Descrizione delle query (finisce nel report)
DESCRIPTIONS = {
    "Q1": "Lettura completa della tabella in pandas (pattern attuale di load_data)",
    "Q2": "Catalogo: numero di tabelle e colonne (home_summary)",
    "Q3": "Slice: ultimi 5 anni, una regione (Esploratore Dati)",
    "Q4": "Dice: ultimi 3 anni, 3 regioni, proiezione (Esploratore / Forecaster)",
    "Q5": "Roll-up: SUM delle misure per ANNO, CODICE_REGIONE (generate_db_ts)",
    "Q6": "Conteggio righe per ANNO (Infografiche, Fig. 2)",
    "Q7": "Join cross-source MINIS x ISTAT su ANNO, CODICE_REGIONE (caso d'uso T14)",
    "Q8": "Group-by sulla colonna di testo con piu' valori distinti, top-20 (tabella L)",  # PATCH_A1_V2
    "Q9": "Nulli per colonna: COUNT(col) vs COUNT(*) (missingness T15)",
}


def q(name):
    return f'"{name}"'


def per_table_queries(t, p):
    """Query per la tabella t con parametri p (da params.json). Restituisce {id: sql}."""
    out = {}
    tq = q(t)
    y1 = p["max_anno"]
    out["Q1"] = f"SELECT * FROM {tq}"
    out["Q3"] = (f"SELECT * FROM {tq} WHERE ANNO BETWEEN {y1 - 4} AND {y1} "
                 f"AND CODICE_REGIONE = '{SLICE_REGION}'")
    cols = ["ANNO", "CODICE_REGIONE"]
    if p["cat_col"]:
        cols.append(q(p["cat_col"]))
    if p["measures"]:
        cols.append(q(p["measures"][0]))
    regs = ", ".join(f"'{r}'" for r in DICE_REGIONS)
    out["Q4"] = (f"SELECT {', '.join(cols)} FROM {tq} WHERE ANNO >= {y1 - 2} "
                 f"AND CODICE_REGIONE IN ({regs})")
    if p["measures"]:
        sums = ", ".join(f"SUM({q(m)}) AS {q('S_' + m)}" for m in p["measures"][:10])
        out["Q5"] = (f"SELECT ANNO, CODICE_REGIONE, {sums} FROM {tq} "
                     f"GROUP BY ANNO, CODICE_REGIONE")
    out["Q6"] = f"SELECT ANNO, COUNT(*) AS N FROM {tq} GROUP BY ANNO ORDER BY ANNO"
    if p["cat_col"]:
        m = f", SUM({q(p['measures'][0])}) AS S" if p["measures"] else ""
        out["Q8"] = (f"SELECT {q(p['cat_col'])} AS K, COUNT(*) AS N{m} FROM {tq} "
                     f"GROUP BY {q(p['cat_col'])} ORDER BY N DESC LIMIT 20")
    counts = ", ".join(f"COUNT({q(c)})" for c in p["columns"])
    out["Q9"] = f"SELECT COUNT(*), {counts} FROM {tq}"
    return out


def join_query():
    return f"""
WITH a AS (
  SELECT ANNO, CODICE_REGIONE, SUM({q(J1_MEASURE)}) AS X
  FROM {q(J1_TABLE)} GROUP BY ANNO, CODICE_REGIONE),
b AS (
  SELECT ANNO, CODICE_REGIONE, SUM({q(J2_MEASURE)}) AS Y
  FROM {q(J2_TABLE)} WHERE {J2_FILTER} GROUP BY ANNO, CODICE_REGIONE)
SELECT a.ANNO, a.CODICE_REGIONE, a.X, b.Y
FROM a JOIN b ON a.ANNO = b.ANNO AND a.CODICE_REGIONE = b.CODICE_REGIONE
ORDER BY a.ANNO, a.CODICE_REGIONE
"""
