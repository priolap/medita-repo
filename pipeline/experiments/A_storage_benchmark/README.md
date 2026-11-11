# A1 — Storage layer: SQLite vs DuckDB vs Parquet vs Delta Lake

Task A1 (P1) e input per A2 di `tasks_MPP.txt`.

## Dove va
`<MEDITA>/experiments/A1_storage_benchmark/` — lo script risale da solo a `<MEDITA>/data`.
Legge `data/output/<AIFA|ISTAT|MINIS>/*.txt` (solo la radice: le sottocartelle datate sono backup e vengono ignorate).

## Prima di lanciare
1. `pip install -r requirements_bench.txt`
2. DB e file generati vanno in `D:\MEDITA_bench_work` (fuori da OneDrive, che altrimenti sincronizzerebbe GB e falserebbe i tempi).
   Per usare un'altra cartella: variabile d'ambiente `MEDITA_BENCH_WORK` o costante `WORK_DIR`.
3. Chiudere programmi pesanti e sospendere la sincronizzazione OneDrive durante il run.

## Esecuzione
```
python bench_storage.py            # ingestion -> query -> indici SQLite -> query -> operazioni Delta
python make_report.py              # tabelle LaTeX e figura
```
Il run e' riprendibile: se si interrompe, rilanciando salta le tabelle gia' caricate.
`--ingest`, `--queries`, `--lakehouse` eseguono una fase sola; `--fresh` riparte da zero.
Prova veloce: puntare `DATA_DIR` a `data_sample` in testa a `bench_storage.py`.

## Cosa misura
| File | Contenuto |
|---|---|
| `ingestion.csv` | tempo e righe per tabella x engine (`note` = fallback sui tipi: `full_scan`/`all_varchar`) |
| `footprint.csv` | byte su disco per engine (SQLite con e senza indici) |
| `queries.csv` | Q1-Q9 x engine x tabella S/M/L: prima esecuzione + REPS ripetizioni |
| `lakehouse_ops.csv` | Delta: append transazionale, time travel, schema evolution, rollback |
| `params.json` | tabelle S/M/L scelte e parametri delle query (identici per tutti gli engine) |
| `env.json` | hardware e versioni |

Query e loro legame con la piattaforma: vedi `queries.py`. La join Q7 usa
`DISP_POSLETTO_REGI` x `DCIS_DECESSI`: se i nomi sono cambiati, aggiornarli in `queries.py`.

## Scelte da dichiarare nel paper
- SQLite caricato con `pandas.to_sql` a blocchi (come la Load attuale) e PRAGMA di bulk load.
- DuckDB deduce i tipi su 200k righe; se fallisce rilegge con scansione completa, poi tutto VARCHAR (annotato).
- Q1 (tabella intera in pandas) solo per tabelle < 1 GB, Q8 solo sulla tabella L.
- "Prima esecuzione" = prima query su una connessione nuova (la cache del sistema operativo non viene svuotata).
