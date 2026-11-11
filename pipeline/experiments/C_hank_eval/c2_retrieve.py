# -*- coding: utf-8 -*-
"""
C2b - Retrieval sulle 300 domande del benchmark (gira su Kaggle, chromadb 0.5.5).

Riusa da c0_check_repro.py (stessa cartella) check_env, open_collection ed embed, cioe'
lo stesso embedding e la stessa interrogazione verificati in c0 (100/100 identici al paper).
  - top-4 con n_results=4: e' il contesto passato al generatore (come RetrievalQA nel paper);
  - top-8 con n_results=8: serve per C13 (recall@k, hit@k, nDCG);
  - per Q001-Q100 controlla di nuovo che il top-4 coincida con il contesto del paper.

Input : benchmark_300.json, config_c.json, collezione, results_pro_gemma2.json
Output: out/c2_contexts.json   (per c3 e per l'annotazione)
        out/c2_contexts.xlsx   (contexts, top8, summary, env)

Uso:  python c2_retrieve.py
"""
import json
from pathlib import Path

import pandas as pd

import c0_check_repro as c0

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"


def n_distinct(chunks):
    return len({c.strip() for c in chunks if c.strip()})


def main():
    OUT.mkdir(exist_ok=True)
    env = c0.check_env()
    col = c0.open_collection()
    k, kmax, sep = c0.CFG["k_main"], c0.CFG["k_max"], c0.CFG["context_separator"]

    bench = json.load(open(HERE / "benchmark_300.json", encoding="utf-8"))
    paper_json = c0.resolve(c0.CFG["paper_results_dir"]) / c0.CFG["paper_reference_json"]
    paper_ctx = [str(x["Context"]).strip() for x in json.load(open(paper_json, encoding="utf-8"))]

    emb = c0.embed([b["QUESTION"] for b in bench]).tolist()
    r4 = col.query(query_embeddings=emb, n_results=k, include=["documents", "distances", "metadatas"])
    r8 = col.query(query_embeddings=emb, n_results=kmax, include=["documents", "distances", "metadatas"])

    records, rows, top8 = [], [], []
    for i, b in enumerate(bench):
        docs4 = r4["documents"][i]
        ctx = sep.join(docs4).strip()
        same_paper = (ctx == paper_ctx[i]) if b["SOURCE"] == "paper" else None
        rec = {**b,
               "CONTEXT": ctx,
               "TOP4_IDS": r4["ids"][i], "TOP4_DIST": r4["distances"][i], "TOP4_DOCS": docs4,
               "TOP8_IDS": r8["ids"][i], "TOP8_DIST": r8["distances"][i], "TOP8_DOCS": r8["documents"][i],
               "TOP8_TITLES": [(m or {}).get("title", "") for m in r8["metadatas"][i]],
               "TOP8_DATES": [(m or {}).get("date", "") for m in r8["metadatas"][i]],
               "SAME_AS_PAPER_CONTEXT": same_paper}
        records.append(rec)
        rows.append({"ID": b["ID"], "C_ID": b["C_ID"], "SOURCE": b["SOURCE"], "LEVEL": b["LEVEL"],
                     "QUESTION": b["QUESTION"], "CONTEXT": ctx, "DISTINCT_CHUNKS_TOP4": n_distinct(docs4),
                     "DIST_1": r4["distances"][i][0], "DIST_4": r4["distances"][i][-1],
                     "SAME_AS_PAPER_CONTEXT": same_paper})
        for rank in range(len(r8["ids"][i])):
            top8.append({"ID": b["ID"], "LEVEL": b["LEVEL"], "RANK": rank + 1, "CHUNK_ID": r8["ids"][i][rank],
                         "DISTANCE": r8["distances"][i][rank], "TITLE": rec["TOP8_TITLES"][rank],
                         "DATE": rec["TOP8_DATES"][rank], "DOCUMENT": r8["documents"][i][rank]})

    df = pd.DataFrame(rows)
    pap = df[df["SOURCE"] == "paper"]
    summary = pd.DataFrame([
        ("domande", len(df)),
        ("paper: top-4 identico al contesto del paper", int(pap["SAME_AS_PAPER_CONTEXT"].sum())),
        ("contesti con chunk ripetuti (tutte)", int((df["DISTINCT_CHUNKS_TOP4"] < k).sum())),
        ("contesti con chunk ripetuti (nuove)", int((df.loc[df["SOURCE"] == "new", "DISTINCT_CHUNKS_TOP4"] < k).sum())),
        ("k_main", k), ("k_max", kmax), ("collection", col.name), ("collection_count", col.count()),
    ], columns=["voce", "valore"])

    json.dump(records, open(OUT / "c2_contexts.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with pd.ExcelWriter(OUT / "c2_contexts.xlsx", engine="openpyxl") as w:
        summary.to_excel(w, sheet_name="summary", index=False)
        df.to_excel(w, sheet_name="contexts", index=False)
        pd.DataFrame(top8).to_excel(w, sheet_name="top8", index=False)
        pd.DataFrame(list(env.items()), columns=["voce", "valore"]).to_excel(w, sheet_name="env", index=False)
    print(summary.to_string(index=False))
    print("Creato:", OUT / "c2_contexts.json", "e", OUT / "c2_contexts.xlsx")


if __name__ == "__main__":
    main()
