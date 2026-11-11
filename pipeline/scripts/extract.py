# -*- coding: utf-8 -*-
"""
Created on Tue Jul 25 11:04:45 2023

@author: paolap
"""

import pandas as pd
import importlib

def extract_process( homepath=None, type_source = None, source=None, new_info=None,
                    today=None, log=None):

    if type_source == 'data':
        # from scripts.modules.utils import json_handler as jh
        # Loop-specific objects
        module_name = f'{type_source}_scraper_{source}'
    else:
        # Loop-generic routines
        module_name = f'{type_source}_scraper'
    
    module_path = f"{homepath}scripts/modules/{module_name}.py"

    # Import string-specific customized function
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    extract_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(extract_mod)
    
    log.info('STARTING THE SOURCE: ' + source)

    # REPO_NEWS_261111: ramo delle fonti testuali escluso dalla repository pubblica (copyright)
    if type_source == 'data':
        file_in = f"{homepath}config/info_{source}.json"
        
        extract_mod.data_scraper(homepath=homepath, file_in=file_in, today=today, 
                                 UPDATE_ANAG=new_info,  log=log)
