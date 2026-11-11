# -*- coding: utf-8 -*-
"""
C0 - Verifica di riproducibilita' del retrieval di HANK (prerequisito di C9-C13).

Cosa fa:
  1. apre una COPIA di lavoro della collezione del paper (medita-news-chunk512-over64-2),
     fuori da OneDrive: l'originale non viene mai aperto, quindi un'eventuale migrazione
     del formato da parte di chromadb tocca solo la copia;
  2. riporta nome, numero di chunk e metrica di distanza (hnsw:space) della collezione;
  3. per le 100 domande del paper calcola l'embedding con MiniLM (come HuggingFaceEmbeddings
     di LangChain: nessuna normalizzazione, '\n' -> ' ') e interroga la collezione con top-4,
     come faceva RetrievalQA con il retriever di default;
  4. confronta il contesto ottenuto ("\n\n".join dei 4 chunk, come la chain "stuff") con il
     contesto salvato negli output del paper (results_pro_gemma2.json);
  5. conta i chunk ripetuti nei contesti (paper e nuovi) e salva il top-8 per C13;
  6. con --dup conta i testi duplicati nell'intera collezione (sola lettura).

Input : config_c.json, collezione Chroma, results_pro_gemma2.json, qa_list_setup_final.xlsx
Output: out/c0_repro_check.xlsx  (summary, per_question, top8, env)
        out/c0_collection_dups.xlsx (solo con --dup)

Uso:   python c0_check_repro.py [--dup]
"""

import argparse
import hashlib
import json
import platform
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
CFG = json.load(open(HERE / "config_c.json", encoding="utf-8"))


def resolve(p: str) -> Path:
    return Path(p.replace("{rag_root}", CFG["rag_root"]))


def check_env() -> dict:
    import chromadb
    import sentence_transformers
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "chromadb": chromadb.__version__,
        "sentence_transformers": sentence_transformers.__version__,
        "pandas": pd.__version__,
        "run_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def open_collection():
    import chromadb
    from chromadb.config import Settings
    coll_dir = resolve(CFG["collection_dir_work"])
    if coll_dir.resolve() == resolve(CFG["collection_dir"]).resolve():
        sys.exit("[STOP] collection_dir_work coincide con la collezione del paper: serve una copia.")
    if not (coll_dir / "chroma.sqlite3").exists():
        sys.exit(f"[STOP] chroma.sqlite3 non trovato in {coll_dir}")
    client = chromadb.PersistentClient(path=str(coll_dir),
                                       settings=Settings(anonymized_telemetry=False))
    cols = client.list_collections()
    # chromadb 0.5.x restituisce oggetti Collection, 0.6.x restituisce i nomi
    names = [c if isinstance(c, str) else c.name for c in cols]
    if len(names) != 1:
        print(f"[ATTENZIONE] {len(names)} collezioni trovate: {names}; uso la prima, come il notebook.")
    # embedding_function=None: si interroga solo con embedding calcolati qui
    col = client.get_collection(name=names[0], embedding_function=None)
    return col


def load_paper_questions() -> pd.DataFrame:
    js = resolve(CFG["paper_results_dir"]) / CFG["paper_reference_json"]
    paper = json.load(open(js, encoding="utf-8"))
    qa = pd.read_excel(resolve(CFG["qa_list"]), sheet_name="questions", header=1)
    if len(paper) != len(qa):
        sys.exit(f"[STOP] {len(paper)} risposte nel JSON contro {len(qa)} domande nel qa_list.")
    df = pd.DataFrame({
        "ID": qa["ID"].values,
        "LEVEL": qa["LEVEL"].values,
        "QUESTION_QALIST": qa["QUESTION"].astype(str).str.strip().values,
        "QUESTION_PAPER": [str(x["Question"]).strip() for x in paper],
        "CONTEXT_PAPER": [str(x["Context"]).strip() for x in paper],
    })
    df["QUESTION_SAME"] = df["QUESTION_QALIST"] == df["QUESTION_PAPER"]
    return df


def embed(questions):
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(CFG["embedding_model"], device="cpu")
    texts = [q.replace("\n", " ") for q in questions]  # come HuggingFaceEmbeddings
    return model.encode(texts, convert_to_numpy=True, show_progress_bar=False)


def n_distinct(chunks):
    return len({c.strip() for c in chunks if c.strip()})


