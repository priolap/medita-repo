# -*- coding: utf-8 -*-
"""
B4 - statistiche del fuzzy matching di MEDITA, a partire dal log del dry run (dryrun_fuzzy.py).

Due comandi:

  estrai   dal log del dry run tiene solo le righe in cui il fuzzy viene chiamato, rinomini o no:
             canonical  colonna -> nome canonico piu' simile (soglia: ratio >= 90)
             files      colonna nuova -> colonne del file precedente (soglia: ratio >= 90)
             sheets     foglio -> rappresentante del gruppo (soglia: ratio >= 88)
           e aggiunge la colonna LABEL vuota da compilare: MATCH, NON_MATCH oppure INCERTO.
           python b4_stats.py estrai --log <fuzzy_dryrun_...csv> [--log <altro>] --out <da_annotare.csv>

  stats    dal CSV annotato calcola, per ogni step:
             - matrice di confusione alla soglia della piattaforma (decisione reale del log);
             - curva di sensibilita' con soglia da 80 a 95: P, R, F1;
             - AUC e AP con il ratio come punteggio.
           Le righe INCERTO o senza LABEL sono escluse e contate.
           python b4_stats.py stats --csv <annotato.xlsx o .csv> --out <cartella>
           Risultati in <cartella>/b4_risultati.xlsx (fogli confusione, curva, auc_ap, escluse) e b4_table.tex.

Regole della curva: la rinomina avviene se ratio >= soglia,
tranne quando il log dice che la piattaforma l'ha bloccata per un altro motivo
(not_renamed_suffix, not_renamed_target_already_in_table, above_threshold_not_in_dictionary):
quelle righe restano non rinominate a ogni soglia.
"""
import argparse
import csv
import os
import sys

FUZZY_STEPS = ("canonical", "files", "sheets")
SKIP = {"identical_columns", "new_group"}                       # nessun confronto fuzzy
BLOCKED = {"not_renamed_suffix", "not_renamed_target_already_in_table", "above_threshold_not_in_dictionary",
           "target_already_in_table", "above_threshold_in_dictionary"}  # PATCH_B4_BLOCCATE_261029: nomi del log attuale
POSITIVE_DEC = {"renamed", "joined"}
GE = {"sheets", "canonical", "files"}                         # soglia con >= per tutti gli step (come nel paper)
THRESHOLDS = range(80, 96)


def read_table(path):
    """Legge il file annotato: Excel (foglio Annotazione, o il primo) oppure CSV."""
    if path.lower().endswith((".xlsx", ".xlsm", ".xls")):
        import pandas as pd
        x = pd.read_excel(path, sheet_name=None, dtype=str)
        df = x.get("Annotazione", next(iter(x.values()))).fillna("")
        return df.to_dict("records")
    return read_csv(path)


