# -*- coding: utf-8 -*-
"""
C1c - Selezione delle 200 domande nuove con campionamento casuale stratificato per livello.

Perche': le etichette GPT-4 sono gia' note per tutte le 240 candidate. Scegliere a mano
guardandole gonfierebbe l'accordo riportato nel paper; un campionamento casuale (seed fisso)
no, ed e' dichiarabile: "240 candidate, 200 estratte a caso stratificando per livello".

Regole:
  - per livello si estraggono a caso (seed di config_c.json) tante domande quante ne servono
    per arrivare a 100 per livello insieme alle 100 del paper (66 LOW, 67 MID, 67 HIGH);
  - le rimanenti restano come riserve, in ordine casuale;
  - in revisione scarti solo per motivi di contenuto (KEEP = "no" nel foglio selected) e
    sostituisci con la prima riserva dello stesso livello (rilancia lo script con --apply);
  - l'accordo con GPT-4 si ricalcola sulle 200 finali dalle etichette gia' ottenute: nessuna
    nuova chiamata all'API.

Input : c1_candidates.json, out/c1_judge.xlsx, qa_list_setup_final.xlsx (conteggi del paper)
Output: annotation/c1_selezione.xlsx (selected, reserves, agreement_*, summary)

Uso:  python c1_select.py            prima estrazione (non sovrascrive un file esistente)
      python c1_select.py --apply    applica gli scarti segnati in "selected" usando le riserve
"""
import argparse
import importlib.util
import json
import random
import shutil
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
CFG = json.load(open(HERE / "config_c.json", encoding="utf-8"))
JUDGE_X = HERE / "out" / "c1_judge.xlsx"
OUT_X = HERE / "annotation" / "c1_selezione.xlsx"
LEVELS = ["LOW", "MID", "HIGH"]


def resolve(p):
    return Path(p.replace("{rag_root}", CFG["rag_root"]))


