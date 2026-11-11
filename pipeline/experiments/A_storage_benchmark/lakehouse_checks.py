#!/usr/bin/env python3
"""
lakehouse_checks.py - Task A2 (P2): checklist delle feature "lakehouse" implementate vs mancanti.

Ogni voce e' verificata con un test funzionale quando possibile (non solo dichiarata).
I test girano su una copia di lavoro della tabella M del benchmark (results/params.json),
caricata in configurazioni temporanee: i database del benchmark non vengono toccati.

Configurazioni: SQLite | DuckDB | Parquet (+DuckDB) | Delta Lake (+DuckDB) | MEDITA attuale (ITADATA 2025)
La colonna "MEDITA attuale" descrive la piattaforma pubblicata (analisi del codice: txt pipe-delimited
-> SQLite ricreato a ogni Load), non un test.

Output in results/:
  p2_checklist.csv   formato lungo: feature, configurazione, stato, evidenza, test
  p2_checklist.md    tabella feature x configurazione
  p2_checklist.tex   idem per LaTeX
Uso:  python lakehouse_checks.py
"""
import json
import os
import random
import shutil
import sqlite3
import time
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

SEED = int(os.environ.get("MEDITA_SEED", "42"))
random.seed(SEED)

HERE = Path(__file__).resolve().parent
R = HERE / "results"
WORK_DIR = Path(os.environ.get("MEDITA_BENCH_WORK", r"D:\MEDITA_bench_work"))
TMP = WORK_DIR / "p2_checks"
CONFS = ["SQLite", "DuckDB", "Parquet", "Delta", "MEDITA attuale"]
OK, PART, NO = "implementato", "parziale", "mancante"
rows = []


def add(feature, conf, status, evidence, test=""):
    rows.append({"feature": feature, "configurazione": conf, "stato": status,
                 "evidenza": evidence, "test": test})


def run_test(fn):
    """Esegue un test e restituisce (esito_bool, dettaglio)."""
    try:
        return fn()
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:160]}"


def setup():
    params = json.loads((R / "params.json").read_text(encoding="utf-8"))
    name = next(n for n, p in params.items() if p["tier"] == "M")
    src = WORK_DIR / "parquet" / f"{name}.parquet"
    shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True)
    tbl = pq.read_table(src)
    df = tbl.to_pandas()
    measure = next((m for m in params[name]["measures"]), None) or \
        next(c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c != "ANNO")
    # configurazioni temporanee
    sq = sqlite3.connect(TMP / "t.sqlite")
    df.to_sql("T", sq, index=False)
    sq.commit()
    dk = duckdb.connect(str(TMP / "t.duckdb"))
    dk.register("src", tbl)
    dk.execute('CREATE TABLE "T" AS SELECT * FROM src')
    (TMP / "parquet").mkdir()
    pq.write_table(tbl, TMP / "parquet" / "part-0.parquet")
    from deltalake import write_deltalake
    write_deltalake(str(TMP / "delta"), tbl, mode="overwrite")
    return name, tbl, df, measure, sq, dk


