# -*- coding: utf-8 -*-
"""
Created on Sat Jul  1 11:09:33 2023

@author: paolap
"""

from unidecode import unidecode
import re
import pandas as pd
import numpy as np
from fuzzywuzzy import fuzz  # PATCH_FUZZY_CANONICAL
from scripts.modules.utils import fuzzy_log  # PATCH_FUZZY_LOG

FUZZY_THRESHOLD = 90  # PATCH_SOGLIA90: rinomina se fuzz.ratio >= soglia (come nel paper)

class DataFrameCleaner:
    def __init__(self, df, log, col_MAP):
        self.df = df
        self.log = log
        self.col_MAP = col_MAP
        
    def find_name_out_convention(self, col): 
         for index, row in self.col_MAP.iterrows():
             # Check if 'old' matches either part of 'name_in'
             old_names = row['name_in'].split('|')
             if col in old_names:
                 return row['name_out']
         return None
        
    def format_number(self, value):
        
        _pattern = r"""(?x)       # enable verbose mode (which ignores whitespace and comments)
                    ^                     # start of the input
                    [^\d+-\.]*            # prefixed junk
                    (?P<number>           # capturing group for the whole number
                        (?P<sign>[+-])?       # sign group (optional)
                        (?P<integer_part>         # capturing group for the integer part
                            \d{1,3}               # leading digits in an int with a thousands separator
                            (?P<sep>              # capturing group for the thousands separator
                                [ ,.]                 # the allowed separator characters
                            )
                            \d{3}                 # exactly three digits after the separator
                            (?:                   # non-capturing group
                                (?P=sep)              # the same separator again (a backreference)
                                \d{3}                 # exactly three more digits
                            )*                    # repeated 0 or more times
                        |                     # or
                            \d+                   # simple integer (just digits with no separator)
                        )?                    # integer part is optional, to allow numbers like ".5"
                        (?P<decimal_part>     # capturing group for the decimal part of the number
                            (?P<point>            # capturing group for the decimal point
                                (?(sep)               # conditional pattern, only tested if sep matched
                                    (?!                   # a negative lookahead
                                        (?P=sep)              # backreference to the separator
                                    )
                                )
                                [.,]                  # the accepted decimal point characters
                            )
                            \d+                   # one or more digits after the decimal point
                        )?                    # the whole decimal part is optional
                    )
                    [^\d]*                # suffixed junk
                    $                     # end of the input
                """
        
        if pd.isnull(value):
            return value
        else:
            value = str(value)
        
        # check if the number is preceded by a leading zero (010)
        if re.match(r'^0\d+$', value):
            return value
        
        # # check if the value is an integer without any number format (2020)
        # if re.match(r'^\d+$', value):
        #     return value            
        
        match = re.match(_pattern, value)
        
        # failed to match # consider raising an exception instead
        if match is None or not (match.group("integer_part") or  match.group("decimal_part")):
            self.log.append(f"{value} value not properly formatted!")
            return value                      
        #  get all of the number, without the junk
        value = match.group("number")      
        sep = match.group("sep")
        if sep: # remove thousands separators
            value = value.replace(sep, "")     
            
        if match.group("decimal_part"):
            # original part
            point = match.group("point")
            if point != ".":
                # regularize the decimal point
                value = value.replace(point, ".")  
            # new part
            if float(value) % 1 == 0:
                return int(float(value))
            else:
                return float(value)
            
       
        # # check if the decimal part is zero and round it to an integer (2020.0)
        # try:
        #     value = float(value)
        #     if value % 1 == 0:
        #         return f'{int(value)}'
        #     else:
        #         return f'{value:,.2f}'
        # except ValueError:
        #     return value
        
        return int(value)
    
    def badjoin_fixer(self):
        # Identifichiamo le coppie di colonne _x e _y
        x_columns = [col for col in self.df.columns if col.endswith('_X')]
        
        # Liste per le colonne da rimuovere e da rinominare
        to_remove = []
        to_rename = {}
        
        for x_col in x_columns:
            y_col = x_col[:-2] + '_Y'
            base_col = x_col[:-2]  # Colonna senza suffisso _x o _y
            
            # Controlliamo se la colonna _y corrispondente esiste e se hanno lo stesso contenuto
            if y_col in self.df.columns and self.df[x_col].equals(self.df[y_col]):
                self.log.append(f"found wrong join {x_col}, {y_col}")
                
                # Se esiste anche la colonna originale senza suffisso, dobbiamo rimuovere sia _x che _y
                if base_col in self.df.columns:
                    self.log.append(f"also found base column {base_col}, removing both {x_col} and {y_col}")
                    to_remove.append(x_col)
                    to_remove.append(y_col)
                else:
                    to_remove.append(y_col)
                    to_rename[x_col] = base_col

        # Se non sono state trovate coppie di colonne uguali, restituiamo il DataFrame originale e il self.log
        if not to_remove and not to_rename:
            return self.df, self.log
        
        # Altrimenti, procediamo con la rimozione e la rinominazione
        self.df.drop(columns=to_remove, inplace=True)
        self.df.rename(columns=to_rename, inplace=True)
        
        return self.df, self.log

    def input_cleaner(self):
        """ STAGE 1: FIND THE REAL COLUMNS NAMES """
        # remove empty rows, bad indexing
        self.df = self.df.dropna(how='all', axis=0)      
        self.df = self.df.reset_index(drop=True)
        # remove empty bad columns
        self.df = self.df.dropna(how='all', axis=1)
        # clean unwanted columns or first bad rows in csv (titles, ecc)
        row_del = 0
        while re.search('Unnamed', str(self.df.columns.values)) or re.search( 'nan', str(self.df.columns.values)):
            row_del +=1     
            self.df.columns = self.df.loc[0]
            self.df.drop( 0, axis=0,inplace=True)
            self.df = self.df.reset_index(drop=True)
            self.log.append(f"err_skip_row_{row_del}")
        
        """ STAGE 2: PARSE THE COLUMN NAMES """
        # trim leading and trailing spaces
        self.df.columns = [unidecode(str(col)).strip() for col in self.df.columns]
        # remove accents from column names
        self.df.columns = [unidecode(str(col)) for col in self.df.columns]
        # remove all non-word, non-numeric characters except underscores from a string
        self.df.columns = [re.sub(r'[^\w\d_\s]', '', x) for x in self.df.columns]
        # remove double quotes from all column values
        self.df.replace({r'"': ''}, regex=True, inplace=True)
        # remove double whitespaces from all column values
        self.df = self.df.map(lambda x: " ".join(x.split()) if isinstance(x, str) else x)
        # upper case all columns and substitute whitespaces between words with underscore
        self.df.columns = [c.upper().replace(' ', '_') for c in self.df.columns]
        # remove /n from column names
        self.df.columns = [col.replace('\n', '_') for col in self.df.columns]
        # remove double underscore, in case it exists because of double whitepaces
        self.df.columns = [col.replace('__', '_') for col in self.df.columns]   
        
        """ STAGE 3: PARSE DATA """         
        # avoid pipe inside the table, since it is the delimiter!
        self.df = self.df.replace({r'\|': ','}, regex=True)
        # drop subtotals left by PA Ministero della Salute (li mortacci vostra)
        wrong_rows = self.df[self.df.apply(lambda row: any(re.search(r'Somma:|TOTALE', str(value)) for value in row.values), axis=1)].index
        # wrong_rows = self.df[self.df.apply(lambda row: 'Somma:|TOTALE' in row.values, axis=1)].index
        self.df = self.df.drop(wrong_rows)
        # drop rows left by PA here all values are either 0 or NaN 
        wrong_rows_bool = self.df.apply(lambda row: all(x in ['0', '', np.nan,'nan', 'NaN'] for x in row), axis=1)
        wrong_rows = wrong_rows_bool[wrong_rows_bool].index
        self.df = self.df.drop(wrong_rows)
        
        """ STAGE 4: HARMONIZE COLUMN NAMES"""                      
        # first, remove the bad joins column names (performed by ISTAT)
        self.df, self.log = self.badjoin_fixer()
        # harmonize column names
        # PATCH_FUZZY_CANONICAL: dizionario esatto, poi fuzzy sui nomi canonici (name_out)
        canon = list(dict.fromkeys(self.col_MAP['name_out']))
        for old in list(self.df.columns):
            new = self.find_name_out_convention(col= old.upper())
            if not pd.isnull(new) and old != new:
                self.df.rename(columns={old: new}, inplace=True)
                self.log.append( f'harmonized column: {old} replaced w {new }')
                fuzzy_log.record('dictionary', old, new, None, 'renamed')  # PATCH_FUZZY_LOG
            elif pd.isnull(new) and old not in canon:
                best, score = max(((c, fuzz.ratio(old, c)) for c in canon), key=lambda t: t[1])
                # PATCH_FUZZY_PAPER: tolta la regola dei suffissi (non e' nel paper)
                if score >= FUZZY_THRESHOLD and best not in self.df.columns:  # PATCH_SOGLIA90
                    self.df.rename(columns={old: best}, inplace=True)
                    self.log.append(f'fuzzy column: {old} replaced w {best} (ratio {score})')
                    fuzzy_log.record('canonical', old, best, score, 'renamed', examples=fuzzy_log.examples(self.df, best))  # PATCH_FUZZY_LOG
                else:
                    why = ', target already in table' if score >= FUZZY_THRESHOLD else ''  # PATCH_SOGLIA90
                    self.log.append(f'fuzzy check: {old} ~ {best} (ratio {score}) not replaced{why}')
                    fuzzy_log.record('canonical', old, best, score, 'not_renamed' + why.replace(', ', '_').replace(' ', '_'), examples=fuzzy_log.examples(self.df, old))  # PATCH_FUZZY_LOG
            else:
                fuzzy_log.record('canonical_name', old, new if not pd.isnull(new) else old, None, 'unchanged')  # PATCH_FUZZY_LOG
            # elif old in self.df.select_dtypes(include=['float','int']).columns:
            #     self.log.append(f"{old} is new, run columns_census")
            
        """ STAGE 4: HARMONIZE DATA"""                           
        # format the numbers in the desired UK format
        numeric_map = self.col_MAP.loc[self.col_MAP['dtype'] == 'numeric','name_out']
        numeric_cols = [x for x in self.df.columns if x in numeric_map.values]
        self.df[numeric_cols] = self.df[numeric_cols].map(lambda value: self.format_number(value) )
        for col in numeric_cols:
            self.df[col] = pd.to_numeric(self.df[col], errors='coerce')
        # manage exceptions  that are ad-hoc
        try:
            if 'CODICE_REGIONE' in self.df.columns:
                self.df['CODICE_REGIONE'] = self.df['CODICE_REGIONE'].astype(float).astype(int).astype(str).str.zfill(3)
        except ValueError:
            pass # è solo per MINIS, codice regione
        
        if 'CODICE_ASL' in self.df.columns:
            # PATCH_CODICE_ASL: solo i valori numerici vengono portati a 3 cifre, gli altri restano invariati
            _asl = self.df['CODICE_ASL']
            _num = pd.to_numeric(_asl, errors='coerce')
            _ok = _num.notna()
            _out = _asl.astype(object)
            _out[_ok] = _num[_ok].astype('int64').astype(str).str.zfill(3)
            self.df['CODICE_ASL'] = _out
            if (~_ok).any():
                self.log.append(f'CODICE_ASL: {int((~_ok).sum())} valori non numerici lasciati invariati')
            
        if 'CAP' in self.df.columns:
            self.df['CAP'] = self.df['CAP'].astype(str).str.zfill(5)
         
        # strip or trim all strings in a dataframe
        self.df = self.df.map(lambda x: str(x).strip() if isinstance(x, str) or isinstance(x, object) else x)
        
        return self.df, self.log
        
    