def repro_check(col, df):
    k, kmax, sep = CFG["k_main"], CFG["k_max"], CFG["context_separator"]
    emb = embed(df["QUESTION_PAPER"].tolist()).tolist()

    res4 = col.query(query_embeddings=emb, n_results=k,
                     include=["documents", "distances", "metadatas"])
    res8 = col.query(query_embeddings=emb, n_results=kmax,
                     include=["documents", "distances", "metadatas"])

    rows, top8 = [], []
    for i, r in df.iterrows():
        docs = res4["documents"][i]
        ctx_new = sep.join(docs).strip()
        ctx_paper = r["CONTEXT_PAPER"]
        paper_chunks = [c for c in ctx_paper.split(sep) if c.strip()]
        rows.append({
            "ID": r["ID"], "LEVEL": r["LEVEL"], "QUESTION": r["QUESTION_PAPER"],
            "QUESTION_SAME_QALIST": r["QUESTION_SAME"],
            "EXACT_MATCH_CONTEXT": ctx_new == ctx_paper,
            "N_CHUNKS_IN_PAPER_CONTEXT": sum(d.strip() in ctx_paper for d in docs),
            "DISTINCT_CHUNKS_NEW_TOP4": n_distinct(docs),
            "DISTINCT_CHUNKS_PAPER": n_distinct(paper_chunks),
            "TOP4_IDS": " | ".join(res4["ids"][i]),
            "TOP8_PREFIX_EQUALS_TOP4": res8["ids"][i][:k] == res4["ids"][i],
            "DIST_1": res4["distances"][i][0], "DIST_4": res4["distances"][i][-1],
            "CONTEXT_NEW": ctx_new, "CONTEXT_PAPER": ctx_paper,
        })
        for rank, (cid, d, m, doc) in enumerate(zip(res8["ids"][i], res8["distances"][i],
                                                     res8["metadatas"][i], res8["documents"][i]), 1):
            top8.append({"ID": r["ID"], "LEVEL": r["LEVEL"], "RANK": rank, "CHUNK_ID": cid,
                         "DISTANCE": d, "TITLE": (m or {}).get("title", ""),
                         "DATE": (m or {}).get("date", ""), "DOCUMENT": doc})
    return pd.DataFrame(rows), pd.DataFrame(top8)


def collection_dups(col, batch=20000):
    n = col.count()
    seen, counts, ex_ids = {}, Counter(), {}
    t0 = time.time()
    for off in range(0, n, batch):
        got = col.get(limit=batch, offset=off, include=["documents", "metadatas"])
        for cid, doc, m in zip(got["ids"], got["documents"], got["metadatas"]):
            h = hashlib.md5((doc or "").strip().encode("utf-8")).digest()
            counts[h] += 1
            if h not in seen:
                seen[h] = (cid, (m or {}).get("title", ""))
            elif counts[h] <= 6:
                ex_ids.setdefault(h, [seen[h][0]]).append(cid)
        print(f"  letti {min(off + batch, n)}/{n}  ({time.time() - t0:.0f}s)")
    dup_groups = {h: c for h, c in counts.items() if c > 1}
    summary = pd.DataFrame([
        ("chunk nella collezione", n),
        ("testi distinti", len(counts)),
        ("gruppi di testi duplicati", len(dup_groups)),
        ("chunk in gruppi duplicati", sum(dup_groups.values())),
        ("chunk in eccesso (n - distinti)", n - len(counts)),
        ("max ripetizioni di un testo", max(counts.values()) if counts else 0),
    ], columns=["voce", "valore"])
    examples = sorted(dup_groups.items(), key=lambda x: -x[1])[:200]
    ex = pd.DataFrame([{"N_COPIE": c, "TITLE": seen[h][1], "IDS (max 6)": " | ".join(ex_ids.get(h, []))}
                       for h, c in examples])
    return summary, ex


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dup", action="store_true", help="conta i duplicati nell'intera collezione")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)

    env = check_env()
    col = open_collection()
    meta = col.metadata or {}
    info = {"collection_name": col.name, "collection_count": col.count(),
            "hnsw:space": meta.get("hnsw:space", "l2 (default, non impostato)"),
            "collection_metadata": json.dumps(meta, ensure_ascii=False)}
    print(json.dumps(info, ensure_ascii=False, indent=2))

    df = load_paper_questions()
    per_q, top8 = repro_check(col, df)

    n = len(per_q)
    summary = pd.DataFrame([
        ("domande", n),
        ("domande identiche tra JSON paper e qa_list", int(per_q["QUESTION_SAME_QALIST"].sum())),
        ("contesto identico al paper (top-4)", int(per_q["EXACT_MATCH_CONTEXT"].sum())),
        ("tutti e 4 i chunk presenti nel contesto del paper", int((per_q["N_CHUNKS_IN_PAPER_CONTEXT"] == 4).sum())),
        ("media chunk ritrovati su 4", round(per_q["N_CHUNKS_IN_PAPER_CONTEXT"].mean(), 3)),
        ("contesti paper con chunk ripetuti", int((per_q["DISTINCT_CHUNKS_PAPER"] < 4).sum())),
        ("contesti nuovi con chunk ripetuti", int((per_q["DISTINCT_CHUNKS_NEW_TOP4"] < 4).sum())),
        ("top-8 coerente con top-4 (prefisso)", int(per_q["TOP8_PREFIX_EQUALS_TOP4"].sum())),
    ] + [(k, v) for k, v in info.items()], columns=["voce", "valore"])

    out_x = OUT / "c0_repro_check.xlsx"
    with pd.ExcelWriter(out_x, engine="openpyxl") as w:
        summary.to_excel(w, sheet_name="summary", index=False)
        per_q.to_excel(w, sheet_name="per_question", index=False)
        top8.to_excel(w, sheet_name="top8", index=False)
        pd.DataFrame(list(env.items()), columns=["voce", "valore"]).to_excel(w, sheet_name="env", index=False)
    print(summary.to_string(index=False))
    print(f"Creato: {out_x}")

    if args.dup:
        print("Conteggio duplicati sull'intera collezione (sola lettura)...")
        s, ex = collection_dups(col)
        out_d = OUT / "c0_collection_dups.xlsx"
        with pd.ExcelWriter(out_d, engine="openpyxl") as w:
            s.to_excel(w, sheet_name="summary", index=False)
            ex.to_excel(w, sheet_name="examples_top200", index=False)
        print(s.to_string(index=False))
        print(f"Creato: {out_d}")


if __name__ == "__main__":
    main()
