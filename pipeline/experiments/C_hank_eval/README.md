# C_hank_eval — Task C (HANK self-contained)

Setup del paper, fissato in `config_c.json`: collezione `medita-news-chunk512-over64-2`
(dataset Kaggle `espritz/medita-news-chunk512-over64-2`), embedding
`paraphrase-multilingual-MiniLM-L12-v2`, chunk 512/64 **caratteri**, distanza L2 (default Chroma),
top-4, prompt verbatim del notebook v10.
Nuove generazioni: Gemma-2 (`google/gemma-2-9b-it`) e Llama-3 (`DeepMount00/Llama-3-8b-Ita`),
4 bit NF4, decoding greedy, max 250 token, seed 100.

## File di lavoro

`annotation/qa_rag_models_comparison_v3.xlsx`, foglio `questions` (formato di `questions_2`):

| Question | Context | ID | LEVEL | HUMAN | gemma2 | llama3 | IS_HALL_gemma2 | IS_HALL_llama3 | NOTE |

- Q001–Q100: domande e gold del paper; Q101–Q300: domande nuove, gold da scrivere usando solo il
  contesto (contesto insufficiente → testo di astensione).
- `gemma2`, `llama3`: risposte di c3. `IS_HALL_*`: 0/1 annotati a mano, come nel paper.
- `python c_qa_workbook.py` si può rilanciare: conserva HUMAN (Q101–Q300), IS_HALL e NOTE, aggiunge
  le risposte di c3 e salva prima il file precedente in `.bak`.

## Flusso

| Passo | Script | Dove | Output |
|---|---|---|---|
| c0 verifica retrieval | `prepara_kaggle_inputs.py`, `kaggle/c0`, `c0_check_repro.py` | Kaggle CPU | `out/kaggle_c0/.../c0_repro_check.xlsx`, `c0_collection_dups.xlsx` |
| c1 domande nuove (C9) | `c1_candidates.json`, `c1_make_workbook.py`, `c1_judge.py`, `c1_select.py` | PC | `annotation/c1_candidati.xlsx`, `out/c1_judge.xlsx`, `annotation/c1_selezione.xlsx` |
| c2 retrieval 300 domande | `c2_prepare.py`, `kaggle/c2`, `c2_retrieve.py` | Kaggle CPU | `out/kaggle_c2/.../c2_contexts.json`, `c2_contexts.xlsx` |
| c3 generazione (C10) | `c3_prepare.py`, `kaggle/c3` | Kaggle GPU | `out/kaggle_c3/out/answers_gemma2.json`, `answers_llama3.json`, `c3_run_info.json` |
| file di lavoro | `c_qa_workbook.py` | PC | `annotation/qa_rag_models_comparison_v3.xlsx` |

Esiti verificati:
- c0: top-4 identico al contesto del paper per 100/100 domande; 1.142.457 chunk, 31.934 copie di testi
  già presenti (articoli duplicati nel corpus).
- c1: 240 candidate scritte con un LLM (Claude), 80 per livello; livello verificato con GPT-4
  (`gpt-4-0613`, prompt Tabella A.9 del DKE, `RAG/scripts/llm_judge_agreement.py`): accordo 67,1%,
  kappa 0,506; 200 estratte a caso stratificando per livello (seed 100).
- c2: 300 domande; per Q001–Q100 top-4 identico al paper (100/100).

## Ambiente sul PC

Venv con il Python installato, fuori da OneDrive (`D:\venvs\hank_c`). Chromadb non serve sul PC:
retrieval e generazione girano su Kaggle (chromadb 0.5.5, come nel paper).

```
D:\venvs\hank_c\Scripts\activate
cd /d pipeline\experiments\C_hank_eval
pip install -r requirements_c.txt
```

Chiavi, mai nei file del progetto:
- OpenAI (c1_judge): variabile d'ambiente `OPENAI_API_KEY` (`setx OPENAI_API_KEY "..."`)
- Kaggle: `%USERPROFILE%\.kaggle\kaggle.json`
- Hugging Face (c3): Secret `HF_TOKEN` collegato al notebook `hank-c3-generate` sul sito Kaggle

## Kaggle da cmd

Gli input stanno nel dataset privato `espritz/hank-c-inputs` (cartella `kaggle/inputs`).

```
kaggle datasets version -p kaggle\inputs -m "messaggio"
kaggle datasets status espritz/hank-c-inputs
kaggle kernels push -p kaggle\c3
kaggle kernels status espritz/hank-c3-generate
kaggle kernels output espritz/hank-c3-generate -p out\kaggle_c3
```

L'errore `'charmap' codec can't encode characters` dopo `kernels output` riguarda solo il log della
CLI su Windows: i file vengono scaricati comunque.
