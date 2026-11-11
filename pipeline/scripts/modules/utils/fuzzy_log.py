# -*- coding: utf-8 -*-
"""
fuzzy_log - log dettagliato di ogni decisione di armonizzazione dei nomi nella Transform (PATCH_FUZZY_LOG).

Una riga per ogni confronto effettuato dal codice:
  step = dictionary      colonna rinominata dal dizionario (cols_attributes.json, corrispondenza esatta)
         canonical_name  colonna che ha gia' un nome canonico (nessuna azione)
         canonical       fuzzy sui nomi canonici (stage 4 di input_cleaner): colonna -> nome canonico piu' simile
         files           FilesHandler.fuzzy_labeler: colonna nuova x colonna del file precedente (stesso VAR_CODE)
         sheets          SheetsHandler.group_similar_sheets: foglio x rappresentante del gruppo
  ratio = fuzz.ratio, threshold = soglia applicata, decision = esito reale.
Il contesto (fonte, snapshot, VAR_CODE, file, foglio) viene impostato da data_miner / sheets_handler.
export() scrive logs/fuzzy/fuzzy_log_<FONTE>_<snapshot>_<data_ora>.csv: non tocca info_<FONTE>.json ne' data/output.
"""
import csv
import os
import time

FIELDS = ["source", "snapshot", "var_code", "file_prev", "file", "sheet", "step", "num",
          "item_a", "item_b", "ratio", "threshold", "decision", "examples"]
THRESHOLDS = {"dictionary": "", "canonical_name": "", "canonical": 90, "files": 90, "sheets": 88}
RECORDS = []
CONTEXT = {"source": "", "snapshot": "", "var_code": "", "file_prev": "", "file": "", "sheet": ""}


def set_context(source="", snapshot="", var_code="", file="", sheet=""):
    same_var = var_code == CONTEXT["var_code"] and source == CONTEXT["source"]
    prev = CONTEXT["file"] if same_var and file != CONTEXT["file"] else (CONTEXT["file_prev"] if same_var else "")
    CONTEXT.update(source=source, snapshot=snapshot, var_code=var_code, file_prev=prev, file=file, sheet=sheet)


def set_sheet(sheet):
    CONTEXT["sheet"] = sheet


def examples(df, col, n=5):
    try:
        if col not in df.columns:
            return ""
        s = df[col]
        if getattr(s, "ndim", 1) > 1:
            s = s.iloc[:, 0]
        vals = []
        for v in s.head(5000).dropna().astype(str):
            v = v.strip()
            if v and v.lower() != "nan" and v not in vals:
                vals.append(v[:40])
            if len(vals) >= n:
                break
        return " | ".join(vals)
    except Exception:
        return ""


def record(step, item_a, item_b, ratio, decision, num="", examples=""):
    RECORDS.append({**CONTEXT, "step": step, "num": num, "item_a": item_a, "item_b": item_b,
                    "ratio": "" if ratio is None else ratio, "threshold": THRESHOLDS.get(step, ""),
                    "decision": decision, "examples": examples})


def export(folder, source, snapshot):
    """Scrive le righe della fonte e le toglie dalla memoria; restituisce il percorso del file."""
    rows = [r for r in RECORDS if r["source"] == source]
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"fuzzy_log_{source}_{snapshot}_{time.strftime('%Y%m%d_%H%M%S')}.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    RECORDS[:] = [r for r in RECORDS if r["source"] != source]
    return path
