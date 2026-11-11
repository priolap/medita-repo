#!/usr/bin/env python3
"""
bench_storage.py - Task A1: storage layer SQLite vs DuckDB vs Parquet (+ Delta Lake)

Posizione attesa:  <MEDITA>/experiments/A1_storage_benchmark/bench_storage.py
Dati letti da:     <MEDITA>/data/output/<FONTE>/*.txt  (le sottocartelle sono backup e vengono ignorate)

Configurazioni:
  S1   sqlite    SQLite, caricamento con pandas.to_sql a blocchi (come la Load attuale)
  S1i  sqlite_ix SQLite dopo la creazione degli indici su (ANNO, CODICE_REGIONE)
  S2   duckdb    file .duckdb nativo
  S3   parquet   un file Parquet (zstd) per tabella, interrogato da DuckDB
  S4   delta     tabelle Delta Lake (deltalake), interrogate da DuckDB via Arrow
                 + operazioni lakehouse: append transazionale, time travel, schema evolution

Uso:
  python bench_storage.py              # tutto (riprende da dove si era fermato)
  python bench_storage.py --ingest     # solo caricamento
  python bench_storage.py --queries    # solo query (richiede il caricamento)
  python bench_storage.py --lakehouse  # solo operazioni Delta
  python bench_storage.py --fresh      # cancella WORK_DIR e results/ e riparte da zero

Output in results/: ingestion.csv, footprint.csv, queries.csv, lakehouse_ops.csv,
params.json, tables.csv, env.json. Poi: python make_report.py
"""
import argparse
import csv
import gc
import hashlib
import json
import os
import platform
import shutil
import sqlite3
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd

import queries as Q

# ============================================================== parametri
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]                 # <MEDITA>
DATA_DIR = ROOT / "data"               # per i test puntare a data_sample
SOURCES = ["AIFA", "ISTAT", "MINIS"]
WORK_DIR = Path(os.environ.get("MEDITA_BENCH_WORK", r"D:\MEDITA_bench_work"))   # DB e file generati (diversi GB)
# PATCH_BENCH_ALIM_261029: copie filtrate delle tabelle (es. ALIM_EXCHANGE_VIVI senza il 2 sem. 2024)
BENCH_INPUT = Path(os.environ.get("MEDITA_BENCH_INPUT", r"D:\MEDITA_bench_input"))
RESULTS = HERE / "results"

ENGINES = ["sqlite", "duckdb", "parquet", "delta"]   # togliere "delta" se non serve
SQLITE_CHUNK = 200_000
SQLITE_BULK_PRAGMAS = True             # journal_mode=OFF, synchronous=OFF durante il load
DUCKDB_THREADS = None                  # None = tutti i core
DUCKDB_MEMORY = None                   # es. "8GB"; None = default DuckDB
CSV_SAMPLE_SIZE = 200_000              # righe usate da DuckDB per dedurre i tipi
REPS = 5                               # ripetizioni "calde" per query
Q1_MAX_MB = 1024                       # Q1 (tabella intera in pandas) solo sotto questa soglia
TIERS = {"XS": 0.25, "S": 0.50, "M": 0.75, "L": 1.00}   # punti sulla scala log delle dimensioni (min..max)  # PATCH_A1_V2
CAT_MAX_DISTINCT_RATIO = 0.90          # Q8: escluse colonne con piu' del 90% di valori distinti (identificativi)
# ========================================================================


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def append_csv(path, row):
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)


