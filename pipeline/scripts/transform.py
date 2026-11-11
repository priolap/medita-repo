# -*- coding: utf-8 -*-
"""
Created on Tue Jul 25 11:04:45 2023

@author: paolap
"""

import importlib

def transform_process( homepath=None, type_source=None, source=None,
                          ni=False, today=None, log=None):
    
    log.info('STARTING THE SOURCE: ' + source)
    
    # Loop-specific objects
    module_name = f'{type_source}_miner'
    module_path = f"{homepath}scripts/modules/{type_source}_miner.py"
    
    # Import string-specific customized function
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    transform_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(transform_mod)
    
    # apply text processing
    # REPO_NEWS_261111: ramo delle fonti testuali escluso dalla repository pubblica (copyright)
    if type_source == 'data':         
        tables_builder = transform_mod.DataMiner(homepath, ni, log, today, source)
        tables_builder.data_miner()
    
    