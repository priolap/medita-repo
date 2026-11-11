# Experiments

Code of the experiments reported in the paper. Each folder is self-contained and finds the
MEDITA installation two levels up (`pipeline/`), so the scripts run unchanged from here once the
data snapshot is in `pipeline/data/` (or in the folder set by `MEDITA_HOME`, see the main README).
Internal notes and comments in the scripts are in Italian.

The outputs of an experiment are written to its own `out/` (or `results/`) folder, which is not
committed. The values used by the paper are exported to `results/experiments/` with
`python tools/export_results.py`, and `python paper/make_all.py` rebuilds every table and figure
from there, checking each value against the paper.
Experiments that measure time were run on an otherwise idle machine; run them the same way.

| Folder | Paper | Script(s) | Needs | Measures time |
|---|---|---|---|---|
| `A_storage_benchmark/` | Tables storage benchmark, storage latency, lakehouse checklist; Fig. query latency | `bench_storage.py`, `run_repro.py` (10 runs, the first is warm-up), `make_lakehouse_checklist.py` | snapshot; `MEDITA_BENCH_WORK`, `MEDITA_BENCH_INPUT` (scratch folders, several GB) | yes |
| `A_lake/` | Load into the lakehouse (time and footprint, text) | `misura_lake_notte.py` | snapshot | yes |
| `B_fuzzy_eval/` | Gold standard; Tables matching quality and threshold; Fig. threshold | `b4_stats.py stats --csv out/fuzzy_annotato_2026.xlsx --out out` | gold standard (`out/fuzzy_annotato_2026.xlsx`, committed) | no |
| `B_baseline/` | Table and Fig. schema-matching baselines | `b6_baseline.py` | gold standard; `valentine`, `sentence-transformers`, `rapidfuzz`, `scikit-learn`, `nltk` (WordNet and OMW, downloaded on first use) | no |
| `B_ablation/` | Table ablation | `ablation_transform.py --source <AIFA/MINIS/ISTAT> --configs ...` | snapshot (raw files) | no |
| `B_superkey/` | Table superkey times; Trentino-Alto Adige aggregation | `superkey_tests.py`, `b4_verifica_ith0.py` | snapshot | yes |
| `B_scalabilita/` | Table scalability | `b5_scalabilita.py` (`MEDITA_B5_WORK` scratch folder) | snapshot | yes |
| `C_hank_eval/` | Tables HANK metrics, comparison, NMISS, abstention; Fig. abstention | `c0`-`c4` steps, see `C_hank_eval/README.md` (retrieval and generation on Kaggle) | the HANK vector store and the question-answer workbook: **not distributed** | no |
| `D_case_study/` | Tables use case and missingness; Figs. matching and missingness | `d14_integrazione_descrittiva.ipynb`, `d15_missingness.ipynb` (run from their folder) | snapshot | no |

## What is not redistributed

- **Health-news corpus and HANK inputs.** The news articles are protected by copyright: the vector
  store built from them, the retrieved contexts, the questions with their reference answers and the
  generated answers are not part of the repository. `results/experiments/C_hank_eval/` contains the
  per-question scores only (one row per question and model), enough to rebuild the HANK tables and
  figure. `config_c.json` keeps the setup of the paper; `rag_root` must point to a local copy of the
  HANK project to re-run the evaluation.
- **Data snapshot.** Deposited on Zenodo (see the main README); the raw files can be downloaded again
  with the extractors of the pipeline.

## Annotation

The gold standard of `B_fuzzy_eval` (546 distinct attribute pairs, 538 labelled) was labelled with
LLM assistance and validated pair by pair by the author (`annotation_guidelines.md`;
`bozze_claude_2026.csv` holds the LLM drafts of the pairs that were new in 2026). The 200 new HANK
questions were written with LLM assistance and validated by the author.