def write_xlsx(path, sheets):
    """sheets: lista di (nome_foglio, righe, campi). Numeri come numeri, intestazione in grassetto."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows, fields in sheets:
        ws = wb.create_sheet(name)
        ws.append(fields)
        for r in rows:
            ws.append([r.get(f, "") for f in fields])
        for row in ws.iter_rows():
            for c in row:
                c.font = Font(name="Arial", size=10, bold=(c.row == 1))
                if isinstance(c.value, float):
                    c.number_format = "0.000"
        for i, f in enumerate(fields, 1):
            ws.column_dimensions[ws.cell(1, i).column_letter].width = max(10, len(f) + 2)
    wb.save(path)


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def cmd_estrai(a):
    rows = []
    for p in a.log:
        for r in read_csv(p):
            if r["step"] in FUZZY_STEPS and r["decision"] not in SKIP and r["ratio"] != "":
                r["LABEL"] = ""
                r["NOTE"] = ""
                rows.append(r)
    fields = ["source", "snapshot", "var_code", "file_prev", "file", "sheet", "step", "item_a", "item_b",
              "ratio", "threshold", "decision", "examples", "LABEL", "NOTE"]
    write_csv(a.out, rows, fields)
    by = {}
    for r in rows:
        by[(r["step"], r["decision"])] = by.get((r["step"], r["decision"]), 0) + 1
    print(f"{a.out}: {len(rows)} righe in cui interviene il fuzzy")
    for k in sorted(by):
        print(f"  {k[0]:10s} {k[1]:36s} {by[k]}")


def blocked(r):
    """Rinomina bloccata per un motivo diverso dal ratio (colonna bloccata_da o decision del log originale)."""
    return bool(str(r.get("bloccata_da", "")).strip()) or r["decision"] in BLOCKED


def predicted(r, t):
    if blocked(r):
        return 0
    s = float(r["ratio"])
    return int(s >= t if r["step"] in GE else s > t)


def confusion(rows, pred):
    tp = sum(1 for r in rows if pred(r) and r["y"])
    fp = sum(1 for r in rows if pred(r) and not r["y"])
    fn = sum(1 for r in rows if not pred(r) and r["y"])
    tn = sum(1 for r in rows if not pred(r) and not r["y"])
    p = tp / (tp + fp) if tp + fp else float("nan")
    rc = tp / (tp + fn) if tp + fn else float("nan")
    f1 = 2 * p * rc / (p + rc) if tp and (p + rc) else 0.0
    return dict(TP=tp, FP=fp, FN=fn, TN=tn, P=p, R=rc, F1=f1)


def auc_ap(rows):
    pos = [float(r["ratio"]) for r in rows if r["y"]]
    neg = [float(r["ratio"]) for r in rows if not r["y"]]
    if not pos or not neg:
        return float("nan"), float("nan")
    # AUC (Mann-Whitney, pareggi a meta')
    gt = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    auc = gt / (len(pos) * len(neg))
    # AP: somma su soglie distinte (decrescenti) di (R_k - R_{k-1}) * P_k
    scores = sorted({float(r["ratio"]) for r in rows}, reverse=True)
    ap, r_prev, npos = 0.0, 0.0, len(pos)
    for s in scores:
        sel = [r for r in rows if float(r["ratio"]) >= s]
        tp = sum(1 for r in sel if r["y"])
        rec, prec = tp / npos, tp / len(sel)
        ap += (rec - r_prev) * prec
        r_prev = rec
    return auc, ap


def fmt(x):
    return "" if x != x else f"{x:.3f}"


def cmd_stats(a):
    rows = read_table(a.csv)
    os.makedirs(a.out, exist_ok=True)
    lab = {"MATCH": 1, "NON_MATCH": 0, "1": 1, "0": 0}
    excluded = {}
    data = {}
    for r in rows:
        L = r.get("LABEL", "").strip().upper()
        if L not in lab:
            key = (r["step"], L or "(vuota)")
            excluded[key] = excluded.get(key, 0) + 1
            continue
        r["y"] = lab[L]
        data.setdefault(r["step"], []).append(r)
    if not data:
        sys.exit("Nessuna riga con LABEL MATCH/NON_MATCH: niente da calcolare.")

    def distinct(rows_):
        """Una riga per coppia di nomi (step, item_a, item_b) con la stessa decisione e la stessa etichetta."""
        seen, out = set(), []
        for r in rows_:
            k = (r["step"], r["item_a"], r["item_b"], r["decision"], str(r.get("bloccata_da", "")), r["y"])
            if k not in seen:
                seen.add(k)
                out.append(r)
        return out

    # unita' di valutazione: la coppia distinta (step, item_a, item_b). Il fuzzy e' deterministico: la stessa coppia
    # ha sempre lo stesso ratio. "occorrenze" = quante volte la piattaforma ha applicato il fuzzy (righe del log).
    dist = {s: distinct(v) for s, v in data.items()}
    conf, curve, summ = [], [], []
    for step in [s for s in FUZZY_STEPS if s in dist]:
        d = dist[step]
        thr = str(d[0].get("threshold") or d[0].get("soglia", "")).replace(">=", "").replace(">", "").strip()
        c = confusion(d, lambda r: r["decision"] in POSITIVE_DEC)          # decisione reale della piattaforma
        conf.append(dict(step=step, soglia=(">=" if step in GE else ">") + thr, coppie=len(d),
                         occorrenze=len(data[step]), **c))
        for t in THRESHOLDS:
            ct = confusion(d, lambda r, t=t: predicted(r, t))
            curve.append(dict(step=step, soglia=t, **ct))
        auc, ap = auc_ap(d)
        summ.append(dict(step=step, coppie=len(d), positivi=sum(r["y"] for r in d), AUC=auc, AP=ap))

    ex = [dict(step=k[0], LABEL=k[1], righe=v) for k, v in sorted(excluded.items())]
    nan0 = lambda L: [{k: ("" if isinstance(v, float) and v != v else (round(v, 3) if isinstance(v, float) else v))
                       for k, v in x.items()} for x in L]
    # errori alla soglia della piattaforma (una riga per coppia, con il numero di occorrenze):
    # FP = rinominata/unita ma NON_MATCH; FN = non rinominata ma MATCH
    errd = {}
    for step in [s for s in FUZZY_STEPS if s in data]:
        for r in data[step]:
            p_ = r["decision"] in POSITIVE_DEC
            if p_ != bool(r["y"]):
                k = (step, r["item_a"], r["item_b"])
                if k not in errd:
                    errd[k] = dict(step=step, errore="FP" if p_ else "FN", occorrenze=0, var_code=r.get("var_code", ""),
                                   item_a=r["item_a"], item_b=r["item_b"], ratio=int(float(r["ratio"])),
                                   decision=r["decision"], bloccata_da=r.get("bloccata_da", ""), NOTE=r.get("NOTE", ""))
                errd[k]["occorrenze"] += 1
    err = sorted(errd.values(), key=lambda e: (e["step"], e["errore"], -e["ratio"]))
    ef = ["step", "errore", "occorrenze", "var_code", "item_a", "item_b", "ratio", "decision", "bloccata_da", "NOTE"]
    write_xlsx(os.path.join(a.out, "b4_risultati.xlsx"),
               [("confusione", nan0(conf), list(conf[0])), ("curva", nan0(curve), list(curve[0])),
                ("auc_ap", nan0(summ), list(summ[0])), ("errori", err, ef), ("escluse", ex, ["step", "LABEL", "righe"])])

    with open(os.path.join(a.out, "b4_table.tex"), "w", encoding="utf-8") as f:
        f.write("\\begin{tabular}{llrrrrrrrrrr}\n\\hline\n")
        f.write("Step & Soglia & Coppie & Occorrenze & TP & FP & FN & TN & P & R & F1 & AUC \\\\\n\\hline\n")
        for c, s in zip(conf, summ):
            sg = c["soglia"].replace(">=", "$\\geq$ ").replace(">", "$>$ ")
            f.write(f"{c['step']} & {sg} & {c['coppie']} & {c['occorrenze']} & "
                    f"{c['TP']} & {c['FP']} & {c['FN']} & {c['TN']} & {fmt(c['P'])} & {fmt(c['R'])} & "
                    f"{fmt(c['F1'])} & {fmt(s['AUC'])} \\\\\n")
        f.write("\\hline\n\\end{tabular}\n")

    for c, s in zip(conf, summ):
        print(f"{c['step']:10s} soglia {c['soglia']:>4s}  coppie={c['coppie']:4d} (occorrenze {c['occorrenze']})  TP={c['TP']} FP={c['FP']} FN={c['FN']} TN={c['TN']}"
              f"  P={fmt(c['P'])} R={fmt(c['R'])} F1={fmt(c['F1'])}  AUC={fmt(s['AUC'])} AP={fmt(s['AP'])}")
    print(f"Escluse (INCERTO o senza LABEL): {sum(excluded.values())}")
    print(f"File in {a.out}: b4_risultati.xlsx, b4_table.tex")


def main():
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)
    e = sp.add_parser("estrai")
    e.add_argument("--log", action="append", required=True)
    e.add_argument("--out", required=True)
    s = sp.add_parser("stats")
    s.add_argument("--csv", required=True)
    s.add_argument("--out", required=True)
    a = p.parse_args()
    {"estrai": cmd_estrai, "stats": cmd_stats}[a.cmd](a)


if __name__ == "__main__":
    main()
