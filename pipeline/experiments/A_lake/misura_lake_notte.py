# -*- coding: utf-8 -*-
"""
misura_lake_notte.py - footprint del lake su disco e tempo della Load sul lake. DA ESEGUIRE A PC LIBERO.
Creato il 09/11/2026 (punti aperti del passaggio al lakehouse).

Cosa misura
1. Load completa (scripts/load.py, la stessa del MASTER) scritta in un lake NUOVO e temporaneo
   (MEDITA/lake_misura_<data_ora>/), cosi' il tempo e' quello di una prima Load (catalogo bronze con SHA-256
   di tutti i grezzi, silver, gold) e non tocca il lake vero. Tempi per zona e totale (time.perf_counter).
   Con --ripetizioni N la Load si ripete N volte, ogni volta in un lake nuovo.
2. Footprint su disco del lake temporaneo (una sola versione per tabella): byte per zona, file Parquet,
   file del _delta_log; confronto con DB.sql + DB_ts.sql (cercati in dashboard/db/ e dashboard/db/old/).
3. Footprint del lake vero (MEDITA/lake/): byte totali e byte dell'ultima versione di ogni tabella
   (la differenza e' il costo delle versioni conservate per il time travel).
Alla fine i lake temporanei vengono SPOSTATI in _cestinare/ (non cancellati).

Output: experiments/A_lake/out/misura_lake_<data_ora>.xlsx (fogli: sintesi, tempi, footprint_zone,
        footprint_tabelle, macchina) e log in logs/Update_<data>_misura_lake.log
Uso (dalla cartella MEDITA, a PC libero, OneDrive in pausa):
  "C:\\Program Files\\Python314\\python.exe" experiments\\A_lake\\misura_lake_notte.py [--ripetizioni N]
"""
import os
import sys
import time
import shutil
import logging
import platform
import argparse
import datetime as dt

import pandas as pd

HOME = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
homepath = HOME.replace('\\', '/') + '/'
sys.path.append(homepath)

from scripts.modules.utils import prompt_reader, logger   # noqa: E402
from scripts import load as l                             # noqa: E402
from deltalake import DeltaTable                          # noqa: E402
import pyarrow                                            # noqa: E402
import pyarrow.compute                                    # noqa: E402


