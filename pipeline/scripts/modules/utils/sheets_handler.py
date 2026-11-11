# -*- coding: utf-8 -*-
"""
Created on Thu Jul 20 13:14:28 2023

@author: paolap
"""

import pandas as pd
from fuzzywuzzy import fuzz
import re

from scripts.modules.utils import datatable_cleaner
from scripts.modules.utils import fuzzy_log  # PATCH_FUZZY_LOG

class SheetsHandler:
    def __init__(self, f_path, sheet_names, out_path, var_code, 
                        dfs_temp, output_files, parsing_log,col_MAP ):
        self.f_path = f_path
        self.sheet_names = sheet_names
        self.out_path = out_path
        self.var_code = var_code
        self.dfs_temp = dfs_temp
        self.output_files = output_files
        self.parsing_log = parsing_log
        self.col_MAP = col_MAP
        
    def find_name_out_convention(self, col): 
         for index, row in self.col_MAP.iterrows():
             # Check if 'old' matches either part of 'name_in'
             old_names = row['name_in'].split('|')
             if col in old_names:
                 return row['name_out']
         return None
     
    def handle_multiple_sheets(self):
        groups = self.group_similar_sheets()
        
        # read data from cluster of sheets name
        # each group cluster is a unique df
        for i, group in enumerate(groups):
         
            dfs_list, output_files_l = [], []
            output_file = self.create_output_file(group)
    
            # read all sheets belonging to a cluster at once
            dfs_chunk = pd.read_excel(self.f_path, sheet_name=group)
    
            for _sheet, df_chunk in dfs_chunk.items():  # PATCH_FUZZY_LOG
                fuzzy_log.set_sheet(_sheet)  # PATCH_FUZZY_LOG
                dfclean = datatable_cleaner.DataFrameCleaner(df = df_chunk,
                                                             log = self.parsing_log,
                                                             col_MAP= self.col_MAP)
                dfc, self.parsing_log = dfclean.input_cleaner()
                
                # dfc, self.parsing_log = tabclean.input_cleaner(df=df_chunk, 
                #                                                log=self.parsing_log, 
                #                                                col_MAP = self.col_MAP)
                dfs_list.append(dfc)
                output_files_l.append(output_file)
    
            """ questo perché hanno cambiato il nome delle colonne TRA i fogli """
            for j in range(0,len(dfs_list)):
                dfsingle = dfs_list[j]
                for col in dfsingle.columns:     
                    new = self.find_name_out_convention(col= col.upper())
                    if not pd.isnull(new) and col != new:   
                        dfsingle.rename(columns={col: new}, inplace=True)
                        self.log.append( f'Harmonized column: {col} replaced w {new }')
                    elif col in dfsingle.select_dtypes(include=['float','int']).columns:
                        self.log.append(f"{col} is new, run columns_census")
                            
                # for col in dfsingle.columns:
                #     try:
                #       new_col = self.col_MAP[self.col_MAP.col_names == col]['ref_name'].values[0]
                #       if not pd.isnull(new_col):   
                #           dfsingle.rename(columns={col: new_col}, inplace=True)        
                #     except IndexError:
                #        self.parsing_log.append(f"{col}_not_found_COLMAP")
                dfs_list[j] = dfsingle  
                      
            dfs_list = pd.concat(dfs_list, axis=0)
            # reset the index
            dfs_list = dfs_list.reset_index(drop=True)
        
            """ in case column names changes, I keep everything """
            # Concatenate the DataFrames into a single DataFrame
            self.dfs_temp.append([dfs_list])
            self.output_files.append(set(output_files_l).pop())
        
        return self.dfs_temp, self.output_files, self.parsing_log

    def group_similar_sheets(self):
        groups = []

        # here I need to check the similarity among the sheet names!
        for sheet_name in self.sheet_names:
            assigned = False
            for group in groups:
                representative = group[0]
                # Calculate similarity between sheet name and group representative
                similarity = fuzz.ratio(sheet_name, representative)
                fuzzy_log.record('sheets', sheet_name, representative, similarity, 'joined' if similarity >= 88 else 'below_threshold')  # PATCH_FUZZY_LOG
                if similarity >= 88:
                    group.append(sheet_name)
                    assigned = True
                    break
            if not assigned:
                groups.append([sheet_name])
                fuzzy_log.record('sheets', sheet_name, '', None, 'new_group')  # PATCH_FUZZY_LOG

        return groups

    def create_output_file(self, group):
        
        # if only one group, keep the original labelling
        if len(group) > 1:
            name_cluster = [x for x in set([re.sub(r'\d+', '', g) for g in group])]

            if len(name_cluster) > 1:
                # since these are cluster, names must be equal!
                self.parsing_log.append('multisheetnames_single_cluster')
                name_cluster = name_cluster[0]
            else:
                name_cluster = name_cluster.pop()

            name_cluster = name_cluster.strip().lower()
            name_cluster = name_cluster.replace('  ', ' ') .replace(' ', '_')
            if name_cluster.endswith('_'):
                name_cluster = name_cluster[:-1]

            return f"{self.out_path}{self.var_code}_{name_cluster}.txt"
        else:
            return f"{self.out_path}{self.var_code}.txt"