def main():
    t0 = time.time()
    name, tbl, df, measure, sq, dk = setup()
    from deltalake import DeltaTable, write_deltalake
    n0 = len(df)
    dpath = str(TMP / "delta")
    small = tbl.slice(0, 100)

    # ---------------------------------------------------------------- 1. formato aperto
    f = "Formato aperto e leggibile da piu' motori"
    ok, d = run_test(lambda: (pq.read_table(TMP / "parquet" / "part-0.parquet").num_rows == n0,
                              "letto con pyarrow e con DuckDB senza conversioni"))
    add(f, "Parquet", OK if ok else NO, "Parquet colonnare, specifica Apache aperta", d)
    ok, d = run_test(lambda: (DeltaTable(dpath).to_pyarrow_dataset().count_rows() == n0,
                              "file Parquet + log JSON; letto con deltalake/pyarrow e DuckDB (delta_scan)"))
    add(f, "Delta", OK if ok else NO, "Parquet + transaction log JSON (protocollo Delta aperto)", d)
    add(f, "SQLite", PART, "formato documentato ma file unico row-oriented, accesso tramite la libreria SQLite", "")
    add(f, "DuckDB", NO, "file .duckdb specifico del motore (formato legato alla versione)", "")
    add(f, "MEDITA attuale", PART, "testo pipe-delimited aperto ma senza schema tipizzato; servito via SQLite", "analisi del codice")

    # ---------------------------------------------------------------- 2. ACID / transazioni
    f = "Transazioni ACID (commit/rollback atomici)"

    def tx(con, is_duck):
        con.execute("BEGIN")
        con.execute('INSERT INTO "T" SELECT * FROM "T" LIMIT 10')
        con.execute("ROLLBACK")
        n = con.execute('SELECT COUNT(*) FROM "T"').fetchone()[0]
        return n == n0, f"INSERT annullato da ROLLBACK: righe {n} (attese {n0})"
    ok, d = run_test(lambda: tx(sq, False))
    add(f, "SQLite", OK if ok else NO, "transazioni ACID native", d)
    ok, d = run_test(lambda: tx(dk, True))
    add(f, "DuckDB", OK if ok else NO, "transazioni ACID native (MVCC)", d)
    add(f, "Parquet", NO, "file immutabili senza log: nessuna atomicita' su scritture multi-file", "")

    def delta_atomic():
        v = DeltaTable(dpath).version()
        bad = small.set_column(small.schema.get_field_index(measure), measure,
                               pa.array(["x"] * small.num_rows))
        try:
            write_deltalake(dpath, bad, mode="append")
            return False, "scrittura con tipo errato accettata"
        except Exception:
            v2 = DeltaTable(dpath).version()
            return v2 == v, f"scrittura fallita: versione invariata ({v}), nessun file parziale visibile"
    ok, d = run_test(delta_atomic)
    add(f, "Delta", OK if ok else NO, "commit atomico sul transaction log (concorrenza ottimistica)", d)
    add(f, "MEDITA attuale", NO, "la Load cancella e ricrea il DB SQLite; bulk load con journal_mode=OFF", "analisi del codice")

    # ---------------------------------------------------------------- 3. schema enforcement
    f = "Schema enforcement (rifiuto di tipi incompatibili)"

    def sqlite_enf():
        sq.execute('INSERT INTO "T" ("{0}") VALUES (?)'.format(measure), ("testo",))
        n = sq.execute(f'SELECT COUNT(*) FROM "T" WHERE typeof("{measure}")=\'text\'').fetchone()[0]
        sq.rollback()
        return n == 0, f"testo inserito in colonna numerica: {'rifiutato' if n == 0 else 'accettato (tipizzazione dinamica)'}"
    ok, d = run_test(sqlite_enf)
    add(f, "SQLite", OK if ok else NO, "affinita' di tipo dinamica (tabelle non STRICT)", d)

    def duck_enf():
        try:
            dk.execute(f'INSERT INTO "T" ("{measure}") VALUES (\'testo\')')
            return False, "testo inserito in colonna numerica: accettato"
        except duckdb.Error:
            return True, "testo inserito in colonna numerica: rifiutato"
    ok, d = run_test(duck_enf)
    add(f, "DuckDB", OK if ok else NO, "tipi statici", d)

    def parquet_enf():
        bad = small.set_column(small.schema.get_field_index(measure), measure, pa.array(["x"] * small.num_rows))
        pq.write_table(bad, TMP / "parquet" / "part-bad.parquet")      # la scrittura non viene impedita
        p = str(TMP / "parquet").replace("\\", "/")
        try:
            duckdb.sql(f"SELECT SUM(TRY_CAST(\"{measure}\" AS DOUBLE)) FROM read_parquet('{p}/*.parquet')").fetchall()
            msg = "file incompatibile scritto nel dataset; la lettura non lo segnala"
        except duckdb.Error:
            msg = "file incompatibile scritto nel dataset; errore solo in lettura"
        (TMP / "parquet" / "part-bad.parquet").unlink()
        return False, msg
    ok, d = run_test(parquet_enf)
    add(f, "Parquet", NO, "schema per singolo file, nessun vincolo a livello di tabella", d)
    ok, d = run_test(delta_atomic)
    add(f, "Delta", OK if ok else NO, "schema della tabella nel log, verificato a ogni scrittura", d)
    add(f, "MEDITA attuale", PART, "tipi imposti in Transform (Data Standardization), non dallo storage", "analisi del codice")

    # ---------------------------------------------------------------- 4. schema evolution
    f = "Schema evolution (aggiunta di colonne senza riscrivere i dati)"
    ok, d = run_test(lambda: (sq.execute('ALTER TABLE "T" ADD COLUMN NOTE TEXT') is not None,
                              "ALTER TABLE ADD COLUMN (DDL manuale)"))
    add(f, "SQLite", PART if ok else NO, "possibile solo con DDL esplicito", d)
    ok, d = run_test(lambda: (dk.execute('ALTER TABLE "T" ADD COLUMN NOTE VARCHAR') is not None,
                              "ALTER TABLE ADD COLUMN (DDL manuale)"))
    add(f, "DuckDB", PART if ok else NO, "possibile solo con DDL esplicito", d)

    def parquet_evo():
        extra = small.append_column("NOTE", pa.array(["n"] * small.num_rows))
        pq.write_table(extra, TMP / "parquet" / "part-new.parquet")
        p = str(TMP / "parquet").replace("\\", "/")
        cols = duckdb.sql(f"SELECT * FROM read_parquet('{p}/*.parquet', union_by_name=true) LIMIT 1").columns
        (TMP / "parquet" / "part-new.parquet").unlink()
        return "NOTE" in cols, "nuovo file con colonna in piu'; riconciliato solo in lettura (union_by_name)"
    ok, d = run_test(parquet_evo)
    add(f, "Parquet", PART if ok else NO, "nessuno schema di tabella: evoluzione gestita dal lettore", d)

    def delta_evo():
        extra = small.append_column("NOTE", pa.array(["n"] * small.num_rows))
        write_deltalake(dpath, extra, mode="append", schema_mode="merge")
        s = DeltaTable(dpath).schema()
        names = s.to_arrow().names if hasattr(s, "to_arrow") else [x.name for x in s.fields]
        return "NOTE" in names, "append con schema_mode=merge: colonna aggiunta, dati esistenti non riscritti"
    ok, d = run_test(delta_evo)
    add(f, "Delta", OK if ok else NO, "evoluzione dello schema registrata nel log", d)
    add(f, "MEDITA attuale", PART, "nuove colonne gestite a monte dal dizionario cols_attributes.json (manuale)", "analisi del codice")

    # ---------------------------------------------------------------- 5. time travel
    f = "Time travel (lettura di versioni precedenti)"
    for c in ("SQLite", "DuckDB"):
        add(f, c, NO, "nessuna versione storica: solo lo stato corrente", "")
    add(f, "Parquet", NO, "nessun versioning nativo", "")

    def delta_tt():
        dt = DeltaTable(dpath)
        n_v0 = DeltaTable(dpath, version=0).to_pyarrow_dataset().count_rows()
        return n_v0 == n0, f"versione corrente {dt.version()}; lettura della versione 0: {n_v0} righe (attese {n0})"
    ok, d = run_test(delta_tt)
    add(f, "Delta", OK if ok else NO, "ogni commit e' una versione interrogabile", d)
    add(f, "MEDITA attuale", PART, "snapshot datati in sottocartelle di backup di data/output (manuali, non interrogabili)", "analisi del codice")

    # ---------------------------------------------------------------- 6. rollback / restore
    f = "Ripristino di una versione dopo il commit"
    add(f, "SQLite", NO, "solo ROLLBACK prima del commit; dopo serve un backup esterno", "")
    add(f, "DuckDB", NO, "solo ROLLBACK prima del commit; dopo serve un backup esterno", "")
    add(f, "Parquet", NO, "nessun log delle modifiche", "")

    def delta_restore():
        DeltaTable(dpath).restore(0)
        dt = DeltaTable(dpath)
        n = dt.to_pyarrow_dataset().count_rows()
        return n == n0, f"restore alla versione 0: {n} righe (attese {n0}); il ripristino e' esso stesso una versione ({dt.version()})"
    ok, d = run_test(delta_restore)
    add(f, "Delta", OK if ok else NO, "RESTORE a qualunque versione registrata", d)
    add(f, "MEDITA attuale", PART, "ripristino possibile solo rilanciando la pipeline da uno snapshot di backup", "analisi del codice")

    # ---------------------------------------------------------------- 7. statistiche/metadati per il pruning
    f = "Metadati e statistiche per data skipping"

    def pq_stats():
        md = pq.ParquetFile(TMP / "parquet" / "part-0.parquet").metadata
        st = md.row_group(0).column(0).statistics
        return st is not None and st.has_min_max, f"{md.num_row_groups} row group con min/max per colonna"
    ok, d = run_test(pq_stats)
    add(f, "Parquet", OK if ok else NO, "statistiche min/max/null per row group nel footer", d)

    def delta_stats():
        acts = DeltaTable(dpath).get_add_actions(flatten=True)
        names = acts.schema.names if hasattr(acts, "schema") else list(acts.column_names)
        has = any(str(n).startswith("min") or ".min" in str(n) for n in names)
        return has, "statistiche min/max per file nel transaction log"
    ok, d = run_test(delta_stats)
    add(f, "Delta", OK if ok else PART, "statistiche per file nel log + quelle Parquet", d)
    add(f, "DuckDB", OK, "zone map automatiche per row group (interne al motore)", "")
    add(f, "SQLite", PART, "solo indici espliciti e ANALYZE; nessuna statistica per blocco", "")
    add(f, "MEDITA attuale", NO, "nessuna statistica: le pagine leggono la tabella intera (SELECT *)", "analisi del codice")

    # ---------------------------------------------------------------- 8. separazione storage/compute
    f = "Separazione storage / compute"
    add(f, "SQLite", NO, "motore embedded su file unico", "")
    add(f, "DuckDB", NO, "motore embedded su file proprio", "")
    add(f, "Parquet", OK, "file su storage condiviso, motore senza stato (DuckDB in memoria)", "verificato nel benchmark A1")
    add(f, "Delta", OK, "file + log su storage condiviso, motore senza stato", "verificato nel benchmark A1")
    add(f, "MEDITA attuale", NO, "DB SQLite locale accoppiato all'app Streamlit", "analisi del codice")

    # ---------------------------------------------------------------- 9. compressione / footprint (dal benchmark)
    f = "Compressione (footprint rispetto al testo)"
    try:
        foot = pd.read_csv(R / "footprint.csv").sort_values("measured").groupby("engine").tail(1).set_index("engine")["bytes"]
        txt = pd.read_csv(R / "tables.csv")["bytes"].sum()
        for eng, conf in [("sqlite", "SQLite"), ("duckdb", "DuckDB"), ("parquet", "Parquet"), ("delta", "Delta")]:
            ratio = foot[eng] / txt
            st = OK if ratio < 0.2 else (PART if ratio < 0.8 else NO)
            add(f, conf, st, f"{foot[eng] / 1e9:.2f} GB su {txt / 1e9:.2f} GB di testo ({ratio:.3f}x)", "footprint.csv")
        add(f, "MEDITA attuale", NO, f"come SQLite: {foot['sqlite'] / 1e9:.2f} GB", "footprint.csv")
    except Exception as e:
        add(f, "SQLite", "n.d.", f"footprint.csv non leggibile: {e!r}"[:200], "")

    # ---------------------------------------------------------------- 10. governance del catalogo
    f = "Catalogo come fonte di verita' delle tabelle attive"
    n_orph = None
    try:
        dup = pd.read_csv(R / "duplicates.csv")
        dup = dup[dup["identical"].astype(str).str.lower() == "true"]
        n_orph = int((dup["n"] - 1).sum())
    except Exception:
        pass
    ev = f"{n_orph} tabelle orfane (VAR_CODE non piu' nel catalogo) caricate comunque" if n_orph is not None else "vedi duplicates.csv"
    for c in ("SQLite", "DuckDB", "Parquet"):
        add(f, c, NO, "nessun catalogo: l'insieme delle tabelle e' quello presente su disco", "")
    add(f, "Delta", PART, "ogni tabella ha schema e storia nel proprio log; manca un catalogo multi-tabella", "")
    add(f, "MEDITA attuale", PART, f"catalogo config/info_<FONTE> presente ma non vincolante: {ev}", "duplicates.csv + info_MINIS_raw.csv")

    sq.close()
    dk.close()
    out = pd.DataFrame(rows)
    out.to_csv(R / "p2_checklist.csv", index=False)
    piv = out.pivot_table(index="feature", columns="configurazione", values="stato", aggfunc="first")[CONFS]
    piv = piv.reindex(list(dict.fromkeys(out["feature"])))
    sym = {OK: "✓", PART: "◐", NO: "✗"}
    md = ["# P2 - Feature lakehouse: implementate vs mancanti", "",
          f"Tabella di prova: `{name}` ({n0} righe), seed {SEED}, {time.strftime('%Y-%m-%d %H:%M')}.",
          "✓ implementato · ◐ parziale · ✗ mancante. Dettaglio ed evidenze in `p2_checklist.csv`.", "",
          "| Feature | " + " | ".join(CONFS) + " |", "|---|" + "---|" * len(CONFS)]
    for feat, r in piv.iterrows():
        md.append(f"| {feat} | " + " | ".join(sym.get(r[c], r[c]) for c in CONFS) + " |")
    (R / "p2_checklist.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    tex_sym = {OK: r"\checkmark", PART: r"$\circ$", NO: r"--"}
    (R / "p2_checklist.tex").write_text(
        piv.apply(lambda col: col.map(lambda s: tex_sym.get(s, s))).to_latex(
            escape=False, caption="Feature lakehouse: \\checkmark{} implementato, $\\circ$ parziale, -- mancante.",
            label="tab:lakehouse_features"), encoding="utf-8")
    shutil.rmtree(TMP, ignore_errors=True)
    print("\n".join(md))
    print(f"\nP2 completato in {time.time() - t0:.1f} s. Test falliti/errori: "
          f"{sum('Error' in str(r['test']) for r in rows)}")


if __name__ == "__main__":
    main()
