import json
import pandas as pd
from scripts.modules.utils import superkey_finder
from fuzzywuzzy import process
from multiprocessing import Pool, cpu_count
import numpy as np

class RegionHarmonizer:
    def __init__(self, file_path, log, s):
        self.mapping_dict = self.load_mapping_dict(file_path)
        self.log = log
        self.standard_regions = [data['REGIONE'] for data in self.mapping_dict.values()]
        self.s = s
    
    @staticmethod
    def parallelize_dataframe(df, func, num_partitions):
        # Split DataFrame into partitions
        df_split = np.array_split(df, num_partitions)
        pool = Pool(num_partitions)
        # Apply function to each partition in parallel
        df = pd.concat(pool.map(func, df_split))
        pool.close()
        pool.join()
        return df

    def load_mapping_dict(self, file_path):
        with open(file_path, 'r', encoding='utf-8') as file:
            mapping_dict = json.load(file)
        return mapping_dict
        
    def map_nuts_to_region(self, keycode, target):
        if target == 'regione':
            data = self.mapping_dict.get(keycode)
            if data:
                return data.get('REGIONE')
            else:
                for nuts2, data in self.mapping_dict.items():
                    if data.get('ASL_CODE') == keycode:
                        return data.get('REGIONE')
            return None
        elif target == 'codice':
            # For the 'codice' target, map ASL_CODE to NUTS code
            for nuts2, data in self.mapping_dict.items():
                if data.get('REGIONE') == keycode:
                    return data.get('NUTS2')
            return None
        
    def generate_unita_admin(self, df):
         # Step 4: just reorder UNITA_ADMIN next to REGIONE
        df['UNITA_ADMIN'] = df['REGIONE']  # Copy fully populated REGIONE to UNITA_ADMIN
        cols = df.columns.tolist()
        regione_index = cols.index('REGIONE')
        cols.insert(regione_index + 1, cols.pop(cols.index('UNITA_ADMIN')))
        df = df[cols]
        self.log.debug("Generated UNITA_ADMIN column with original or mapped region names.")
        
        return df
    
    def harmonize_regione_codes(self, df):
        if "CODICE_REGIONE" in df.columns:
            df['CODICE_REGIONE'] = df['REGIONE'].apply(lambda x: self.map_nuts_to_region(x, 'codice'))
            # drop any others (centro, Italia)
            df = df.dropna(subset=['CODICE_REGIONE']).reset_index(drop=True)
            self.log.debug("Region codes harmonized according to NUTS2-2024 standards.")
        return df
    
    def harmonize_region_name(self, region):
       # Use self.standard_regions for fuzzy matching
       if region.upper() in ['PROVINCIA AUTONOMA BOLZANO / BOZEN']:
           return 'PROV. AUTON. BOLZANO'
       if region.upper() in ['PROVINCIA AUTONOMA TRENTO']:
           return 'PROV. AUTON. TRENTO'
       best_match = process.extractOne(region.upper(), self.standard_regions, score_cutoff=88)
       return best_match[0] if best_match else region.upper()
   
    def harmonize_regione_names_parallel(self, df):
        # Apply harmonize_region_name function to REGIONE column in parallel
        # PATCH_REGIONI_VELOCE: una chiamata per valore distinto, poi map (stesso risultato di apply riga per riga)
        _lut = {v: self.harmonize_region_name(v) for v in df['REGIONE'].unique()}
        df['REGIONE'] = df['REGIONE'].map(_lut)
        return df
    
    def harmonize_regione_names(self, df):
                    
        # PATCH_FIX_TRANSFORM: in serie (Pool su Windows richiede il blocco __main__ in MASTER.py)
        df = self.harmonize_regione_names_parallel(df)
        self.log.debug("Region names harmonized in REGIONE column.")
        return df
    
    def fill_regione_attributes(self,df):
        # PATCH_CODICE_MINISTERIALE: se il codice regione e' ministeriale (ASL_CODE della mappa),
        # REGIONE si prende dal codice e non dal nome (nomi troncati nei file AIFA, es. 'PA BOLZA')
        if 'CODICE_REGIONE' in df.columns:
            _min2reg = {str(v.get('ASL_CODE')): v.get('REGIONE') for v in self.mapping_dict.values() if v.get('ASL_CODE')}
            _cod = df['CODICE_REGIONE'].astype(str).str.strip()
            _cod = _cod.where(~_cod.str.fullmatch(r'\d{1,3}'), _cod.str.zfill(3))
            _by_code = _cod.map(_min2reg)
            if 'REGIONE' in df.columns:  # PATCH_AGGREGATI: totale nazionale con il codice di una regione
                _agg = df['REGIONE'].astype(str).str.strip().str.upper().str.fullmatch(
                    r'(TOTALE )?ITALIA|ITALY|TOTALE NAZIONALE')
                if (_agg & _by_code.notna()).any():
                    self.log.debug(f"Righe di totale nazionale non abbinate dal codice: {int((_agg & _by_code.notna()).sum())}")
                _by_code = _by_code.where(~_agg)
            if _by_code.notna().any():
                if 'REGIONE' in df.columns:
                    df['REGIONE'] = _by_code.fillna(df['REGIONE'])
                else:
                    df['REGIONE'] = _by_code
                self.log.debug(f"REGIONE da codice ministeriale per {int(_by_code.notna().sum())} righe")
        # PATCH_CODICE_ISTAT: codici territoriali ISTAT (ITTER107). Le regioni (NUTS vecchi e nuovi) si
        # abbinano dal codice; Italia, ripartizioni e province si scartano (prima le province finivano
        # nella regione sbagliata per somiglianza del nome, es. Roma -> EMILIA-ROMAGNA)
        if 'CODICE_REGIONE' in df.columns:
            _c = df['CODICE_REGIONE'].astype(str).str.strip()
            _is_it = _c.str.fullmatch(r'IT[A-Z0-9]{0,3}')
            if _is_it.any():
                _old = {'ITD1': 'ITH1', 'ITD2': 'ITH2', 'ITD3': 'ITH3', 'ITD4': 'ITH4', 'ITD5': 'ITH5',
                        'ITDA': 'ITH0', 'ITE1': 'ITI1', 'ITE2': 'ITI2', 'ITE3': 'ITI3', 'ITE4': 'ITI4'}
                _key = _c.map(lambda k: _old.get(k, k))
                # PATCH_ISTAT_PA: provincia autonoma con il solo codice provinciale (es. DCIS_SUICIDI)
                _pres = set(_key.unique())
                _pa = {'ITD10': 'ITH1', 'ITH10': 'ITH1', 'ITD20': 'ITH2', 'ITH20': 'ITH2'}
                _fb = {k: v for k, v in _pa.items() if k in _pres and v not in _pres}
                if _fb:
                    _key = _key.map(lambda k: _fb.get(k, k))
                    self.log.debug(f"Province autonome dal codice provinciale: {_fb}")
                _reg = _key.map(lambda k: self.mapping_dict.get(k, {}).get('REGIONE'))
                _drop = _is_it & _reg.isna()
                if _drop.any():
                    self.log.debug(f"Scartate {int(_drop.sum())} righe con codice ISTAT non regionale: "
                                   f"{sorted(_c[_drop].unique().tolist())[:20]}")
                    df = df.loc[~_drop].copy()
                    _reg = _reg.loc[~_drop]
                    _is_it = _is_it.loc[~_drop]
                if 'REGIONE' in df.columns:
                    df.loc[_is_it, 'REGIONE'] = _reg[_is_it]
                else:
                    df['REGIONE'] = _reg
                self.log.debug(f"REGIONE da codice ISTAT per {int(_is_it.sum())} righe")
        # Step 1: Check if 'REGIONE' is present
        if 'REGIONE' in df.columns:
            # Step 2: Fill any missing values in REGIONE based on CODICE_REGIONE
            if any(df['REGIONE'].isna()):
                self.log.debug("Filling REGIONE missing values based on CODICE_REGIONE.")
                df['REGIONE'] = df['REGIONE'].fillna(df['CODICE_REGIONE'].apply(lambda x: self.map_nuts_to_region(x, 'regione')))
         # Step 3: If 'REGIONE' is missing, create it based on CODICE_REGIONE without substitutions
        else:
             self.log.debug('REGIONE column missing; creating and filling based on CODICE_REGIONE.')
             df['REGIONE'] = df['CODICE_REGIONE'].apply(lambda x: self.map_nuts_to_region(x, 'regione'))
                 
        return df
    
    def harmonize_trentino_attr(self, df ):
        "functions that maps REGIONE col to TRENTINO when ADMIN is bolzano and trento"
        
        df.loc[df['REGIONE'].isin(['PROV. AUTON. BOLZANO', 'PROV. AUTON. TRENTO']), 'REGIONE'] = 'TRENTINO-ALTO ADIGE'
        self.log.debug("REGIONE col harmonized to regions convention names for Trentino-Alto Adige")
        
        return df
    
    def aggregate_trentino_data(self, df, numeric_cols, conversions=None):
        """PATCH_TRENTINO_SUPERKEY: aggiunge le righe regionali del Trentino-Alto Adige (ITH0) calcolate da
        Bolzano (ITH1) e Trento (ITH2); le righe delle due province restano nella tabella.
          1. superkey (chiave minimale, superkey_finder.find_super_key) sulle righe ITH1/ITH2, colonne descrittive,
             con il territorio ancora distinto; colonne territoriali prima e anagrafiche per ultime, cosi' a parita'
             di grandezza la chiave usa il territorio invece di un identificativo di ente
          2. grana dell'aggregazione = superkey senza attributi territoriali e anagrafici, piu' gli attributi
             temporali presenti (ANNO, SEMESTRE, TRIMESTRE, MESE: un ente presente in un solo anno renderebbe
             l'anno superfluo nella chiave, e le somme mescolerebbero anni diversi)
          3. una riga ITH0 per gruppo: misure sommate o mediate secondo 'conversion' (cols_attributes.json);
             descrittive costanti nel gruppo tenute, le altre = 'MERGED'
        Non aggrega se la tabella ha gia' righe ITH0 (dato regionale pubblicato dalla fonte)."""
        TERR = ['CODICE_REGIONE', 'REGIONE', 'UNITA_ADMIN']
        TIME = ['ANNO', 'SEMESTRE', 'TRIMESTRE', 'MESE']
        REGISTRY = ['DENOMINAZIONE_AZIENDA', 'DSM', 'CODICE_ASL', 'CODICE_STRUTTURA', 'INDIRIZZO',
                    'DENOMINAZIONE_STRUTTURA', 'COMUNE', 'SIGLA_PROVINCIA', 'CODICE_TIPO_STRUTTURA', 'TIPO_STRUTTURA',
                    'DENOMINAZIONE_ASL', 'COMUNE_STRUTTURA',
                    # PATCH_TRENTINO_ANAGRAFICA: enti trovati nelle tabelle MINIS (SERD, DSM, ASL, comuni, ...)
                    'CODICE_DSM', 'DIPARTIMENTO_DI_SALUTE_MENTALE', 'CODICE_SERD', 'DENOMINAZIONE_SERD',
                    'SERD', 'DENOMINAZIONE_AZIENDA_SANITARIA', 'CODICE_AZIENDA_SANITARIA_LOCALE',
                    'INDIRIZZO_ASL', 'CAP_ASL', 'COMUNE_ASL', 'SIGLA_PROVINCIA_ASL', 'INDIRIZZO_STRUTTURA',
                    'SIGLA_PROVINCIA_STRUTTURA', 'CODICE_COMUNE', 'PARTITA_IVA', 'RAGIONE_SOCIALE',
                    'CODICE_PROVINCIA', 'PROVINCIA']
        conversions = conversions or {}
        if 'CODICE_REGIONE' not in df.columns:
            return df
        cod = df['CODICE_REGIONE'].astype(str).str.strip()
        if (cod == 'ITH0').any():
            self.log.debug("Trentino: righe ITH0 gia' presenti (dato della fonte), nessuna aggregazione")
            return df
        fil = df[cod.isin(['ITH1', 'ITH2'])].drop_duplicates()
        meas = [c for c in df.columns if c in numeric_cols]
        if fil.empty or not meas:
            return df
        desc = [c for c in df.columns if c not in meas]
        order = ([c for c in TERR if c in desc] + [c for c in desc if c not in TERR and c not in REGISTRY]
                 + [c for c in desc if c in REGISTRY])
        key = superkey_finder.find_super_key(fil[order])
        if key is None:
            self.log.debug("Trentino: nessuna superkey (righe descrittive ripetute), grana = tutte le descrittive")
            key = order
        grain = [c for c in key if c not in TERR and c not in REGISTRY]
        grain = [c for c in TIME if c in desc and c not in grain] + grain
        self.log.debug(f"Trentino superkey: {key}")
        self.log.debug(f"Trentino grana: {grain}")

        work = fil.copy()
        for c in meas:
            work[c] = pd.to_numeric(work[c].astype(str).str.strip(), errors='coerce')  # 'nan', '-' -> NaN
        how = {c: 'mean' if str(conversions.get(c, 'sum')).lower() in ('mean', 'avg') else 'sum' for c in meas}
        other = [c for c in desc if c not in grain]
        if grain:
            g = work.groupby(grain, dropna=False, sort=False)
            parts = {c: (g[c].mean() if how[c] == 'mean' else g[c].sum(min_count=1)) for c in meas}
            for c in other:
                parts[c] = g[c].agg(lambda s: s.iloc[0] if s.nunique(dropna=False) == 1 else 'MERGED')
            res = pd.DataFrame(parts).reset_index()
        else:
            row = {c: (work[c].mean() if how[c] == 'mean' else work[c].sum(min_count=1)) for c in meas}
            for c in other:
                row[c] = work[c].iloc[0] if work[c].nunique(dropna=False) == 1 else 'MERGED'
            res = pd.DataFrame([row])
        res['CODICE_REGIONE'] = 'ITH0'
        if 'REGIONE' in df.columns:
            res['REGIONE'] = 'TRENTINO-ALTO ADIGE'
        if 'UNITA_ADMIN' in df.columns:
            res['UNITA_ADMIN'] = 'TRENTINO-ALTO ADIGE'

        def _txt(v):  # stesso formato testo del resto della tabella (input_cleaner usa str())
            if pd.isna(v):
                return 'nan'
            if isinstance(v, float) and v.is_integer():
                return str(int(v))
            return str(v)
        for c in meas:
            res[c] = res[c].map(_txt)
        res = res[list(df.columns)]
        n_sum = sum(1 for c in meas if how[c] == 'sum')
        self.log.debug(f"Trentino: {len(res)} righe ITH0 da {len(fil)} righe ITH1/ITH2 "
                       f"({n_sum} misure sommate, {len(meas) - n_sum} mediate)")
        return pd.concat([df, res], ignore_index=True)


    def harmonize_regions(self, df, numeric_cols):
        df = self.fill_regione_attributes(df)       # Step 0: Fill regione field if missing
        df = self.harmonize_regione_names(df)       # Step 1: Harmonize region names
        df = self.generate_unita_admin(df)          # Step 2: Generate UNIT_ADMIN
        df = self.harmonize_regione_codes(df)       # Step 3: Harmonize region codes 
        df = self.harmonize_trentino_attr(df)      # Step 4: Harmonize REGIONE name convention 

        return df
