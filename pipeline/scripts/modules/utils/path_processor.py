# -*- coding: utf-8 -*-
"""
Created on Tue Jul 18 15:53:01 2023

@author: paolap
"""

import json, os
# others
from scripts.modules.utils import json_handler as jh

# =============================================================================
# DATA PATH PREPARATION
# =============================================================================

class PathProcessor:
    def __init__(self, homepath=None, source=None):
        self.source = source
        self.homepath = homepath
        self.col_MAP, self.DB_info, self.last_request = self.read_data()
        self.dset_path, self.out_path, self.out_master = self.configure_paths()
        self.manage_dirs([self.out_path, self.out_master])

    def read_data(self):
                   
        file_col = f"{self.homepath}config/cols_attributes.json"
        jhandler = jh.JsonHandler( file_tgt= file_col, encoding='ISO-8859-1')
        col_MAP = jhandler.json_reader()

        file_ = f"{self.homepath}config/info_{self.source}.json"
        jhandler = jh.JsonHandler( file_tgt= file_, encoding='utf-8')
        DB_info = jhandler.json_reader()
        input_dir = self.homepath + 'data/input/' + self.source
        last_request = sorted([x for x in os.listdir(input_dir)], reverse=True)[0]

        return col_MAP, DB_info, last_request
            
    def configure_paths(self):
        dset_path = f"{self.homepath}data/input/{self.source}/{self.last_request}"
        out_path = f"{self.homepath}data/output/{self.source}/{self.last_request}/"
        out_master = f"{self.homepath}data/output/{self.source}/"
        return dset_path, out_path, out_master
        
    def manage_dirs(self, dirs):
        for dir_path in dirs:
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)

    def get_files( self, path ):
        return os.listdir(path)