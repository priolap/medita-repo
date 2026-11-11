# -*- coding: utf-8 -*-
"""
Created on Thu Mar 14 13:45:20 2024

@author: paola
"""

import os, sys
import pandas as pd
import numpy as np

from scripts.modules.utils import excel_parser
from scripts.modules.utils import datatable_cleaner
from scripts.modules.utils import path_processor
from scripts.modules.utils import sheets_handler
from scripts.modules.utils import files_handler
from scripts.modules.utils import data_updater
from scripts.modules.utils import json_handler as jh
from scripts.modules.utils import nuts_region_harmonizer
from scripts.modules.utils import attributes_censor as ac
from scripts.modules.utils import fuzzy_log  # PATCH_FUZZY_LOG

# Opt-in to future behavior for replace downcasting
try:  # PATCH_OBSOLESCENZA: in pandas 3 il comportamento e' gia' predefinito
    pd.set_option('future.no_silent_downcasting', True)
except Exception:
    pass
    
# PATCH_CATALOGO: la Transform legge il catalogo dell'Extract. info_<FONTE>.json viene riscritto alla fine
# della Transform (la Load usa file_out e i VAR_CODE delle tabelle divise); riletto cosi' com'e', il giro
# successivo ripeteva le righe e numerava di nuovo i codici (TIPO1 -> TIPO11 -> TIPO111).
_TRANSFORM_COLS = ['delimiter', 'encoding', 'file_out', 'last_pars', 'outcome', 'parsing', 'sheets']


def _fogli_non_vuoti(f_path, engine):  # PATCH_FOGLI_VUOTI
    """Nomi dei fogli con almeno una cella piena (i fogli vuoti non sono tabelle)."""
    fogli = pd.read_excel(f_path, engine=engine, sheet_name=None, header=None, nrows=5)
    return [nome for nome, df in fogli.items() if not df.dropna(how='all').empty]


# PATCH_ESCLUDI: codici che la pipeline non sa trasformare, esclusi come nello snapshot di agosto 2025
_ESCLUSI_TRANSFORM = {'MINIS': ['FARM_VEND6MES_SOPS']}


def catalogo_extract(info):  # PATCH_CATALOGO
    df = info.copy()
    n_base = 0
    sfx = df['VAR_NAME'].astype(str).str.extract(r'_(\d+)$')[0]
    for i in df.index[sfx.notna()]:
        code, n = df.at[i, 'VAR_CODE'], sfx[i]
        if isinstance(code, str) and code.endswith(n) and len(code) > len(n):
            df.at[i, 'VAR_CODE'] = code[:-len(n)]
            df.at[i, 'VAR_NAME'] = str(df.at[i, 'VAR_NAME'])[:-(len(n) + 1)]
            n_base += 1
    df = df.drop(columns=[c for c in _TRANSFORM_COLS if c in df.columns])
    key = df.apply(lambda r: (str(r['FILE_NAME']).strip(), r['VAR_CODE'],
                              tuple(sorted(r['file_in'])) if isinstance(r['file_in'], list) else str(r['file_in'])),
                   axis=1)
    dup = key.duplicated()
    df = df.loc[~dup].reset_index(drop=True)
    return df, n_base, int(dup.sum())


