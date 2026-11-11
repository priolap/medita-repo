# -*- coding: utf-8 -*-
"""
Kernel Kaggle (GPU) per c3: generazione delle risposte con il protocollo del paper (task C10).

Protocollo (da config_c.json, identico per tutti i generatori):
  - prompt verbatim del notebook v10, contesto = top-4 di c2 uniti con "\n\n" (come la chain "stuff");
  - quantizzazione 4 bit NF4, double quant, compute fp16 (BitsAndBytesConfig del paper);
  - decoding greedy (do_sample=False), max_new_tokens=250, seed 100;
  - post-processing della risposta con la stessa extract_details del notebook v10, applicata a
    prompt + testo generato (come l'output di HuggingFacePipeline con return_full_text=True).
Generatori: config_c.json["generators"] (gemma2 = google/gemma-2-9b-it, llama3 = DeepMount00/Llama-3-8b-Ita).
Token HF: Kaggle Secret "HF_TOKEN" (da collegare al notebook dal sito, una volta).

Input : /kaggle/input/hank-c-inputs/{config_c.json, c2_contexts.json}
Output: /kaggle/working/out/answers_<modello>.json, c3_run_info.json, c3_log.txt
"""
import hashlib
import json
import os
import platform
import random
import re
import subprocess
import sys
import time
from pathlib import Path

IN = Path(os.environ.get("C_KAGGLE_INPUT", "/kaggle/input"))
OUT = Path(os.environ.get("C_KAGGLE_WORK", "/kaggle/working")) / "out"
DRY = os.environ.get("C_DRY") == "1"


def find_one(name):
    hits = sorted(IN.rglob(name))
    if len(hits) != 1:
        sys.exit(f"[STOP] {name}: trovati {len(hits)} file in {IN}: {hits}")
    return hits[0]


# --- post-processing identico al notebook def-grid-rag-v10-qav2.ipynb ---------------------------
def extract_details(result):
    prompt_pattern = r"### \[INST\](.*?)Sezioni di contesto:"
    context_pattern = r"Sezioni di contesto:(.*?)Domanda:"
    question_pattern = r"Domanda:(.*?)\[/INST\]"
    answer_pattern = r"Risposta:(.*?)(?=\n#|### \[INST\]|$)"
    prompt_match = re.search(prompt_pattern, result, re.DOTALL)
    prompt = prompt_match.group(1).strip() if prompt_match else ""
    context_match = re.search(context_pattern, result, re.DOTALL)
    context = context_match.group(1).strip() if context_match else ""
    question_match = re.search(question_pattern, result, re.DOTALL)
    question = question_match.group(1).strip() if question_match else ""
    answer_match = re.search(answer_pattern, result, re.DOTALL)
    answer = answer_match.group(1).strip() if answer_match else ""
    answer = re.sub(r'```\s*', '', answer).strip()
    answer = re.sub(r'\[.*?\]', '', answer).strip()
    answer = answer.replace("INST", "").strip()
    answer = answer.rstrip('#').strip()
    return prompt, question, context, answer
# -------------------------------------------------------------------------------------------------


def set_seed(seed):
    import numpy as np
    import torch
    from transformers import set_seed as hf_set_seed
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    hf_set_seed(seed)


def hf_token():
    try:
        from kaggle_secrets import UserSecretsClient
        return UserSecretsClient().get_secret("HF_TOKEN")
    except Exception as e:
        sys.exit(f"[STOP] Secret HF_TOKEN non disponibile ({e}): collegalo al notebook dal sito Kaggle.")


def load_model(path, cfg, token):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    q = cfg["quantization"]
    bnb = BitsAndBytesConfig(load_in_4bit=q["load_in_4bit"], bnb_4bit_quant_type=q["bnb_4bit_quant_type"],
                             bnb_4bit_use_double_quant=q["bnb_4bit_use_double_quant"],
                             bnb_4bit_compute_dtype=getattr(torch, q["bnb_4bit_compute_dtype"]))
    tok = AutoTokenizer.from_pretrained(path, token=token)
    model = AutoModelForCausalLM.from_pretrained(path, quantization_config=bnb, torch_dtype=torch.float16,
                                                 device_map="auto", token=token)
    model.eval()
    return tok, model


def generate_all(name, path, records, cfg, token, log):
    import torch
    tok, model = load_model(path, cfg, token)
    pad = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    dec = cfg["decoding"]
    out, t_all = [], time.time()
    for i, r in enumerate(records):
        prompt = cfg["prompt_template"].format(context=r["CONTEXT"], question=r["QUESTION"])
        enc = tok(prompt, return_tensors="pt").to(model.device)
        t0 = time.time()
        with torch.no_grad():
            gen = model.generate(**enc, do_sample=dec["do_sample"], max_new_tokens=dec["max_new_tokens"],
                                 temperature=None, top_p=None, top_k=None, pad_token_id=pad)
        new_ids = gen[0][enc["input_ids"].shape[1]:]
        generated = tok.decode(new_ids, skip_special_tokens=True)
        _, _, _, answer = extract_details(prompt + generated)
        out.append({"ID": r["ID"], "SOURCE": r["SOURCE"], "LEVEL": r["LEVEL"], "QUESTION": r["QUESTION"],
                    "CONTEXT": r["CONTEXT"], "ANSWER": answer, "RAW_GENERATION": generated,
                    "N_NEW_TOKENS": int(new_ids.shape[0]), "SECONDS": round(time.time() - t0, 2)})
        if (i + 1) % 25 == 0:
            json.dump(out, open(OUT / f"answers_{name}.partial.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            log.write(f"{name}: {i + 1}/{len(records)}  ({time.time() - t_all:.0f}s)\n"); log.flush()
    json.dump(out, open(OUT / f"answers_{name}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    p = OUT / f"answers_{name}.partial.json"
    if p.exists():
        p.unlink()
    info = {"hf_id": path, "commit_hash": getattr(model.config, "_commit_hash", None),
            "seconds_total": round(time.time() - t_all, 1),
            "abstentions": sum(cfg["abstention_text"].lower() in a["ANSWER"].lower() for a in out)}
    del model
    torch.cuda.empty_cache()
    return info


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = json.load(open(find_one("config_c.json"), encoding="utf-8"))
    records = json.load(open(find_one("c2_contexts.json"), encoding="utf-8"))
    print(f"{len(records)} domande, generatori: {cfg['generators']}")
    if DRY:
        r = records[0]
        print(cfg["prompt_template"].format(context=r["CONTEXT"], question=r["QUESTION"])[:600])
        return

    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "bitsandbytes", "accelerate"], check=True)
    import torch, transformers, bitsandbytes
    set_seed(cfg["seed"])
    token = hf_token()
    log = open(OUT / "c3_log.txt", "w", encoding="utf-8")
    info = {"python": platform.python_version(), "torch": torch.__version__,
            "transformers": transformers.__version__, "bitsandbytes": bitsandbytes.__version__,
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none",
            "decoding": cfg["decoding"], "quantization": cfg["quantization"], "seed": cfg["seed"],
            "prompt_sha1": hashlib.sha1(cfg["prompt_template"].encode("utf-8")).hexdigest(),
            "n_questions": len(records), "models": {}}
    for name, path in cfg["generators"].items():
        log.write(f"== {name} ({path})\n"); log.flush()
        info["models"][name] = generate_all(name, path, records, cfg, token, log)
        json.dump(info, open(OUT / "c3_run_info.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log.close()
    print(json.dumps(info, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
