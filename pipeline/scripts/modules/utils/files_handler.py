# -*- coding: utf-8 -*-
"""
Created on Thu Jul 20 18:25:15 2023

parameters:
    col_MAP     = dataframe with old label and new label mapping
    parsing_log = list. To keep logging
    num         = scalar
    df_prev     = dataframe
    df_next     = dataframe (next)
    dfs_temp    = list of dataframes. Can be empty
    
@author: paolap
"""

from fuzzywuzzy import fuzz
from scripts.modules.utils import fuzzy_log  # PATCH_FUZZY_LOG
import pandas as pd

class FilesHandler:
    def __init__(self, col_MAP, parsing_log, dfs_temp, output_files):
        self.col_MAP = col_MAP
        self.parsing_log = parsing_log
        self.dfs_temp = dfs_temp
        self.output_files = output_files
        
    def find_name_out_convention(self, col): 
          for index, row in self.col_MAP.iterrows():
              # Check if 'old' matches either part of 'name_in'
              old_names = row['name_in'].split('|')
              if col in old_names:
                  return row['name_out']
          return None
        
    def fuzzy_labeler(self, num, df_prev, df_next):
        
        # check if the column names are identical in both DataFrames
        if df_next.columns.tolist() != df_prev.columns.tolist():       
            """ TEMP, THIS IS GOING TO GIVE BIG BIG DATA """
            # step 1: Find non-matching column names
            diff_cols = set(df_next.columns) - set(df_prev.columns)
            
            # step 2 and 3: Find most similar column name and rename if
            # similarity ratio is above 90%
            for old in diff_cols:
             
                for new in df_prev.columns:
                    ratio = fuzz.ratio(new, old)
                    _dec = 'below_threshold'  # PATCH_FUZZY_LOG
                        
                    if ratio >= 90:  # PATCH_SOGLIA90: come nel paper (Similarity >= 90)
                        _dec = 'above_threshold_in_dictionary'  # PATCH_FUZZY_PAPER
                        
                        try:
                            new_col = self.find_name_out_convention(col= old.upper())
                            if pd.isnull(new_col) and new in df_next.columns:  # PATCH_COLLISIONE: colonna gia' presente nel file
                                _dec = 'target_already_in_table'  # PATCH_COLLISIONE
                            elif pd.isnull(new_col):  # PATCH_FUZZY_PAPER: il fuzzy interviene se il nome NON e' nel dizionario
                                df_next.rename(columns={old: new}, inplace=True)
                                self.parsing_log.append( f'Mismatch column: f{old} replaced w {new}')
                                _dec = 'renamed'  # PATCH_FUZZY_LOG
                        except IndexError:
                                self.parsing_log.append(f"{old} is new, run columns_census")
                    fuzzy_log.record('files', old, new, ratio, _dec, num=num)  # PATCH_FUZZY_LOG
                                                     
        else:
            mess_log = 'no mismatch between dataframe columns'
            self.parsing_log.append(mess_log)
            fuzzy_log.record('files', '', '', None, 'identical_columns', num=num)  # PATCH_FUZZY_LOG
                        
        # then store it
        if num == 1:
            self.dfs_temp.append(df_prev)
            self.dfs_temp.append(df_next)
        else:
            self.dfs_temp.append(df_next)

        return self.dfs_temp, self.parsing_log
    
    def harmonize_multisheetsfiles_dfs(self, dfs_list):
        
        # Flatten the list to extract DataFrames
        flat_dfs_temp = [df[0] for df in dfs_list if isinstance(df, list) and len(df) == 1]

        # Group the DataFrames based on their columns
        grouped_dfs = {}
        dfs = []
        
        for df in flat_dfs_temp:
            cols = tuple(sorted(df.columns))
            grouped_dfs.setdefault(cols, []).append(df)

        for group_key, group_dfs in grouped_dfs.items():
            temp_dfs = []  # temp list to store processed DataFrames for the current group
                    
            # Iterate over each DataFrame in the current group
            for df in group_dfs:
                # Harmonize column names based on the mapping
                for col in df.columns:
                        new_col = self.find_name_out_convention(col= col.upper())
                        if not pd.isnull(new_col) and col != new_col:
                            df.rename(columns={col: new_col}, inplace=True)
                            self.log.append( f'Harmonized column: {col} replaced w {new_col}')
                        elif col in df.select_dtypes(include=['float','int']).columns:
                                self.log.append(f"{col} is new, run columns_census")
                
                temp_dfs.append(df)
        
            # Merge the processed DataFrames in the current group into a single DataFrame
            merged_df = pd.concat(temp_dfs, axis=0)
            dfs.append(merged_df)
            
        return dfs
    
    def harmonize_dataframes(self):
        # harmonize the columns basd on the feature mapping column reduction
        
        if len(self.dfs_temp) > 1: 
            
            # only if I have multiple tables that refers to the same source
            if len(set( self.output_files)) == 1:
                for tt in range(0,len(self.dfs_temp)):
                    
                    try:
                        df_merged = pd.DataFrame(self.dfs_temp[tt])
                    except ValueError: # for the case multi_sheets 
                        df_merged = pd.concat(self.dfs_temp[tt],axis=0)
                    
                    df_merged = df_merged.reset_index(drop=True)
                    
                    # Harmonize column names based on the mapping
                    for col in df_merged.columns:
                            new_col = self.find_name_out_convention(col= col.upper())
                            if not pd.isnull(new_col) and col != new_col:
                                df_merged.rename(columns={col: new_col}, inplace=True)
                                self.log.append( f'Harmonized column: {col} replaced w {new_col}')
                            elif col in df_merged.select_dtypes(include=['float','int']).columns:
                                    self.log.append(f"{col} is new, run columns_census")
                              
                    self.dfs_temp[tt] = df_merged   
                    
                df = pd.concat(self.dfs_temp, axis=0)
                
                return df
                
        else:
            
            try:
                self.dfs_temp = pd.DataFrame(self.dfs_temp[0])
            except ValueError: # for the case multi_sheets 
                self.dfs_temp = pd.concat(self.dfs_temp[0],axis=0)
            
            self.dfs_temp = self.dfs_temp.reset_index(drop=True)
            
            for col in self.dfs_temp.columns:
                    new_col = self.find_name_out_convention(col= col.upper())
                    if not pd.isnull(new_col) and col != new_col:
                        self.dfs_temp.rename(columns={col: new_col}, inplace=True)
                        self.log.append( f'Harmonized column: {col} replaced w {new_col}')
                    elif col in  self.dfs_temp.select_dtypes(include=['float','int']).columns:
                            self.log.append(f"{col} is new, run columns_census")
                    
            df = self.dfs_temp
            
            return df