def dimensioni(root):
    """Byte, file Parquet e file del _delta_log per zona e per tabella."""
    zone, tabelle = [], []
    for zona in ('bronze', 'silver', 'gold', '_lake_log'):
        base = os.path.join(root, zona)
        if not os.path.isdir(base):
            continue
        dirs = [base] if zona == '_lake_log' else [os.path.join(base, d) for d in sorted(os.listdir(base))]
        tz = {'ZONA': zona, 'TABELLE': 0, 'BYTE': 0, 'FILE_PARQUET': 0, 'FILE_DELTA_LOG': 0, 'BYTE_ULTIMA_VERSIONE': 0}
        for d in dirs:
            if not os.path.isdir(os.path.join(d, '_delta_log')):
                continue
            b = npq = nlog = 0
            for cur, _, files in os.walk(d):
                for f in files:
                    s = os.path.getsize(os.path.join(cur, f))
                    b += s
                    if '_delta_log' in cur:
                        nlog += 1
                    elif f.endswith('.parquet'):
                        npq += 1
            dtab = DeltaTable(d)
            add = pyarrow.table(dtab.get_add_actions(flatten=True))   # file dell'ultima versione
            ultima = int(pyarrow.compute.sum(add['size_bytes']).as_py() or 0) if add.num_rows else 0
            tabelle.append({'ZONA': zona, 'TABELLA': os.path.basename(d), 'VERSIONE': dtab.version(), 'BYTE': b,
                            'BYTE_ULTIMA_VERSIONE': ultima, 'FILE_PARQUET': npq, 'FILE_DELTA_LOG': nlog})
            tz['TABELLE'] += 1
            tz['BYTE'] += b
            tz['FILE_PARQUET'] += npq
            tz['FILE_DELTA_LOG'] += nlog
            tz['BYTE_ULTIMA_VERSIONE'] += ultima
        zone.append(tz)
    return pd.DataFrame(zone), pd.DataFrame(tabelle)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ripetizioni', type=int, default=1)
    args = ap.parse_args()
    stamp = dt.datetime.now().strftime('%Y%m%d_%H%M%S')
    log = logger.Logger(log_file=f"{homepath}logs/Update_{stamp[:8]}_misura_lake.log", log_level=logging.INFO)
    _, _, _, sources_list = prompt_reader.PromptReader('paolap', f"{homepath}config/PROMPT.json",
                                                       log, stamp[:8]).read_prompt()
    macchina = {'DATA_ORA': stamp, 'PIATTAFORMA': platform.platform(), 'PROCESSORE': platform.processor(),
                'CPU_LOGICHE': os.cpu_count(), 'PYTHON': platform.python_version()}
    try:
        import psutil
        macchina['RAM_GB'] = round(psutil.virtual_memory().total / 1e9, 1)
        macchina['RAM_LIBERA_GB_INIZIO'] = round(psutil.virtual_memory().available / 1e9, 1)
        macchina['CPU_USO_PERC_INIZIO'] = psutil.cpu_percent(interval=2)
    except ImportError:
        macchina['NOTA'] = 'psutil non installato: RAM e uso CPU non registrati'
    import duckdb, deltalake  # noqa: E401
    macchina.update({'DUCKDB': duckdb.__version__, 'DELTALAKE': deltalake.__version__,
                     'PYARROW': pyarrow.__version__, 'PANDAS': pd.__version__})

    tempi, temporanei = [], []
    for r in range(1, args.ripetizioni + 1):
        root = os.path.join(HOME, f"lake_misura_{stamp}_r{r}")
        temporanei.append(root)
        lp = l.LoadProcess(homepath, sources_list, log, lake_root=root.replace('\\', '/'), bronze_hash=True)
        riga = {'RIPETIZIONE': r}
        t_tot = time.perf_counter()
        for zona, fn in (('bronze', lp.build_bronze_catalog), ('silver', lp.build_silver), ('gold', lp.build_gold)):
            t0 = time.perf_counter()
            fn()
            lp._flush_log()
            riga[f"SECONDI_{zona.upper()}"] = round(time.perf_counter() - t0, 1)
            print(f"ripetizione {r}, {zona}: {riga[f'SECONDI_{zona.upper()}']} s")
        riga['SECONDI_TOTALE'] = round(time.perf_counter() - t_tot, 1)
        tempi.append(riga)
        print(f"ripetizione {r}: totale {riga['SECONDI_TOTALE']} s")

    zone, tabelle = dimensioni(temporanei[-1])
    zone_vero, tabelle_vero = dimensioni(os.path.join(HOME, 'lake'))
    sqlite = {}
    for nome in ('DB.sql', 'DB_ts.sql'):
        for d in (os.path.join(HOME, 'dashboard', 'db'), os.path.join(HOME, 'dashboard', 'db', 'old')):
            p = os.path.join(d, nome)
            if os.path.exists(p):
                sqlite[nome] = os.path.getsize(p)
                break
    t = pd.DataFrame(tempi)
    b_lake = int(zone['BYTE'].sum())
    b_sqlite = sum(sqlite.values()) if len(sqlite) == 2 else None
    sintesi = pd.DataFrame([
        {'MISURA': 'Load sul lake, tempo totale (s), mediana delle ripetizioni', 'VALORE': t['SECONDI_TOTALE'].median()},
        {'MISURA': '  di cui bronze (catalogo + SHA-256 dei grezzi) (s)', 'VALORE': t['SECONDI_BRONZE'].median()},
        {'MISURA': '  di cui silver (s)', 'VALORE': t['SECONDI_SILVER'].median()},
        {'MISURA': '  di cui gold (s)', 'VALORE': t['SECONDI_GOLD'].median()},
        {'MISURA': 'Lake nuovo (una versione): byte totali', 'VALORE': b_lake},
        {'MISURA': '  silver + gold (confrontabile con DB.sql + DB_ts.sql): byte',
         'VALORE': int(zone.loc[zone.ZONA.isin(['silver', 'gold']), 'BYTE'].sum())},
        {'MISURA': 'DB.sql + DB_ts.sql: byte', 'VALORE': b_sqlite},
        {'MISURA': 'Rapporto (silver + gold) / SQLite',
         'VALORE': (round(zone.loc[zone.ZONA.isin(['silver', 'gold']), 'BYTE'].sum() / b_sqlite, 4)
                    if b_sqlite else None)},
        {'MISURA': 'Lake vero (MEDITA/lake/): byte totali', 'VALORE': int(zone_vero['BYTE'].sum())},
        {'MISURA': 'Lake vero: byte dell\'ultima versione', 'VALORE': int(zone_vero['BYTE_ULTIMA_VERSIONE'].sum())},
    ])
    try:
        import psutil
        macchina['RAM_LIBERA_GB_FINE'] = round(psutil.virtual_memory().available / 1e9, 1)
    except ImportError:
        pass

    os.makedirs(os.path.join(HOME, 'experiments', 'A_lake', 'out'), exist_ok=True)
    out = os.path.join(HOME, 'experiments', 'A_lake', 'out', f"misura_lake_{stamp}.xlsx")
    with pd.ExcelWriter(out) as xw:
        sintesi.to_excel(xw, sheet_name='sintesi', index=False)
        t.to_excel(xw, sheet_name='tempi', index=False)
        zone.assign(LAKE='nuovo').to_excel(xw, sheet_name='footprint_zone', index=False)
        zone_vero.assign(LAKE='vero').to_excel(xw, sheet_name='footprint_zone', index=False, startrow=len(zone) + 2)
        pd.concat([tabelle.assign(LAKE='nuovo'), tabelle_vero.assign(LAKE='vero')]).to_excel(
            xw, sheet_name='footprint_tabelle', index=False)
        pd.DataFrame([macchina]).T.reset_index().rename(columns={'index': 'VOCE', 0: 'VALORE'}).to_excel(
            xw, sheet_name='macchina', index=False)
    print(sintesi.to_string(index=False))

    cest = os.path.join(HOME, '_cestinare')
    os.makedirs(cest, exist_ok=True)
    for root in temporanei:
        if os.path.isdir(root):
            shutil.move(root, os.path.join(cest, os.path.basename(root)))
            print(f"{os.path.basename(root)} -> _cestinare/")
    print(f"Output: {out}")


if __name__ == '__main__':
    main()
