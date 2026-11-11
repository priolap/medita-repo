# -*- coding: utf-8 -*-
"""
Created on Tue Jul 25 11:06:30 2023
@author: paolap

last update: 2024-09-30
last update: 2026-10-25

"""

# libraries and modules
import sys
import time
import datetime as dt
import logging

start_time = time.time()
today = dt.datetime.now().strftime("%Y%m%d")

import os  # REPO_261031
# REPO_261031: folder that contains scripts/, config/ and data/ (default: the folder of this file)
homepath = os.environ.get("MEDITA_HOME", os.path.dirname(os.path.abspath(__file__))).replace("\\", "/").rstrip("/") + "/"
json_prompt = homepath + "config/PROMPT.json"

# import modules
sys.path.append(homepath)
from scripts.modules.utils import prompt_reader
from scripts.modules.utils import logger
from scripts import extract as e
from scripts import transform as t
from scripts import load as l
# from scripts import deploy as d  # REPO_261031: deploy.py (dashboard deployment) is not distributed

# istantiate logger
user = 'paolap'
log_file = f"{homepath}logs/Update_{today}.log"
log = logger.Logger( log_file=log_file, log_level=logging.DEBUG)

# read prompt
rp = prompt_reader.PromptReader( user, json_prompt, log, today)
new_info, text, data, sources_list = rp.read_prompt()

Model = False # to train the GPT model
Deploy = False # to deploy the streamlit app

# source = 'MINIS'
# type_source = 'data'
# today = '20250826'
# Extract = True
# Transform = True
# Load = True
# new_info = False

for type_source, sources in sources_list.items():
    
    print(type_source)
    print(sources)
    
    log.info(type_source)
    log.info(sources)

    for source in sources.keys():
        
        # ETL process
        Extract = sources[source]['Extract']
        Transform = sources[source]['Transform']
        Load = sources[source]['Load']
        
        ###################
        # EXTRACT PROCESS #
        ###################
        
        extract_ok = True  # PATCH_ISTAT_RATELIMIT_261026
        if Extract:
            
            log.info( 'EXTRACT PROCESS START')
            
            try:
                e.extract_process(homepath, type_source, source, new_info, today, log )
                log.info( 'EXTRACT PROCESS END')
            except Exception as err:  # PATCH_EXTRACT_P3: 'e' e' il modulo extract
                log.exception(err)
                extract_ok = False  # PATCH_ISTAT_RATELIMIT_261026
            
            
        #####################
        # TRANSFORM PROCESS #
        #####################
            
        if Transform and not extract_ok:  # PATCH_ISTAT_RATELIMIT_261026
            log.critical(f'{source}: Extract non completata, Transform saltata (snapshot incompleto)')
        elif Transform:
            
            log.info( 'TRANSFORM PROCESS START')
            t.transform_process(homepath, type_source, source, new_info, today, log)
            log.info( 'TRANSFORM PROCESS END')
            

################
# LOAD PROCESS #
################

# PATCH_LOAD_261026: la Load parte se il flag e' True per almeno una fonte (prima contava solo l'ultima)
Load = any(flags.get('Load', False) for srcs in sources_list.values() for flags in srcs.values())
if Load:
    log.info( 'LOAD PROCESS START')
    l.load_process( homepath, sources_list, log)
    log.info( 'LOAD PROCESS END')

#################
# MODEL PROCESS #
#################

if Model:
    pass

##################
# DEPLOY PROCESS #
##################

if Deploy:
    log.info('DEPLOYMENT PROCESS START')
    from scripts import deploy as d  # REPO_261031: not distributed in the repository
    d.deploy_process(homepath, log, lfs=True)
    log.info('DEPLOYMENT PROCESS END')
    
# stop the timer
end_time = time.time()

# clculate the elapsed time
elapsed_time = end_time - start_time

# print the elapsed time in seconds and hours
log.info( f"Elapsed time in seconds: {elapsed_time}" )
log.info( f"Elapsed time in hours: {elapsed_time/3600}")