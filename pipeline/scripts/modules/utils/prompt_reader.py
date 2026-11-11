# -*- coding: utf-8 -*-
"""
Created on Tue Jul 25 11:14:06 2023

@author: paolap
"""
import json

class PromptReader:
    def __init__(self, user, json_prompt, log, today):
        self.user = user
        self.json_prompt = json_prompt
        self.log = log
        self.today = today
        
    def read_prompt(self):
        
        # open the file in read mode
        with open( self.json_prompt, 'r') as file:
            prompt = json.load(file)
            
        # homepath = prompt["path"]
        new_info = prompt["settings"]["NEW_INFO"] # boolean, true if it a new database or info_DB has changed
        text = prompt["sources"]["text"]
        data = prompt["sources"]["data"]
        # Process text and data sources
        sources_list = {'text': text, 'data': data}
        
        return new_info, text, data, sources_list
