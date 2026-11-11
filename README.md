# MEDITA — a Multimodal hEalth Data lakehouse for ITAly

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24143031.svg)](https://doi.org/10.5281/zenodo.24143031)<!-- REPO_DOI_261111 -->

Code, configuration and experiment scripts of MEDITA, a platform that extracts,
harmonises and serves Italian public-health open data (Ministero della Salute, AIFA,
ISTAT), together with the scripts that regenerate every experimental table and figure
of the accompanying paper.

> Version 0.1.0. The DOI of the data snapshot is added at its deposit on Zenodo.<!-- REPO_EXP_261111 -->

## Repository layout

```
paper/
  make_all.py          single entry point: regenerates all tables and figures
  scripts/             one script per table/figure group (inputs/outputs in each docstring)
  config/              mappings used by the paper scripts (topics)
results/               intermediate results (small CSV/JSON) — committed, so that figures
                       can be rebuilt without the data; results/experiments/ holds the
                       results of experiments A-D (tools/export_results.py)
figures/               generated figures (PDF for LaTeX, PNG for preview)
tables/                generated LaTeX tables (+ CSV)
tools/                 utilities (environment lock, export of the experiment results)
pipeline/              ETL pipeline: MASTER.py, scripts/ (extract, transform, load), config/
pipeline/experiments/  code of the experiments: A storage, B Transform, C HANK, D use case
```

## Quick start

```bash
python -m venv .venv && .venv/Scripts/activate      # Windows (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
python paper/make_all.py --list                      # steps and what each needs
python paper/make_all.py                             # tables and figures from results/
```

`make_all.py` rebuilds every experimental table (`tables/*.tex`, `tables/*.csv`) and figure
(`figures/*.pdf`, `figures/*.png`) of the paper and checks each value against the paper.

### Rebuilding the results from the data

The harmonised data snapshot (all tables produced by the Transform for AIFA, ISTAT
and MINIS) is being deposited on Zenodo; its DOI will be added here.<!-- REPO_REL_261111 --> Unpack it and point `MEDITA_HOME` to
the folder that contains `data/output/<SOURCE>/` and `config/`:

```bash
set MEDITA_HOME=D:\path\to\medita-snapshot          # Windows  (Linux/macOS: export MEDITA_HOME=...)
python paper/make_all.py --from-data
```

### What can and cannot be redistributed

- **Data snapshot:** derived from open data; released under CC BY 4.0 (see `DATA_LICENSE.md`).
- **Health-news corpus:** copyrighted articles; neither the articles nor the code that
  collects them are redistributed. Only aggregated counts (documents per year and topic) are
  published in `results/news/`; they are enough to rebuild Figure 2.3.<!-- REPO_NEWS_261111 -->

## Running the ETL pipeline

`pipeline/` keeps the layout of a MEDITA installation, so `MASTER.py` runs from there and writes
`data/`, `logs/` and `lake/` next to itself (all excluded from git). To use another folder,
set `MEDITA_HOME`.

<!-- REPO_261111 -->
The Load writes a lakehouse (Delta Lake tables, queried with DuckDB) in `lake/`, in three zones:
`bronze/raw_catalog` (one row per raw file of `data/input/`, with its SHA-256; the raw files stay
in their original format), `silver/` (one table per harmonised dataset) and `gold/` (regional time
series `<dataset>_ts` and service tables). Every Load writes a new Delta version of each table, so
earlier versions stay readable (time travel); `lake/_lake_log` records table, version and snapshot. Which sources and steps run is set in `pipeline/config/PROMPT.json`
(`Extract`, `Transform`, `Load` for AIFA, MINIS, ISTAT).

```bash
cd pipeline
python MASTER.py
```

The ISTAT extractor respects the rate limit of esploradati.istat.it (at most 4 requests per 65 s).
The text sources (health news) are not part of this repository: the articles are copyrighted, so
`pipeline/config/PROMPT.json` lists no text sources and the Load processes only AIFA, MINIS and ISTAT.

## Tables and figures

| Paper | Script | Needs |
|---|---|---|
| Table 2.4, Figure 2.2 — corpus by domain and year | `paper/scripts/data_topic_stats.py` → `fig_data_topics.py` | data snapshot (only to recompute `results/data/`) |
| Figure 2.3 — news by topic and year | `paper/scripts/fig_news_topics.py` | `results/news/` (aggregated counts) |
| Storage benchmark, query latency, lakehouse features; Figure query latency (A) | `paper/scripts/build_A_storage.py` | `results/experiments/A_storage_benchmark/`, `A_lake/` |
| Matching quality, threshold, baselines, ablation, superkey, scalability; Figures threshold and baselines (B) | `paper/scripts/build_B_transform.py` | `results/experiments/B_*/` |
| HANK metrics, comparison, NMISS, abstention; Figure abstention (C) | `paper/scripts/build_C_hank.py` | `results/experiments/C_hank_eval/` (per-question scores only) |
| Use-case matching and join, missingness; Figures matching and missingness (D) | `paper/scripts/build_D_usecase.py` | `results/experiments/D_case_study/` |

## Experiments

The code of every experiment is in `pipeline/experiments/<experiment>/`; how to re-run each one, what it
needs and what is not redistributed is in `pipeline/experiments/README.md`. Extra packages:
`pip install -r requirements-experiments.txt`. After a re-run:

```bash
python paper/make_all.py --from-experiments          # re-export results/experiments/, then rebuild
```

## Citation

See `CITATION.cff`. A DOI is assigned by Zenodo to each GitHub release. Software DOI (all versions): [10.5281/zenodo.24143031](https://doi.org/10.5281/zenodo.24143031); version 0.1.0: [10.5281/zenodo.24143032](https://doi.org/10.5281/zenodo.24143032).

## Licence

Code: MIT (`LICENSE`). Data and aggregated results: CC BY 4.0 (`DATA_LICENSE.md`).
