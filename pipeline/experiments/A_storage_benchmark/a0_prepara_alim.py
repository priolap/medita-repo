# -*- coding: utf-8 -*-
r"""
a0_prepara_alim.py  (MEDITA, task A - benchmark dello storage, snapshot unico 29/10/2026)

Decisione 29/10/2026: il file MINIS scambi_di_alimenti_di_origine_animale_01_07_2024_31_12_2024.csv
(ALIM_EXCHANGE_VIVI, 2° semestre 2024) e' escluso come errore della fonte (ogni riga tra virgolette, letta
come una sola colonna), SENZA rifare la Transform: le tabelle in data\output restano come sono e
l'esclusione si applica negli esperimenti.

Per il benchmark questo script scrive, FUORI da OneDrive e senza toccare data\output, una copia di
data\output\MINIS\ALIM_EXCHANGE_VIVI.txt senza le righe di quel file e senza la colonna incollata:
  righe tolte   = righe con la colonna incollata valorizzata (DATA_ARRIVOPRIMO_DESTINATARIO_...NAZIONE)
  colonna tolta = la colonna incollata
Le altre righe e colonne sono riscritte com'erano (lette e scritte come testo, separatore '|').
bench_storage.py (dopo patch_bench_alim_261029.py) usa questa copia al posto della tabella in data\output.

Destinazione: %MEDITA_BENCH_INPUT%\MINIS\ALIM_EXCHANGE_VIVI.txt (default D:\MEDITA_bench_input) e un
riepilogo ALIM_EXCHANGE_VIVI_esclusione.json accanto. Se la copia esiste gia' non la riscrive.

Uso (cmd), dalla cartella MEDITA:
  "C:\Program Files\Python314\python.exe" experiments\A_storage_benchmark\a0_prepara_alim.py
"""
import os
import sys
import json
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = ROOT / "data" / "output" / "MINIS" / "ALIM_EXCHANGE_VIVI.txt"
DEST_DIR = Path(os.environ.get("MEDITA_BENCH_INPUT", r"D:\MEDITA_bench_input")) / "MINIS"
DEST = DEST_DIR / "ALIM_EXCHANGE_VIVI.txt"
PREFIX = "DATA_ARRIVOPRIMO_DESTINATARIO"
FILE_ESCLUSO = "scambi_di_alimenti_di_origine_animale_01_07_2024_31_12_2024.csv"
CHUNK = 500_000


def main():
    if DEST.exists():
        print(f"{DEST} esiste gia': nessuna modifica (spostarlo a mano per rigenerarlo).")
        return
    if "onedrive" in str(DEST).lower():
        sys.exit("STOP: la destinazione e' dentro OneDrive. Impostare MEDITA_BENCH_INPUT fuori da OneDrive.")
    cols = pd.read_csv(SRC, sep="|", nrows=0).columns.tolist()
    glued = [c for c in cols if c.startswith(PREFIX)]
    if len(glued) != 1:
        sys.exit(f"STOP: attesa 1 colonna incollata che inizia con {PREFIX}, trovate {len(glued)}: {glued}")
    g = glued[0]
    keep = [c for c in cols if c != g]
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DEST.with_suffix(".txt.part")
    t0, n_in, n_out, prima = time.time(), 0, 0, True
    for ch in pd.read_csv(SRC, sep="|", dtype=str, keep_default_na=False, na_values=[""], chunksize=CHUNK):
        n_in += len(ch)
        ok = ch[g].isna()
        altre_piene = ch.loc[~ok, keep].notna().any(axis=1).sum()
        if altre_piene:
            sys.exit(f"STOP: {altre_piene} righe hanno sia la colonna incollata sia altre colonne valorizzate: "
                     "la regola di esclusione non e' sicura. Nessuna copia scritta.")
        out = ch.loc[ok, keep]
        n_out += len(out)
        out.to_csv(tmp, sep="|", index=False, header=prima, mode="w" if prima else "a")
        prima = False
        print(f"  {n_in:,} righe lette, {n_in - n_out:,} tolte ({time.time() - t0:.0f} s)", flush=True)
    os.replace(tmp, DEST)
    info = {"origine": str(SRC), "copia": str(DEST), "file_escluso": FILE_ESCLUSO,
            "motivo": "errore della fonte: ogni riga del CSV tra virgolette, letta come una sola colonna",
            "colonna_tolta": g, "righe_origine": n_in, "righe_tolte": n_in - n_out, "righe_copia": n_out,
            "bytes_origine": SRC.stat().st_size, "bytes_copia": DEST.stat().st_size,
            "creato_il": time.strftime("%Y-%m-%d %H:%M:%S")}
    (DEST_DIR / "ALIM_EXCHANGE_VIVI_esclusione.json").write_text(json.dumps(info, indent=2, ensure_ascii=False),
                                                                  encoding="utf-8")
    print(json.dumps(info, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