class DataMiner:
    def __init__(self, homepath=None, new_info=None, log=None,today=None, source=None):
        self.homepath = homepath
        self.log = log
        self.today = today
        self.source = source
        self.init_objects()
        self.new_info = new_info
        
    def init_objects(self):      
        ipp = path_processor.PathProcessor(self.homepath, self.source )  
        self.col_map, self.DB_info, self.last_request = ipp.read_data()     
        self.DB_info, _nb, _nd = catalogo_extract(self.DB_info)  # PATCH_CATALOGO
        self.log.debug(f"Catalogo dell'Extract: {_nb} codici riportati alla base, {_nd} righe ripetute tolte")  # PATCH_CATALOGO
        _escl = self.DB_info['VAR_CODE'].isin(_ESCLUSI_TRANSFORM.get(self.source, []))  # PATCH_ESCLUDI
        if _escl.any():  # PATCH_ESCLUDI
            self.log.warning(f"Esclusi dalla Transform (non gestiti dalla pipeline): "
                             f"{sorted(set(self.DB_info.loc[_escl, 'VAR_CODE']))}, {int(_escl.sum())} righe del catalogo")
            self.DB_info = self.DB_info.loc[~_escl].reset_index(drop=True)
        self.dset_path, self.out_path, self.out_master = ipp.configure_paths()
        self.codregione_path = f"{self.homepath}config/codregione_map.json"
        self.cols_matrix, self.col_labels = {}, []
        self.numeric_cols = list(self.col_map.loc[self.col_map['dtype'] == 'numeric','name_out'])
        self.conversions = dict(zip(self.col_map['name_out'], self.col_map['conversion']))  # PATCH_TRENTINO_SUPERKEY
        self.OUT = {'index':[],'FILE_NAME':[],'VAR_NAME':[],'VAR_CODE':[],'file_in':[],
                    'encoding':[],'delimiter':[],'sheets':[],'outcome':[],
                    'file_out':[], 'last_pars':[], 'parsing':[]}
        
    def architecture_definition(self, var_code, files):
        
        """    
        this release handles architecture for the 4 cases. Hank can be:
        # MULTIOBJECTS_SINGLETABLE (MS): this is the case when n -> 1
        # SINGLEOBJECT_MULTITABLES (SM): this is the case when 1 -> m (not implemented)
        # SINGLEOBJECT_SINGLETABLE (SS): this is the case when 1 -> 1 
        # MULTIOBJECTS_MULTITABLES (MM): this is the case when n -> m 
        """

        # Aug 2025, bug da fixare: quando trova fogli vuoti dentro il file excel li considera... (risolto: PATCH_FOGLI_VUOTI)

        hank = []
        if len(files) > 1:
            for f_path in files:
                ext = f_path.split('.')[-1]
                if ext == 'csv':
                    hank_out = 'MULTIOBJECTS_SINGLETABLE'
                else:
                    eng = 'openpyxl' if ext == 'xlsx' else 'odf' if ext == 'ods' else 'xlrd'
                    sheets = _fogli_non_vuoti(f_path, eng)  # PATCH_FOGLI_VUOTI
                    if len(sheets) > 1:
                        hank_out = 'MULTIOBJECTS_MULTITABLES'
                    else:
                        hank_out = 'MULTIOBJECTS_SINGLETABLE'
                hank.append(hank_out)
        else:
            f_path = files[0]
            ext = f_path.split('.')[-1]
            if ext == 'csv':
                hank_out = 'SINGLEOBJECT_SINGLETABLE'
            else:
                eng = 'openpyxl' if ext == 'xlsx' else 'odf' if ext == 'ods' else 'xlrd'
                sheets = _fogli_non_vuoti(f_path, eng)  # PATCH_FOGLI_VUOTI
                hank_out = 'SINGLEOBJECT_MULTITABLES' if len(sheets) > 1 else 'SINGLEOBJECT_SINGLETABLE'
            hank.append(hank_out)
        
        hank = list(set(hank))
        
        # case when 1 csv, 1 xlsx with MM...
        if len(hank) > 1:
            if hank == ['MULTIOBJECTS_SINGLETABLE', 'MULTIOBJECTS_MULTITABLES'] \
            or hank == ['MULTIOBJECTS_MULTITABLES', 'MULTIOBJECTS_SINGLETABLE']:
                
                hank = 'MULTIOBJECTS_MULTITABLES'
            
            else:
                self.log.critical(f'Design out of this architecture: {hank} not implemented. Please check {var_code}')
                sys.exit()
        else:
            hank = hank[0]
              
        return hank
    
       
    def data_miner(self):
        
        # PATCH_OBSOLESCENZA: rimossi import pdb / pdb.set_trace()
        
        var_codes = sorted( self.DB_info['VAR_CODE'].unique())
        
        # var_code = 'FARM_VEND6MES_SOPS'  # PATCH_OBSOLESCENZA: valore di prova, sovrascritto dal ciclo

        for var_code in var_codes:

            print(var_code)
            # init objects
            self.log.debug(var_code) 
            parsing_log, dfs_temp, output_files = [], [], []

            files = [i for sub in self.DB_info.loc[self.DB_info.VAR_CODE == var_code]['file_in'].values for i in sub]
            files = [os.path.join( f"{self.dset_path}/{i}" ) for i in files]
             
            # the heart of this project 
            hank = self.architecture_definition(var_code, files)
            
            #=======================================================# 
            # STEP 1: MINE THE TABLES ACCORDING TO THE ARCHITECTURE # 
            #=======================================================# 
            
            # put a floor at 0 for files
            last_num = max(0, len(files) - 1)
            output_files.append( f"{self.out_path}{var_code}.txt")
            
            # bugfix Aug 2025, to prevent NoneType Error
            self.DB_info['file_in'] = self.DB_info['file_in'].apply(lambda x: x if isinstance(x, list) else [])


            for num, f_path in enumerate(files):
                
                print(num)

                # find the VAR_NAME for the specific file_in 
                f_in = os.path.basename(f_path)
                fuzzy_log.set_context(source=self.source, snapshot=self.last_request, var_code=var_code, file=f_in,  # PATCH_FUZZY_LOG
                                      sheet='(primo foglio via parse_file, non usato in MM)' if hank == 'MULTIOBJECTS_MULTITABLES' else '')
                var_name = self.DB_info.loc[self.DB_info['file_in'].apply(lambda x: f_in in x), 'VAR_NAME'].values[0]
                fname = self.DB_info.loc[self.DB_info['file_in'].apply(lambda x: f_in in x), 'FILE_NAME'].values[0]
                
                # parse file and generate the df
                excelparser = excel_parser.ExcelParser(f_path)
                df, delim, enc, sheet_names, parsing_log = excelparser.parse_file(parsing_log, self.log)
                dfclean = datatable_cleaner.DataFrameCleaner(df=df, log=parsing_log,col_MAP=self.col_map)
                df_temp, parsing_log = dfclean.input_cleaner()
              
                if hank == 'SINGLEOBJECT_MULTITABLES':
                    self.log.critical(f"{var_code} code not supported: {hank}. A patch is required" )
                    quit()
                
                if hank == 'SINGLEOBJECT_SINGLETABLE':
                    dfs_temp.append(df_temp)
                
                if hank == 'MULTIOBJECTS_SINGLETABLE':              
                    if num == 0:
                        # istantiate the class for manipulating multi_files belonging to the same variable
                        dfs_handler = files_handler.FilesHandler(self.col_map, parsing_log,
                                                                dfs_temp,output_files)
                    try:
                          if num == 0:
                              df_prev = df_temp
                          elif num == 1:
                              df_next = df_temp
                          else:
                              df_prev = df_next
                              df_next = df_temp
                             
                          if num > 0:
                              dfs_temp, parsing_log = dfs_handler.fuzzy_labeler( num, 
                                                        df_prev, df_next)
                    except UnboundLocalError:
                          """ handle the case when multi_files TRUE but not multi_sheets for all files
                          example : 1 file multisheet, 1 file single sheet for the same var"""
                          dfs_temp.append(df_temp)
                
                    if num == last_num:
                        dfs_temp = dfs_handler.harmonize_dataframes()
                
                # qui devo unificare il dataframe, essendo multi files single sheets 
                if hank == 'MULTIOBJECTS_MULTITABLES': 
                    
                    if num == 0:
                        # istantiate the class for manipulating multi_files belonging to the same variable
                        dfs_handler = files_handler.FilesHandler(self.col_map, parsing_log,
                                                                dfs_temp,output_files)
                    if not sheet_names:  # PATCH_MM_CSV: file CSV in una voce multi-foglio, prima veniva scartato
                        dfs_temp.append([df_temp])
                        output_files.append(f"{self.out_path}{var_code}.txt")
                        self.log.debug(f"{var_code}: {f_in} (CSV) unito alle tabelle multi-foglio")
                    else:
                        dh = sheets_handler.SheetsHandler( f_path, sheet_names, self.out_path, var_code, 
                                                        dfs_temp, output_files, parsing_log, self.col_map )
                        
                        # handle multiple sheets and merge them in time series
                        dfs_temp, output_files, parsing_log = dh.handle_multiple_sheets()
                    output_files = [x for x in output_files if x.split('/')[-1].split('.')[0] != var_code]

                    if num == last_num:
                        dfs_temp = dfs_handler.harmonize_multisheetsfiles_dfs(dfs_temp)
                       
                # manipulate log to preserve only unique alerts
                parsing_log_out = [e for e in parsing_log if isinstance(e, str) and e]
                parsing_log_out = list(set(parsing_log_out))
            
                """ eccezione caso hank {'MULTIOBJECTS_MULTITABLES', 'MULTIOBJECTS_SINGLETABLE'}
                ma solo per i files che contengono più fogli riferiti alla stessa tabella """
                if var_code in ['AASL_STAFFLEX_TIPO']:
                    output_files = [f'{self.homepath}data/output/MINIS/{self.last_request}/{var_code}.txt']
                    
                # This generate a unique list of output preserving the order
                unique_out_files = []
                for file in output_files:
                    if file not in unique_out_files:
                        unique_out_files.append(file)
               
                for ii, outf in enumerate(unique_out_files):

                    if len(unique_out_files) > 1:
                        new_output = outf.replace(os.path.basename(outf), f"{var_code}{str(ii+1)}.txt")
                        # in this case I need to dynamically generate extra var codes
                        unique_out_files[ii] = new_output
                        self.OUT['VAR_CODE'].append(f"{var_code}{str(ii+1)}")
                        self.OUT['VAR_NAME'].append(f"{var_name}_{ii+1}")
                        self.OUT['file_out'].append(f"{var_code}{str(ii+1)}.txt")       
                    else:
                        self.OUT['VAR_CODE'].append(var_code)
                        self.OUT['VAR_NAME'].append(var_name)
                        self.OUT['file_out'].append(os.path.basename(outf))

                    # collect the information
                    self.OUT['FILE_NAME'].append(fname)
                    self.OUT['file_in'].append(f_in)
                    self.OUT['delimiter'].append(delim)
                    self.OUT['encoding'].append(enc)
                    self.OUT['parsing'].append(parsing_log_out)
                    self.OUT['index'].append(0)
                    self.OUT['sheets'].append(len(sheet_names))
                    self.OUT['outcome'].append(hank)
                    self.OUT['last_pars'].append(self.last_request)
                                    
            #===========================#
            # 2: MERGE TABLES AND PATHS #
            #===========================#
            
            # se df, trasforma in lista
            if isinstance(dfs_temp, pd.DataFrame):
                dfs_temp = [dfs_temp]
                           
            # handle multi tables               
            for jj, df in enumerate(dfs_temp):
                try:
                    df = pd.DataFrame(df[0])
                except KeyError:
                    df = pd.DataFrame(df)
                    # succede solo per COST_DISPMEDI_AASL
                    wrong_add = ['level_0', 'index']
                    for wa in wrong_add:
                        if wa in df.columns:
                            df = df.drop(columns=wa)
                        
                output_file = unique_out_files[jj]
                
                #========================#
                # 3: HARMONIZATION PHASE #
                #========================#
                
                if 'CODICE_REGIONE' not in df.columns:
                    self.log.debug('No CODICE_REGIONE in table; treating as registry table.')
                else:
                    
                    # Initialize the harmonizer
                    harmonizer = nuts_region_harmonizer.RegionHarmonizer( file_path = self.codregione_path, 
                                                                         log=self.log, s = self.source)
                    
                    # Perform  harmonization (without Trentino aggregation)
                    df = harmonizer.harmonize_regions(df, numeric_cols=self.numeric_cols)
                    
                    # PATCH_TRENTINO_SUPERKEY: aggregazione del Trentino riattivata e corretta. Bolzano (ITH1) e
                    # Trento (ITH2) restano; si aggiungono le righe regionali ITH0. Stessa condizione del 2024
                    # (no elenchi ELEN, no ISTAT); la funzione non aggrega se la fonte pubblica gia' ITH0
                    if 'ELEN' not in var_code and self.source != 'ISTAT' and set(self.numeric_cols) & set(df.columns):
                        df = harmonizer.aggregate_trentino_data(df, numeric_cols=self.numeric_cols,
                                                                conversions=self.conversions)
                
                #=====================#
                # 4: EXPORTING TABLES #
                #=====================#
                
                # remove "-" that prevent columns to be considered as numericals
                df.replace("-", np.nan, inplace=True)
                # export dataframe to txt file
                df.to_csv(output_file, index=False, sep='|')
                self.col_labels.extend(df.columns)
            
        # store information on column names 
        self.cols_matrix.setdefault(var_code, []).extend(self.col_labels)
                
        # final export: a date-specific folder and the OUTPUT generic one
        self.cols_matrix = pd.DataFrame.from_dict(self.cols_matrix,orient='index')
        self.cols_matrix.columns = [f'COL_{j}' for j in range(1, len(self.cols_matrix.columns)+1)]
           
        #=====================#
        # 4: UPDATE LOGS INFO #
        #=====================#

        self.OUT = pd.DataFrame(self.OUT)
        
        # must be updated
        self.DB_info.drop( columns = ['VAR_NAME', 'VAR_CODE'], inplace=True )
        
        # Columns unique to each DataFrame
        common_cols = self.DB_info.columns.intersection(self.OUT.columns).tolist()
        dbinfo_unique_cols = self.DB_info.columns.difference(common_cols).tolist()
        out_unique_cols = self.OUT.columns.difference(common_cols).tolist()
        
        # Perform the merge keeping all relevant columns
        self.DB_info = pd.merge(
            self.DB_info[common_cols + dbinfo_unique_cols], 
            self.OUT[out_unique_cols + ['FILE_NAME']], 
            on="FILE_NAME", 
            how="left"
        )
        
        self.DB_info.reset_index(drop=True, inplace=True)
             
        # Replace any sets in the DataFrame with lists
        for column in self.DB_info.columns:
            if self.DB_info[column].apply(type).eq(set).any():
                self.DB_info[column] = self.DB_info[column].apply(lambda x: list(x) if isinstance(x, set) else x)
            
        # drop eventually duplicates: first convert to tuple
        list_columns = [col for col in self.DB_info.columns if self.DB_info[col].apply(type).eq(list).any()]
        
        for col in list_columns:
            print(col)
            self.DB_info[col] = self.DB_info[col].apply(lambda x: tuple(x) if isinstance(x, list) else x)

        # Drop duplicates
        self.DB_info = self.DB_info.drop_duplicates()
        self.DB_info = self.DB_info.reset_index(drop=True)
        
        # Convert tuples back to lists, handling NaN values
        for col in list_columns:
            self.DB_info[col] = self.DB_info[col].apply(lambda x: list(x) if isinstance(x, tuple) else x)
            
        # drop index
        self.OUT.drop(columns=['index'], inplace=True)
        self.DB_info.drop(columns=['index'], inplace=True)
        
        # Rearrange the columns to place ['VAR_NAME', 'VAR_CODE'] after 'file_in'
        columns = self.DB_info.columns.tolist()
        
        # Identify the position of 'file_in'
        file_in_index = columns.index('file_in') + 1
        
        # Remove 'VAR_NAME' and 'VAR_CODE' from their current positions
        columns.remove('VAR_NAME')
        columns.remove('VAR_CODE')
        
        # Insert 'VAR_NAME' and 'VAR_CODE' after 'file_in'
        columns[file_in_index:file_in_index] = ['VAR_NAME', 'VAR_CODE']
        
        # Reorder the DataFrame
        self.DB_info = self.DB_info[columns]

        
        # PATCH_FUZZY_LOG: log dettagliato fuzzy/dizionario, fuori da info e da data/output
        _flog = fuzzy_log.export(f"{self.homepath}logs/fuzzy/", self.source, self.last_request)
        self.log.debug(f"fuzzy log exported: {_flog}")
        print(f"fuzzy log exported: {_flog}")
        jhandler = jh.JsonHandler( file_tgt= f"{self.homepath}config/info_{self.source}.json", encoding='utf-8')
        jhandler.json_writer(data = self.DB_info)
        
        #===========================#
        # 5: OVERWRITING FINAL DATA #
        #===========================#
         
        files_new = os.listdir( self.out_path )
        files_old = os.listdir( self.out_master )
        not_overwritten_files = []
        
        for f_last in files_new:
            df_last = pd.read_csv(f"{self.out_path}{f_last}", delimiter='|', dtype=str,  # PATCH_TESTO
                                  keep_default_na=False, na_values=[''])
            df_last = pd.DataFrame(df_last)
            _n = len(df_last)  # PATCH_DUPLICATI: tuple identiche in tutte le colonne = duplicati
            df_last = df_last.drop_duplicates()  # PATCH_DUPLICATI
            if len(df_last) < _n:  # PATCH_DUPLICATI: snapshot riscritto, resta uguale alla tabella principale
                self.log.debug(f"{f_last}: tolte {_n - len(df_last)} righe identiche")
                df_last.to_csv(f"{self.out_path}{f_last}", index=False, sep='|')
            
            if f_last in files_old:
                df_master = pd.read_csv(f"{self.out_master}{f_last}", delimiter='|', dtype=str,  # PATCH_TESTO
                                        keep_default_na=False, na_values=[''])
                dbupdater = data_updater.UpdateDB( data_name=f_last, data_master = df_master,
                                                  data_last=df_last,
                                                  output_log = self.log)
                df_merged, self.log = dbupdater.db_updater()
                # export dataframe to txt file
                df_merged.to_csv(f"{self.out_master}{f_last}", index=False, sep='|')
            else:
                # export dataframe to txt file
                df_last.to_csv(f"{self.out_master}{f_last}", index=False, sep='|')
                # file was not overwritten
                not_overwritten_files.append(f_last)
        
        self.log.debug( f"Files not updated: {not_overwritten_files}" )
        self.log.debug( 'success' )
        
        #===================================#
        # 6: RUN COLUMN CENSUNS IF NEW_INFO #
        #===================================#
        
        if self.new_info and self.source == 'MINIS':
            self.log.debug( 'Running column censor, please wait' )
            self.log = ac.numbers_dtypes( home = self.homepath, log = self.log, tod= self.today )
            
        
        
                    