def judge_module():
    path = Path(CFG["rag_root"]) / "scripts" / "llm_judge_agreement.py"
    spec = importlib.util.spec_from_file_location("llm_judge_agreement", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def targets():
    paper = pd.read_excel(resolve(CFG["qa_list"]), sheet_name="questions", header=1)
    n = paper["LEVEL"].value_counts().to_dict()
    return {lv: 100 - n.get(lv, 0) for lv in LEVELS}


def load_pool():
    cand = pd.DataFrame(json.load(open(HERE / "c1_candidates.json", encoding="utf-8"))["questions"])
    lab = pd.read_excel(JUDGE_X, sheet_name="labels")[["C_ID", "LLM", "QUESTION"]]
    lab = lab.rename(columns={"QUESTION": "QUESTION_JUDGED"})
    pool = cand.merge(lab, on="C_ID", how="left", validate="one_to_one")
    if pool["LLM"].isna().any():
        sys.exit("[STOP] alcune candidate non hanno etichetta GPT-4 in out/c1_judge.xlsx")
    pool["LEN_CHAR"] = pool["QUESTION"].str.len()
    return pool


def draw(pool, tgt, seed):
    rng = random.Random(seed)
    sel, res = [], []
    for lv in LEVELS:
        ids = sorted(pool.loc[pool["LEVEL_DESIGN"] == lv, "C_ID"])
        rng.shuffle(ids)
        sel += ids[: tgt[lv]]
        res += [(i, k + 1) for k, i in enumerate(ids[tgt[lv]:])]
    selected = pool[pool["C_ID"].isin(sel)].copy()
    selected["KEEP"] = "sì"
    selected["NOTE"] = ""
    order = {i: r for i, r in res}
    reserves = pool[pool["C_ID"].isin(order)].copy()
    reserves["RESERVE_RANK"] = reserves["C_ID"].map(order)
    return selected, reserves.sort_values(["LEVEL_DESIGN", "RESERVE_RANK"])


def apply_discards(selected, reserves):
    drop = selected["KEEP"].astype(str).str.strip().str.lower() == "no"
    log = []
    for lv in LEVELS:
        n_drop = int((drop & (selected["LEVEL_DESIGN"] == lv)).sum())
        avail = reserves[reserves["LEVEL_DESIGN"] == lv].sort_values("RESERVE_RANK")
        if n_drop > len(avail):
            sys.exit(f"[STOP] {lv}: {n_drop} scarti ma solo {len(avail)} riserve")
        take = avail.head(n_drop)
        log += [f"{lv}: sostituita {a} con {b}" for a, b in
                zip(selected.loc[drop & (selected["LEVEL_DESIGN"] == lv), "C_ID"], take["C_ID"])]
        add = take.drop(columns="RESERVE_RANK").assign(KEEP="sì", NOTE="riserva")
        selected = pd.concat([selected, add], ignore_index=True)
        reserves = reserves[~reserves["C_ID"].isin(take["C_ID"])]
    discarded = selected[selected["KEEP"].astype(str).str.strip().str.lower() == "no"]
    selected = selected[selected["KEEP"].astype(str).str.strip().str.lower() != "no"]
    return selected, reserves, discarded, log


def write(selected, reserves, discarded, mod, seed, log):
    df = selected.rename(columns={"LEVEL_DESIGN": "HUMAN"})
    per_cat, summary, conf = mod.compute_agreement(df)
    extra = pd.DataFrame({"metric": ["seed", "n_selected", "n_discarded_content"] + [f"n_{lv}" for lv in LEVELS],
                          "value": [seed, len(selected), len(discarded)] +
                                   [int((selected["LEVEL_DESIGN"] == lv).sum()) for lv in LEVELS]})
    lens = selected.groupby("LEVEL_DESIGN")["LEN_CHAR"].mean().round(1).reindex(LEVELS).reset_index()
    cols = ["C_ID", "LEVEL_DESIGN", "QUESTION", "LEN_CHAR", "TOPIC", "LLM", "KEEP", "NOTE"]
    OUT_X.parent.mkdir(exist_ok=True)
    with pd.ExcelWriter(OUT_X, engine="openpyxl") as w:
        selected.sort_values("C_ID")[cols].to_excel(w, sheet_name="selected", index=False)
        reserves[["C_ID", "LEVEL_DESIGN", "RESERVE_RANK", "QUESTION", "LEN_CHAR", "LLM"]].to_excel(
            w, sheet_name="reserves", index=False)
        if len(discarded):
            discarded[cols].to_excel(w, sheet_name="discarded", index=False)
        per_cat.to_excel(w, sheet_name="agreement_per_category", index=False)
        pd.concat([summary, extra], ignore_index=True).to_excel(w, sheet_name="summary", index=False)
        conf.to_excel(w, sheet_name="confusion_matrix")
        lens.to_excel(w, sheet_name="len_by_level", index=False)
    for line in log:
        print(line)
    print(per_cat.to_string(index=False))
    print(summary.to_string(index=False))
    print(conf.to_string())
    print(f"Creato: {OUT_X}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    mod, seed = judge_module(), CFG["seed"]

    if not args.apply:
        if OUT_X.exists():
            sys.exit(f"[STOP] {OUT_X} esiste gia'. Per applicare gli scarti usa --apply.")
        pool, tgt = load_pool(), targets()
        selected, reserves = draw(pool, tgt, seed)
        write(selected, reserves, selected.iloc[0:0], mod, seed, [f"target: {tgt}"])
        return

    if not OUT_X.exists():
        sys.exit("[STOP] lancia prima python c1_select.py")
    shutil.copy2(OUT_X, OUT_X.with_name(OUT_X.name + ".bak"))
    selected = pd.read_excel(OUT_X, sheet_name="selected")
    reserves = pd.read_excel(OUT_X, sheet_name="reserves")
    pool = load_pool().set_index("C_ID")
    for df in (selected, reserves):
        df["TOPIC"] = df["C_ID"].map(pool["TOPIC"])
    selected["QUESTION"] = selected["QUESTION"].astype(str).str.strip()
    selected["LEN_CHAR"] = selected["QUESTION"].str.len()
    selected, reserves, discarded, log = apply_discards(selected, reserves)
    write(selected, reserves, discarded, mod, seed, log)


if __name__ == "__main__":
    main()