def read_csv_rows(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def dir_bytes(p):
    p = Path(p)
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


# ------------------------------------------------------------ discovery
def discover_tables():
    """Tabelle trasformate in data/output/<FONTE>/*.txt (solo la radice: le sottocartelle sono backup)."""
    tables = []
    for src in SOURCES:
        folder = DATA_DIR / "output" / src
        if not folder.is_dir():
            continue
        for f in sorted(folder.glob("*.txt")):
            snap = "output"
            if (BENCH_INPUT / src / f.name).is_file():  # PATCH_BENCH_ALIM_261029: copia filtrata
                f, snap = BENCH_INPUT / src / f.name, "output_filtrata"
            with f.open(encoding="utf-8", errors="replace") as h:
                header = h.readline().strip().split("|")
            tables.append({"table": f.stem, "source": src, "snapshot": snap,  # PATCH_BENCH_ALIM_261029
                           "path": str(f), "bytes": f.stat().st_size,
                           "has_keys": "ANNO" in header and "CODICE_REGIONE" in header})
    seen = {}
    for t in tables:                       # stesso nome in due fonti: tiene la prima
        seen.setdefault(t["table"], t)
    return list(seen.values())


CSV_MODES = ("sample", "full_scan", "all_varchar")   # tentativi in ordine se i tipi dedotti falliscono


def read_csv_sql(path, mode="sample"):
    p = str(path).replace("\\", "/").replace("'", "''")
    opts = "delim='|', header=true, quote='\"'"
    opts += {"sample": f", sample_size={CSV_SAMPLE_SIZE}", "full_scan": ", sample_size=-1",
             "all_varchar": ", all_varchar=true"}[mode]
    return f"read_csv('{p}', {opts})"


def with_csv_fallback(t, action):
    """Esegue action(mode) provando i CSV_MODES; annota in t['note'] il modo usato se non e' il primo."""
    last = None
    for mode in CSV_MODES:
        try:
            out = action(mode)
            if mode != CSV_MODES[0]:
                t["note"] = mode
            return out
        except Exception as e:          # duckdb.Error o errori Arrow emersi durante la lettura
            last = e
    raise last


def duck_connect(path=":memory:"):
    con = duckdb.connect(str(path))
    if DUCKDB_THREADS:
        con.execute(f"SET threads={int(DUCKDB_THREADS)}")
    if DUCKDB_MEMORY:
        con.execute(f"SET memory_limit='{DUCKDB_MEMORY}'")
    return con


# ------------------------------------------------------------ engines
class Engine:
    name = ""

    def __init__(self):
        self.dir = WORK_DIR / self.name
        self.dir.mkdir(parents=True, exist_ok=True)

    def footprint(self):
        return dir_bytes(self.dir)


class SQLiteEngine(Engine):
    name = "sqlite"

    def __init__(self):
        super().__init__()
        self.db = self.dir / "medita.sqlite"

    def connect(self):
        return sqlite3.connect(self.db)

    def ingest(self, t):
        con = self.connect()
        if SQLITE_BULK_PRAGMAS:
            con.execute("PRAGMA journal_mode=OFF")
            con.execute("PRAGMA synchronous=OFF")
        con.execute(f'DROP TABLE IF EXISTS "{t["table"]}"')
        n = 0
        for chunk in pd.read_csv(t["path"], sep="|", chunksize=SQLITE_CHUNK, low_memory=False,
                                 encoding="utf-8", encoding_errors="replace"):
            chunk.to_sql(t["table"], con, if_exists="append", index=False)
            n += len(chunk)
        con.commit()
        con.close()
        return n

    def has(self, table):
        if not self.db.exists():
            return False
        con = self.connect()
        r = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        con.close()
        return r is not None

    def create_indexes(self, tables):
        con = self.connect()
        t0 = time.perf_counter()
        for t in tables:
            if t["has_keys"]:
                con.execute(f'CREATE INDEX IF NOT EXISTS "ix_{t["table"]}" '
                            f'ON "{t["table"]}"(ANNO, CODICE_REGIONE)')
        con.commit()
        con.close()
        return time.perf_counter() - t0

    def drop_indexes(self):
        con = self.connect()
        for (n,) in con.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'ix_%'").fetchall():
            con.execute(f'DROP INDEX "{n}"')
        con.commit()
        con.close()

    def run(self, sql, con):
        return pd.read_sql_query(sql, con)

    def catalog(self, con):
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        ncols = sum(len(con.execute(f'PRAGMA table_info("{n}")').fetchall()) for n in names)
        return pd.DataFrame({"tables": [len(names)], "columns": [ncols]})


class DuckDBEngine(Engine):
    name = "duckdb"

    def __init__(self):
        super().__init__()
        self.db = self.dir / "medita.duckdb"

    def connect(self):
        return duck_connect(self.db)

    def ingest(self, t):
        con = self.connect()
        tq = f'"{t["table"]}"'
        with_csv_fallback(t, lambda m: con.execute(
            f"CREATE OR REPLACE TABLE {tq} AS SELECT * FROM {read_csv_sql(t['path'], m)}"))
        n = con.execute(f"SELECT COUNT(*) FROM {tq}").fetchone()[0]
        con.close()
        return n

    def has(self, table):
        if not self.db.exists():
            return False
        con = self.connect()
        r = con.execute("SELECT 1 FROM information_schema.tables WHERE table_name=?", [table]).fetchone()
        con.close()
        return r is not None

    def run(self, sql, con):
        return con.execute(sql).fetchdf()

    def catalog(self, con):
        return con.execute("SELECT COUNT(DISTINCT table_name) AS tables, COUNT(*) AS columns "
                           "FROM information_schema.columns WHERE table_schema='main'").fetchdf()


class ParquetEngine(DuckDBEngine):
    name = "parquet"

    def __init__(self):
        Engine.__init__(self)

    def file(self, table):
        return self.dir / f"{table}.parquet"

    def ingest(self, t):
        con = duck_connect()
        out = str(self.file(t["table"])).replace("\\", "/")
        with_csv_fallback(t, lambda m: con.execute(
            f"COPY (SELECT * FROM {read_csv_sql(t['path'], m)}) TO '{out}' (FORMAT parquet, COMPRESSION zstd)"))
        n = con.execute(f"SELECT COUNT(*) FROM read_parquet('{out}')").fetchone()[0]
        con.close()
        return n

    def has(self, table):
        return self.file(table).exists()

    def connect(self):
        con = duck_connect()
        for f in sorted(self.dir.glob("*.parquet")):
            p = str(f).replace("\\", "/")
            con.execute(f"CREATE VIEW \"{f.stem}\" AS SELECT * FROM read_parquet('{p}')")
        return con

    def catalog(self, con):
        p = str(self.dir).replace("\\", "/")
        return con.execute(f"SELECT COUNT(DISTINCT file_name) AS tables, COUNT(*) AS columns "
                           f"FROM parquet_schema('{p}/*.parquet') WHERE num_children IS NULL").fetchdf()


class DeltaEngine(DuckDBEngine):
    name = "delta"

    def __init__(self):
        Engine.__init__(self)
        from deltalake import DeltaTable, write_deltalake  # noqa: F401  (errore chiaro se manca)

    def path(self, table):
        return self.dir / table

    def ingest(self, t):
        from deltalake import write_deltalake
        con = duck_connect()
        dest = self.path(t["table"])

        def write(mode):
            shutil.rmtree(dest, ignore_errors=True)       # niente tabelle parziali tra un tentativo e l'altro
            rel = con.execute(f"SELECT * FROM {read_csv_sql(t['path'], mode)}")
            reader = rel.to_arrow_reader(500_000) if hasattr(rel, "to_arrow_reader") else rel.fetch_record_batch(500_000)
            write_deltalake(str(dest), reader, mode="overwrite")

        with_csv_fallback(t, write)
        con.close()
        from deltalake import DeltaTable
        return DeltaTable(str(self.path(t["table"]))).to_pyarrow_dataset().count_rows()

    def has(self, table):
        return (self.path(table) / "_delta_log").exists()

    reader = None                      # "delta_scan" (nativo DuckDB) o "arrow" (fallback)

    def connect(self):
        con = duck_connect()
        tables = sorted(p for p in self.dir.iterdir() if (p / "_delta_log").exists())
        try:
            con.execute("INSTALL delta")
            con.execute("LOAD delta")
            for d in tables:
                p = str(d).replace("\\", "/")
                con.execute(f"CREATE VIEW \"{d.name}\" AS SELECT * FROM delta_scan('{p}')")
            DeltaEngine.reader = "delta_scan"
        except Exception as e:
            from deltalake import DeltaTable
            log(f"    delta_scan non disponibile ({e!r:.120}): uso Arrow")
            con = duck_connect()
            for d in tables:
                con.register(d.name, DeltaTable(str(d)).to_pyarrow_dataset())
            DeltaEngine.reader = "arrow"
        self._names = [d.name for d in tables]
        return con

    def catalog(self, con):
        c = sum(len(con.execute(f'DESCRIBE "{n}"').fetchall()) for n in self._names)
        return pd.DataFrame({"tables": [len(self._names)], "columns": [c]})


ENGINE_CLASSES = {"sqlite": SQLiteEngine, "duckdb": DuckDBEngine,
                  "parquet": ParquetEngine, "delta": DeltaEngine}


# ------------------------------------------------------------ fasi
def phase_ingest(tables, engines):
    done = {(r["engine"], r["table"]) for r in read_csv_rows(RESULTS / "ingestion.csv") if r["status"] == "ok"}
    measured = {r["engine"] for r in read_csv_rows(RESULTS / "footprint.csv")}
    for eng in engines:
        ingested = 0
        for t in tables:
            if (eng.name, t["table"]) in done and eng.has(t["table"]):
                continue
            ingested += 1
            log(f"[ingest] {eng.name:8s} {t['table']} ({t['bytes'] / 1e6:,.1f} MB)")
            t.pop("note", None)
            t0 = time.perf_counter()
            try:
                n, status = eng.ingest(t), "ok"
            except Exception as e:
                n, status = None, f"error: {e!r}"[:300]
                log("   ", status)
            append_csv(RESULTS / "ingestion.csv", {
                "engine": eng.name, "table": t["table"], "source": t["source"], "snapshot": t["snapshot"],
                "rows": n, "txt_bytes": t["bytes"], "seconds": round(time.perf_counter() - t0, 3),
                "status": status, "note": t.get("note", "")})
        if ingested or eng.name not in measured:     # dopo la creazione degli indici SQLite non si rimisura
            append_csv(RESULTS / "footprint.csv", {"engine": eng.name, "bytes": eng.footprint(),
                                                   "measured": time.strftime("%Y-%m-%d %H:%M:%S")})


def build_params(tables):
    """Parametri delle query ricavati una volta da DuckDB (riferimento comune a tutti gli engine)."""
    ref = DuckDBEngine()
    con = ref.connect()
    keyed = sorted((t for t in tables if t["has_keys"] and ref_has(con, t["table"])), key=lambda t: t["bytes"])
    if not keyed:
        sys.exit("Nessuna tabella con ANNO e CODICE_REGIONE caricata in DuckDB.")
    # fasce: punti equispaziati sulla scala log delle dimensioni, tabella piu' vicina a ciascun punto
    import math
    logs = [math.log(t["bytes"]) for t in keyed]
    lo, hi = min(logs), max(logs)
    picked, used = {}, set()
    for tier, qt in TIERS.items():
        target = lo + qt * (hi - lo)
        cand = sorted((abs(math.log(t["bytes"]) - target), t["table"]) for t in keyed if t["table"] not in used)
        name = cand[0][1]
        used.add(name)
        picked[name] = {"tier": tier, "target_bytes": int(math.exp(target))}
    params = {}
    for name, sel in picked.items():
        tier = sel["tier"]
        desc = con.execute(f'DESCRIBE "{name}"').fetchall()
        cols = [d[0] for d in desc]
        types = {d[0]: d[1].upper() for d in desc}
        colset = set(cols)
        numeric = [c for c in cols if c not in ("ANNO",) and not c.upper().startswith("CODICE")
                   and f"{c}_DESC" not in colset                     # codici con descrizione: non sono misure
                   and not (c.upper().startswith("ID") or c.upper().endswith("_ID"))   # identificativi numerici
                   and any(k in types[c] for k in ("INT", "DOUBLE", "DECIMAL", "FLOAT", "REAL"))]
        n_rows = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        cats = [c for c in cols if "VARCHAR" in types[c]
                and c not in ("CODICE_REGIONE", "REGIONE", "UNITA_ADMIN")]
        card = {}
        if cats:
            exprs = ", ".join(f'approx_count_distinct("{c}")' for c in cats)
            card = dict(zip(cats, con.execute(f'SELECT {exprs} FROM "{name}"').fetchone()))
        ok = {c: n for c, n in card.items() if n_rows and n / n_rows <= CAT_MAX_DISTINCT_RATIO}
        cat = max(ok, key=ok.get) if ok else None
        max_anno = con.execute(f'SELECT MAX(TRY_CAST(ANNO AS INTEGER)) FROM "{name}"').fetchone()[0]
        t = next(x for x in tables if x["table"] == name)
        params[name] = {"tier": tier, "bytes": t["bytes"], "target_bytes": sel["target_bytes"],
                        "source": t["source"], "rows": n_rows, "columns": cols, "measures": numeric,
                        "cat_col": cat, "cat_distinct": ok.get(cat) if cat else None,
                        "cat_candidates": card, "max_anno": int(max_anno or 2020)}
    con.close()
    (RESULTS / "params.json").write_text(json.dumps(params, indent=2), encoding="utf-8")
    return params


def ref_has(con, table):
    return con.execute("SELECT 1 FROM information_schema.tables WHERE table_name=?", [table]).fetchone() is not None


def time_query(eng, con, qid, sql, table, tier, label):
    rows = []
    for rep in range(REPS + 1):          # rep 0 = prima esecuzione ("fredda")
        t0 = time.perf_counter()
        try:
            df = eng.run(sql, con) if qid != "Q2" else eng.catalog(con)
            n, status = len(df), "ok"
        except Exception as e:
            n, status = None, f"error: {e!r}"[:300]
        dt = time.perf_counter() - t0
        df = None
        gc.collect()                         # evita che i DataFrame grandi pesino sulle ripetizioni successive
        rows.append({"engine": label, "query": qid, "table": table, "tier": tier, "rep": rep,
                     "cold": rep == 0, "seconds": round(dt, 5), "rows_out": n, "status": status})
        if status != "ok":
            log(f"    {label} {qid} {table}: {status}")
            break
    return rows


def phase_queries(engines, params, sqlite_indexed=False):
    out = RESULTS / "queries.csv"
    for eng in engines:
        label = "sqlite_ix" if (eng.name == "sqlite" and sqlite_indexed) else eng.name
        if eng.name == "sqlite" and not sqlite_indexed:
            eng.drop_indexes()              # S1 si misura sempre senza indici
        con = eng.connect()
        log(f"[query]  {label}")
        rows = time_query(eng, con, "Q2", None, "*", "-", label)
        for name, p in params.items():
            qs = Q.per_table_queries(name, p)
            order = [k for k in qs if k != "Q1"] + (["Q1"] if "Q1" in qs else [])   # Q1 (tabella intera) per ultima
            for qid in order:
                sql = qs[qid]
                if qid == "Q1" and p["bytes"] > Q1_MAX_MB * 1e6:
                    continue
                if qid == "Q8" and p["tier"] != "L":
                    continue
                rows += time_query(eng, con, qid, sql, name, p["tier"], label)
        rows += time_query(eng, con, "Q7", Q.join_query(), f"{Q.J1_TABLE}x{Q.J2_TABLE}", "-", label)
        con.close()
        if eng.name == "delta":
            append_csv(RESULTS / "engine_notes.csv", {"engine": "delta", "reader": DeltaEngine.reader,
                                                      "measured": time.strftime("%Y-%m-%d %H:%M:%S")})
        for r in rows:
            append_csv(out, r)


def phase_lakehouse(params):
    """Operazioni che SQLite/Parquet puri non offrono: append ACID, time travel, schema evolution."""
    from deltalake import DeltaTable, write_deltalake
    import pyarrow as pa
    eng = DeltaEngine()
    name = next(n for n, p in params.items() if p["tier"] == "M")
    path = str(eng.path(name))
    rows = []

    def rec(op, dt, ok, detail):
        r = {"table": name, "operation": op, "seconds": round(dt, 4), "ok": ok, "detail": detail}
        rows.append(r)
        append_csv(RESULTS / "lakehouse_ops.csv", r)
        log(f"[lake]   {op}: {ok} {detail}")

    dt0 = DeltaTable(path)
    v0 = dt0.version()
    n0 = dt0.to_pyarrow_dataset().count_rows()
    batch = dt0.to_pyarrow_dataset().head(1000)

    t = time.perf_counter()
    write_deltalake(path, batch, mode="append")
    d = DeltaTable(path)
    rec("append_transazionale", time.perf_counter() - t, d.version() == v0 + 1,
        f"versione {v0}->{d.version()}, righe {n0}->{d.to_pyarrow_dataset().count_rows()}")

    t = time.perf_counter()
    old = DeltaTable(path, version=v0).to_pyarrow_dataset().count_rows()
    rec("time_travel", time.perf_counter() - t, old == n0, f"lettura versione {v0}: {old} righe")

    t = time.perf_counter()
    extra = batch.append_column("NOTE_REVISIONE", pa.array(["test"] * batch.num_rows))
    ok, detail = True, ""
    try:
        write_deltalake(path, extra, mode="append", schema_mode="merge")
        d = DeltaTable(path)
        ok = "NOTE_REVISIONE" in d.schema().to_arrow().names if hasattr(d.schema(), "to_arrow") \
            else "NOTE_REVISIONE" in [f.name for f in d.schema().fields]
        detail = f"colonna aggiunta, versione {d.version()}"
    except Exception as e:
        ok, detail = False, repr(e)[:300]
    rec("schema_evolution", time.perf_counter() - t, ok, detail)

    t = time.perf_counter()                                   # PATCH_A1_CLOSE: schema enforcement
    d = DeltaTable(path)
    v_before, n_before = d.version(), d.to_pyarrow_dataset().count_rows()
    sample = d.to_pyarrow_dataset().head(10)
    cands = list(params[name].get("measures") or []) + list(sample.schema.names)
    col = next((c for c in cands if c in sample.schema.names
                and not pa.types.is_string(sample.schema.field(c).type)
                and not pa.types.is_large_string(sample.schema.field(c).type)), None)
    if col is None:
        ok, detail = False, "nessuna colonna non testuale su cui provare"
    else:
        bad = sample.set_column(sample.schema.get_field_index(col), col,
                                pa.array(["non_numerico"] * sample.num_rows))
        try:
            write_deltalake(path, bad, mode="append")
            ok, detail = False, f"testo in {col} ({sample.schema.field(col).type}) accettato"
        except Exception as e:
            d = DeltaTable(path)
            ok = d.version() == v_before and d.to_pyarrow_dataset().count_rows() == n_before
            detail = (f"testo in {col} ({sample.schema.field(col).type}) rifiutato: {type(e).__name__}; "
                      f"versione {d.version()} invariata")
    rec("schema_enforcement", time.perf_counter() - t, ok, detail)

    t = time.perf_counter()
    DeltaTable(path).restore(v0)
    d = DeltaTable(path)
    rec("rollback_restore", time.perf_counter() - t,
        d.to_pyarrow_dataset().count_rows() == n0, f"ripristinata versione {v0} (nuova versione {d.version()})")
    return rows


def check_duplicates(tables):
    """Tabelle con identica dimensione confrontate via SHA-256. Solo segnalazione."""
    by_size = {}
    for t in tables:
        by_size.setdefault(t["bytes"], []).append(t)
    rows = []
    for size, group in by_size.items():
        if len(group) < 2:
            continue
        hashes = {}
        for t in group:
            h = hashlib.sha256()
            with open(t["path"], "rb") as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    h.update(block)
            hashes.setdefault(h.hexdigest(), []).append(t["table"])
        for digest, names in hashes.items():
            rows.append({"bytes": size, "sha256": digest[:16], "n": len(names),
                         "identical": len(names) > 1, "tables": " | ".join(names)})
    out = RESULTS / "duplicates.csv"
    if out.exists():
        out.unlink()
    for r in rows:
        append_csv(out, r)
    dup = [r for r in rows if r["identical"]]
    log(f"Controllo duplicati: {len(dup)} gruppi di tabelle identiche (vedi results/duplicates.csv)")


def write_env(tables):
    env = {"python": sys.version.split()[0], "platform": platform.platform(),
           "processor": platform.processor(), "cpu_count": os.cpu_count(),
           "duckdb": duckdb.__version__, "pandas": pd.__version__, "sqlite": sqlite3.sqlite_version,
           "data_dir": str(DATA_DIR), "n_tables": len(tables),
           "txt_bytes_total": sum(t["bytes"] for t in tables),
           "params": {"REPS": REPS, "SQLITE_CHUNK": SQLITE_CHUNK, "SQLITE_BULK_PRAGMAS": SQLITE_BULK_PRAGMAS,
                      "CSV_SAMPLE_SIZE": CSV_SAMPLE_SIZE, "DUCKDB_THREADS": DUCKDB_THREADS,
                      "DUCKDB_MEMORY": DUCKDB_MEMORY}}
    try:
        import psutil
        env["ram_gb"] = round(psutil.virtual_memory().total / 2**30, 1)
    except ImportError:
        pass
    try:
        import deltalake
        import pyarrow
        env["deltalake"], env["pyarrow"] = deltalake.__version__, pyarrow.__version__
    except ImportError:
        pass
    (RESULTS / "env.json").write_text(json.dumps(env, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ingest", action="store_true")
    ap.add_argument("--queries", action="store_true")
    ap.add_argument("--lakehouse", action="store_true")
    ap.add_argument("--fresh", action="store_true")
    a = ap.parse_args()
    run_all = not (a.ingest or a.queries or a.lakehouse)

    if a.fresh:
        shutil.rmtree(WORK_DIR, ignore_errors=True)
        shutil.rmtree(RESULTS, ignore_errors=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    if "onedrive" in str(WORK_DIR).lower():
        log(f"ATTENZIONE: WORK_DIR e' dentro OneDrive ({WORK_DIR}). La sincronizzazione carica GB in cloud "
            "e altera i tempi. Imposta MEDITA_BENCH_WORK o modifica WORK_DIR.")
    tables = discover_tables()
    if not tables:
        sys.exit(f"Nessuna tabella trovata in {DATA_DIR / 'output'}")
    with (RESULTS / "tables.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(tables[0]))
        w.writeheader()
        w.writerows(tables)
    write_env(tables)
    check_duplicates(tables)
    log(f"{len(tables)} tabelle, {sum(t['bytes'] for t in tables) / 1e9:,.2f} GB di testo")

    engines = [ENGINE_CLASSES[e]() for e in ENGINES]
    if run_all or a.ingest:
        phase_ingest(tables, engines)

    if run_all or a.queries:
        params = build_params(tables)
        if (RESULTS / "queries.csv").exists():
            (RESULTS / "queries.csv").unlink()        # le query si rifanno sempre per intero
        phase_queries(engines, params)
        if "sqlite" in ENGINES:
            sq = SQLiteEngine()
            dt = sq.create_indexes(tables)
            append_csv(RESULTS / "footprint.csv", {"engine": "sqlite_ix", "bytes": sq.footprint(),
                                                   "measured": time.strftime("%Y-%m-%d %H:%M:%S")})
            append_csv(RESULTS / "ingestion.csv", {
                "engine": "sqlite_ix", "table": "*indici*", "source": "", "snapshot": "", "rows": "",
                "txt_bytes": "", "seconds": round(dt, 3), "status": "ok", "note": "CREATE INDEX (ANNO, CODICE_REGIONE)"})
            phase_queries([sq], params, sqlite_indexed=True)

    if (run_all or a.lakehouse) and "delta" in ENGINES:
        params = json.loads((RESULTS / "params.json").read_text(encoding="utf-8")) \
            if (RESULTS / "params.json").exists() else build_params(tables)
        if (RESULTS / "lakehouse_ops.csv").exists():
            (RESULTS / "lakehouse_ops.csv").unlink()
        phase_lakehouse(params)

    log("Fatto. Ora: python make_report.py")


if __name__ == "__main__":
    main()
