# -*- coding: utf-8 -*-
"""
Created on Thu Jun 22 15:39:42 2023

@author: paolap
"""

import pandas as pd
import csv
import dask.dataframe as dd
import re, os
import chardet
import logging
logging.getLogger('chardet').setLevel(logging.INFO)

class ExcelParser:
    def __init__(self, file_path):
        self.file_path = file_path
        self.delim = None
        self.encoding = None
        self.parsed_outcome = []

    def infer_delimiter(self):
        # infer the delimiter from the CSV file
        try:
            with open(self.file_path, 'r') as file:
                self.valid_seps = ['|',',',';','\t']
                first_row = file.readline()
                self.delim = csv.Sniffer().sniff(first_row, delimiters=self.valid_seps).delimiter
        except UnicodeDecodeError:
            # open the file in binary mode
            with open(self.file_path, 'rb') as file:
                # read a small sample from the file
                sample = file.read(10000)  
                # decode the sample using the detected encoding
                decoded_sample = sample.decode(self.encoding, errors='ignore')
                self.delim = csv.Sniffer().sniff(decoded_sample, delimiters=self.valid_seps).delimiter

        return self.delim
    
    def infer_encoding(self):
        with open(self.file_path, 'rb') as file:
            # Read a portion of the file
            sample = file.read(10000)  # Adjust sample size as needed
            self.encoding = chardet.detect(sample)
            self.encoding = self.encoding['encoding']
        return self.encoding 
    
    def read_on_parallel(self, quoting, large=False):      
        
        if large:
            # if file is larger than 300MB, use Dask
            try:
                df = dd.read_csv(self.file_path, delimiter=self.delim, encoding=self.encoding,
                                 assume_missing=True, dtype=object)
                df = df.compute()

            except pd.errors.ParserError:
                df = dd.read_csv(self.file_path, delimiter=self.delim, encoding=self.encoding,
                                   quoting=csv.QUOTE_MINIMAL, assume_missing=True, dtype=object)
     
        else:
            """ case atti di concessione, è un utf-8 corrotto per apostrofo """
            try:
                df = pd.read_csv(self.file_path, delimiter=self.delim, encoding=self.encoding, 
                                 engine='python', quoting=quoting, dtype=object)
            
            except pd.errors.ParserError:
                df = pd.read_csv(self.file_path, delimiter=self.delim, encoding=self.encoding, 
                                 engine='python', quoting=csv.QUOTE_MINIMAL, dtype=object)
                
        return df       
    
    def parse_csv(self):
        
        self.encoding = self.infer_encoding()                
        self.delim = self.infer_delimiter()
        
        is_large = os.path.getsize(self.file_path) / 1e9 > 0.3
        
        # force the latin encoding when cp1252 returns error
        # or somebody from PA uses old Macs, or when inference fails
        # PATCH_OBSOLESCENZA: chardet >= 6 usa nomi non previsti qui sotto (cp1258, iso8859-15, ...)
        _enc_key = str(self.encoding).lower().replace('_', '-')
        if self.encoding is not None and _enc_key in ('utf-8', 'utf-8-sig', 'utf8'):
            self.encoding = 'utf-8'
        elif self.encoding not in ['ISO-8859-1', 'MacRoman', 'Windows-1252', 'ascii', None]:
            self.parsed_outcome.append(f'real_encoding_{self.encoding}')
            self.encoding = 'ISO-8859-1'
        if self.encoding in ['MacRoman','Windows-1252','ascii',None]:
            self.parsed_outcome.append(f'real_encoding_{self.encoding}')
            self.encoding = 'ISO-8859-1' 

        # standard ones
        if self.encoding in ['utf-8']:
            df = self.read_on_parallel(quoting=csv.QUOTE_NONE, large=is_large)
            
        # this is latin-1
        if self.encoding == 'ISO-8859-1': 
            try:
                df = self.read_on_parallel(quoting=csv.QUOTE_MINIMAL, large=is_large)
                # charmap for accent, equivalent to Windows-1252
                is_illparsed = re.search(r'xe2|x88|x92', str(df.columns.values))
                if is_illparsed:
                    self.encoding = 'cp1252'
                    
                    try:
                        df = self.read_on_parallel(quoting=csv.QUOTE_MINIMAL, large=is_large)
                        self.parsed_outcome.append('is_windows-1252')
                    except UnicodeDecodeError:
                        """ last resort, this csv is such a nightmare: a mix of mac old formats """
                        self.encoding = 'ISO-8859-1'
                        df = self.read_on_parallel(quoting=csv.QUOTE_MINIMAL, large=is_large)
                        self.parsed_outcome.append('is_nightmare_mac_lastresort_latin-1')
                        
                # check parsing errors that move the first column in index
                is_err_index = type(df.index.values[0]) == str
                if is_err_index:
                    df.reset_index(inplace=True)
                    labels = df.columns[1:]
                    df = df.dropna(how='all',axis=1) # the inplace generate a nan column
                    df.columns = labels
                    self.parsed_outcome.append('err_pars_firstcolindex')
                        
            except pd.errors.ParserError:
                # err_pars_whitespace: Remove leading/trailing spaces from each field
                rows = []
                with open(self.file_path, "r", encoding=self.encoding) as file:
                    reader = csv.reader(file, delimiter=self.delim)
                    for row in reader:
                        cleaned_row = [field.strip() for field in row if not re.search(r'&#', field.strip())]
                        rows.append(cleaned_row)
                # clean the data
                df = pd.DataFrame(rows)
                col_labs = df.iloc[0]
                df = df.rename(columns=col_labs)
                df = df.iloc[1:]
                
                self.parsed_outcome.append('err_pars_whitespace')

        return df
        
    def parse_file(self, parsing_log, log):
        
        """
        Parses a given file path into a DataFrame and extracts relevant information.
        Parameters:
        file_path (str): The file path to be parsed.
        parsing_log (list): A list to append the parsing outcomes or errors
        Returns:
        tuple: A tuple containing the DataFrame, delimiter, encoding, and sheet names.
        """
    
        
        # Determine the file type and parse accordingly
        file_ext = self.file_path.split('.')[-1].lower()
        
        try:

            if file_ext == 'csv':
                # Parse CSV file
                df = self.parse_csv()
                sheet_names = []
                parsing_log.append(self.parsed_outcome)

            elif file_ext in ['xlsx', 'xls']:
                # Parse Excel file
                df = pd.read_excel(self.file_path,dtype=object)
                sheet_names = pd.ExcelFile(self.file_path).sheet_names
                self.delim = ','
                self.encoding = 'utf-8'
                
            elif file_ext == 'ods':
                df = pd.read_excel(self.file_path, engine='odf',dtype=object)
                sheet_names = pd.ExcelFile(self.file_path).sheet_names
                self.delim = ','
                self.encoding = 'utf-8'
            else:
                # Handle unsupported file formats
                raise ValueError("Undefined file format")

        except Exception as e:
                  
            parsing_log.append(f"Error processing {self.file_path}: {e}")
            log.critical(f"{self.file_path} processing error: {e}")

        return df, self.delim, self.encoding, sheet_names, parsing_log



