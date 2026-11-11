#!/usr/bin/env python3
"""
make_lakehouse_checklist.py - Task A2 (P2): checklist delle feature lakehouse, implementate vs mancanti.

Legge i risultati del benchmark A1 in results/ e produce:
  results/p2_checklist.csv   una riga per feature x configurazione, con stato ed evidenza
  results/p2_checklist.md    tabella leggibile + note sulle evidenze
  results/p2_checklist.tex   tabella LaTeX compatta (stati)

Stato: "Si'" / "Parziale" / "No".  Evidenza:
  "misurata"      = dimostrata da un'operazione eseguita nel benchmark (lakehouse_ops, footprint, ...)
  "documentata"   = proprieta' nota del formato/motore, non esercitata dal benchmark
Le righe "Piattaforma MEDITA" descrivono la pipeline attuale, indipendentemente dal motore.

Uso: python make_lakehouse_checklist.py   (viene chiamato anche da run_repro.py alla fine)
"""
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE / "results"
CONFIGS = ["SQLite (MEDITA attuale)", "DuckDB", "Parquet + DuckDB", "Delta Lake + DuckDB"]


def read_csv(name):
    p = R / name
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def lake_ops():
    """Operazioni Delta: da repro_lakehouse.csv (tutti i run) o, in mancanza, da lakehouse_ops.csv."""
    # PATCH_A1_CLOSE: unione delle due fonti; repro_lakehouse.csv (piu' run) ha la precedenza
    out = {r["operation"]: {"ok": r["ok"] == "True", "txt": f"{float(r['seconds']) * 1000:.0f} ms, {r['detail']}"}
           for r in read_csv("lakehouse_ops.csv")}
    out.update({r["operation"]: {"ok": r["ok_all"] == "True", "txt": f"{int(r['n_ok'])}/{int(r['n'])} run riusciti, "
                f"mediana {float(r['median_s']) * 1000:.0f} ms"} for r in read_csv("repro_lakehouse.csv")})
    return out


def footprint():
    out = {}
    for r in read_csv("summary_engines.csv"):
        try:
            out[r["engine"]] = (float(r["footprint_GB"]), float(r["ratio_vs_txt"]), float(r["ingest_min"]))
        except (KeyError, ValueError):
            pass
    return out


