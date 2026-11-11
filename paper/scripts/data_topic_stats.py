# -*- coding: utf-8 -*-
"""Statistics of the harmonised corpus by domain (topic) and year.

Input : <MEDITA_HOME>/data/output/<SOURCE>/*.txt   (harmonised tables, '|' separated;
        only the folder root: dated sub-folders are snapshot copies)
        <MEDITA_HOME>/config/info_<SOURCE>_raw.csv  (catalogue: VAR_CODE -> TAG)
        paper/config/topic_map.csv, topic_overrides.csv (TAG / VAR_CODE -> English topic)
Output: results/data/table_stats.csv       one row per table
        results/data/yearly_obs.csv        observed values per table and year
        results/data/features.csv          column names per table
        results/data/snapshot.json         input folders and files used

Definitions (as in the paper):
  observations = non-missing cells; missing = empty cells;
  yearly observations = non-missing cells of the rows of a year, ANNO itself excluded;
  tables without ANNO (registries) count in Table 2.4 but not in Figure 2.2.
Large tables are read in chunks, so the whole corpus never sits in memory.
"""
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

from common import CONFIG, RESULTS, SOURCES, medita_home

CHUNK = 500_000

# PATCH_ALIM_ESCLUSA_261031: source error excluded from the statistics (as in the experiments).
# MINIS file scambi_di_alimenti_di_origine_animale_01_07_2024_31_12_2024.csv (ALIM_EXCHANGE_VIVI,
# 2nd half of 2024): every line is quoted, so the Transform read it as ONE column whose name starts
# with DATA_ARRIVOPRIMO_DESTINATARIO. Its rows (that column filled) and the column itself are dropped.
EXCLUDE = {("MINIS", "ALIM_EXCHANGE_VIVI"): "DATA_ARRIVOPRIMO_DESTINATARIO"}


def topic_lookup(home):
    tag_map = pd.read_csv(CONFIG / "topic_map.csv").set_index("tag_it")["topic_en"].to_dict()
    overrides = pd.read_csv(CONFIG / "topic_overrides.csv").set_index("var_code")["topic_en"].to_dict()
    codes = {}
    for src in SOURCES:
        f = home / "config" / f"info_{src}_raw.csv"
        cat = pd.read_csv(f, encoding="cp1252")
        if "TAG" not in cat.columns:
            raise SystemExit(f"{f.name} has no TAG column")
        for code, tag in cat[["VAR_CODE", "TAG"]].drop_duplicates().itertuples(index=False):
            codes[(src, code)] = tag
    return codes, tag_map, overrides


def base_code(src, stem, codes):
    """Split tables (AASL_STAFFUNI_TIPO1/2) belong to the catalogue code without the digit."""
    if (src, stem) in codes:
        return stem
    b = re.sub(r"\d+$", "", stem)
    return b if (src, b) in codes else None


def scan_table(path, glued_prefix=None):
    rows = cells = obs = 0
    cols = None
    yearly = defaultdict(int)
    excluded = 0  # PATCH_ALIM_ESCLUSA_261031
    for chunk in pd.read_csv(path, sep="|", dtype=str, keep_default_na=False,
                             na_values=[""], chunksize=CHUNK, low_memory=False):
        if glued_prefix:  # PATCH_ALIM_ESCLUSA_261031
            glued = [c for c in chunk.columns if c.startswith(glued_prefix)]
            if len(glued) != 1:
                raise SystemExit(f"{path.name}: expected 1 column starting with {glued_prefix}, found {glued}")
            bad = chunk[glued[0]].notna()
            if chunk.loc[bad].drop(columns=glued).notna().any(axis=None):
                raise SystemExit(f"{path.name}: rows with the glued column also have other values; rule not safe")
            excluded += int(bad.sum())
            chunk = chunk.loc[~bad].drop(columns=glued)
        if cols is None:
            cols = list(chunk.columns)
        nn = chunk.notna()
        rows += len(chunk)
        cells += chunk.size
        obs += int(nn.values.sum())
        if "ANNO" in chunk.columns:
            year = chunk["ANNO"].str.extract(r"^\s*(\d{4})", expand=False)
            per_row = nn.drop(columns="ANNO").sum(axis=1)
            for y, v in per_row.groupby(year).sum().items():
                yearly[int(y)] += int(v)
    return cols or [], rows, cells, obs, dict(yearly), excluded  # PATCH_ALIM_ESCLUSA_261031


def main():
    home = medita_home()
    codes, tag_map, overrides = topic_lookup(home)
    out = RESULTS / "data"
    out.mkdir(parents=True, exist_ok=True)

    tables, yearly_rows, feat_rows, snapshot = [], [], [], {"medita_home": str(home),
                                                           "created": datetime.now().isoformat(timespec="seconds"),
                                                           "sources": {}}
    for src in SOURCES:
        folder = home / "data" / "output" / src
        files = sorted(folder.glob("*.txt"))
        inputs = sorted(p.name for p in (home / "data" / "input" / src).iterdir() if p.is_dir()) \
            if (home / "data" / "input" / src).is_dir() else []
        snapshot["sources"][src] = {"input_snapshot": inputs[-1] if inputs else None,
                                    "tables": [f.name for f in files]}
        for f in files:
            code = base_code(src, f.stem, codes)
            if code is None:
                raise SystemExit(f"{src}/{f.name}: code not in info_{src}_raw.csv")
            tag = codes[(src, code)]
            topic = overrides.get(code, tag_map.get(tag))
            if topic is None:
                raise SystemExit(f"{src}/{f.name}: TAG '{tag}' missing in paper/config/topic_map.csv")
            print(f"{src}/{f.name} -> {topic}", flush=True)
            cols, rows, cells, obs, yearly, excluded = scan_table(f, EXCLUDE.get((src, f.stem)))  # PATCH_ALIM_ESCLUSA_261031
            if excluded:
                snapshot.setdefault("excluded_rows", {})[f"{src}/{f.name}"] = excluded
                print(f"  excluded {excluded:,} rows (source error, see EXCLUDE)", flush=True)
            tables.append({"source": src, "table": f.stem, "var_code": code, "tag_it": tag,
                           "topic": topic, "records": rows, "features": len(cols), "cells": cells,
                           "observations": obs, "missing": cells - obs, "has_year": "ANNO" in cols,
                           "year_min": min(yearly) if yearly else None,
                           "year_max": max(yearly) if yearly else None})
            yearly_rows += [{"source": src, "table": f.stem, "topic": topic, "year": y, "observations": v}
                            for y, v in sorted(yearly.items())]
            feat_rows += [{"source": src, "table": f.stem, "topic": topic, "feature": c} for c in cols]

    pd.DataFrame(tables).to_csv(out / "table_stats.csv", index=False)
    pd.DataFrame(yearly_rows).to_csv(out / "yearly_obs.csv", index=False)
    pd.DataFrame(feat_rows).to_csv(out / "features.csv", index=False)
    (out / "snapshot.json").write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    print(f"{len(tables)} tables -> {out}")


if __name__ == "__main__":
    main()