def main():
    ops = lake_ops()
    fp = footprint()
    dup = [r for r in read_csv("duplicates.csv") if r.get("identical") == "True"]
    n_dup_tables = sum(int(r["n"]) - 1 for r in dup)
    notes = read_csv("engine_notes.csv")
    reader = notes[-1]["reader"] if notes else "n.d."

    def op(name, fallback="non eseguita"):
        o = ops.get(name)
        if not o:
            return ("No", "misurata", fallback)
        return ("Si'" if o["ok"] else "No", "misurata", o["txt"])

    def fpt(engine):
        if engine not in fp:
            return "n.d."
        gb, ratio, mins = fp[engine]
        return f"{gb:.2f} GB ({ratio:.2f}x il testo), ingestion {mins:.1f} min"

    S, D, P, L = CONFIGS
    rows = []

    def add(feature, cells):
        for cfg, (state, ev, detail) in zip(CONFIGS, cells):
            rows.append({"area": "Storage", "feature": feature, "configurazione": cfg,
                         "stato": state, "evidenza": ev, "dettaglio": detail})

    add("Formato dei dati aperto", [
        ("Parziale", "documentata", "file SQLite documentato ma leggibile solo tramite libreria SQLite"),
        ("Parziale", "documentata", "file .duckdb nativo, leggibile solo da DuckDB"),
        ("Si'", "documentata", "Apache Parquet, leggibile da qualunque motore (pandas, Spark, Arrow, DuckDB)"),
        ("Si'", "documentata", "Parquet + transaction log JSON aperto (protocollo Delta)")])
    add("Storage colonnare e compressione", [
        ("No", "misurata", fpt("sqlite")), ("Si'", "misurata", fpt("duckdb")),
        ("Si'", "misurata", fpt("parquet")), ("Si'", "misurata", fpt("delta"))])
    add("Transazioni ACID", [
        ("Si'", "documentata", "transazioni su file singolo, un solo scrittore alla volta"),
        ("Si'", "documentata", "transazioni su file singolo"),
        ("No", "documentata", "file indipendenti, nessun log: scritture parziali possibili"),
        op("append_transazionale")])
    add("Schema enforcement", [
        ("Parziale", "documentata", "type affinity: una colonna INTEGER accetta anche testo"),
        ("Si'", "documentata", "tipi rigidi sulle tabelle"),
        ("Parziale", "documentata", "schema per singolo file, nessun controllo tra file della stessa tabella"),
        op("schema_enforcement")])
    add("Schema evolution", [
        ("Parziale", "documentata", "ALTER TABLE ADD COLUMN, senza storico"),
        ("Parziale", "documentata", "ALTER TABLE, senza storico"),
        ("Parziale", "documentata", "solo in lettura (union_by_name), nessuna gestione delle versioni di schema"),
        op("schema_evolution")])
    add("Time travel (lettura di versioni precedenti)", [
        ("No", "documentata", "solo copie manuali del file"), ("No", "documentata", "solo copie manuali del file"),
        ("No", "documentata", "solo cartelle-snapshot manuali"), op("time_travel")])
    add("Rollback a una versione precedente", [
        ("No", "documentata", "ripristino da backup"), ("No", "documentata", "ripristino da backup"),
        ("No", "documentata", "ripristino da backup"), op("rollback_restore")])
    add("Separazione storage / compute", [
        ("No", "documentata", "dati dentro il file del motore"), ("No", "documentata", "dati dentro il file del motore"),
        ("Si'", "misurata", "file Parquet interrogati da DuckDB in memoria"),
        ("Si'", "misurata", f"tabelle Delta interrogate da DuckDB (lettore: {reader})")])
    add("Analisi e ML sugli stessi dati senza copie", [
        ("Parziale", "misurata", "via SQL o pandas; la piattaforma oggi carica tabelle intere in pandas (Q1)"),
        ("Si'", "misurata", "SQL analitico + export Arrow/pandas"),
        ("Si'", "misurata", "SQL analitico + lettura diretta da pandas/Arrow/Spark"),
        ("Si'", "misurata", "SQL analitico + lettura diretta da pandas/Arrow/Spark")])

    plat = [
        ("Catalogo dei metadati", "Parziale",
         "catalogo info_<FONTE> per fonte; " + (f"{n_dup_tables} tabelle in output/ non presenti nel catalogo corrente "
                                              f"(nomi pre-ridenominazione, contenuto identico)" if dup else
                                              "nessuna tabella duplicata rilevata")),
        ("Versioning dei dati grezzi", "Parziale", "snapshot datati delle sorgenti (cartelle AAAAMMGG), gestiti a mano"),
        ("Dati non strutturati nello stesso sistema", "Si'",
         "corpus di news (pickle) e vector store Chroma accanto alle tabelle"),
        ("Lineage sorgente -> tabella", "Parziale", "ricostruibile dal catalogo e dai log, non tracciato automaticamente"),
    ]
    for feat, state, det in plat:
        rows.append({"area": "Piattaforma MEDITA", "feature": feat, "configurazione": "pipeline attuale",
                     "stato": state, "evidenza": "misurata" if "tabelle in output" in det else "documentata",
                     "dettaglio": det})

    R.mkdir(exist_ok=True)
    with (R / "p2_checklist.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    feats = list(dict.fromkeys(r["feature"] for r in rows if r["area"] == "Storage"))
    cell = {(r["feature"], r["configurazione"]): r for r in rows}
    md = ["# P2 - Checklist feature lakehouse", "",
          "Stato per configurazione. (m) = dimostrata nel benchmark A1, (d) = proprieta' documentata.", "",
          "| Feature | " + " | ".join(CONFIGS) + " |", "|---|" + "---|" * len(CONFIGS)]
    for ft in feats:
        md.append(f"| {ft} | " + " | ".join(
            f"{cell[(ft, c)]['stato']} ({cell[(ft, c)]['evidenza'][0]})" for c in CONFIGS) + " |")
    md += ["", "## Piattaforma MEDITA (indipendente dal motore)", "", "| Feature | Stato | Dettaglio |", "|---|---|---|"]
    for r in rows:
        if r["area"] == "Piattaforma MEDITA":
            md.append(f"| {r['feature']} | {r['stato']} | {r['dettaglio']} |")
    md += ["", "## Evidenze", ""]
    for r in rows:
        if r["area"] == "Storage":
            md.append(f"- **{r['feature']} - {r['configurazione']}**: {r['stato']} ({r['evidenza']}) - {r['dettaglio']}")
    (R / "p2_checklist.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    sym = {"Si'": r"\checkmark", "Parziale": r"$\sim$", "No": r"--"}
    tex = [r"\begin{table}", r"\centering", r"\caption{Feature lakehouse per configurazione di storage "
           r"(\checkmark{} presente, $\sim$ parziale, -- assente; $^m$ dimostrata nel benchmark).}",
           r"\label{tab:lakehouse_checklist}", r"\begin{tabular}{l" + "c" * len(CONFIGS) + "}", r"\toprule",
           "Feature & " + " & ".join(c.replace("&", r"\&") for c in CONFIGS) + r" \\", r"\midrule"]
    for ft in feats:
        cells = []
        for c in CONFIGS:
            r = cell[(ft, c)]
            cells.append(sym[r["stato"]] + ("$^m$" if r["evidenza"] == "misurata" else ""))
        tex.append(f"{ft} & " + " & ".join(cells) + r" \\")
    tex += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
    (R / "p2_checklist.tex").write_text("\n".join(tex) + "\n", encoding="utf-8")
    print(f"P2: {len(feats)} feature di storage x {len(CONFIGS)} configurazioni -> results/p2_checklist.*")


if __name__ == "__main__":
    main()
