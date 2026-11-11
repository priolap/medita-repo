# -*- coding: utf-8 -*-
"""
Created on Fri Jul 21 13:23:52 2023

This function simply takes in:
    data master: data that has been stored from the previous run
    data last : data that has been made from the last run
    
The outcome is to merge data in a way that stores it since in MINIS
data is overwritten in the website for few variables

The check_data_integrity function checks if the columns in both dataframes are 
the same and if the data types of each column are the same. If not, it logs the
 error and returns False.
 
The db_updater function first calls check_data_integrity to perform the integrity check. 
If the check fails, it logs the error and returns None. If the check passes, it merges
 the dataframes using pd.concat, drops the duplicates with drop_duplicates, and returns
 the updated dataframe.
 
The get_logs function returns all the logs that were created during the process.

@author: Posto05_Guest
"""

import pandas as pd

class UpdateDB:
    
    def __init__(self, data_name, data_master, data_last, output_log):
        self.data_name = data_name
        self.data_master = data_master
        self.data_last = data_last
        self.output_log = output_log
        

    def check_data_integrity(self):
        # Check if both dataframes have the same columns
        if set(self.data_master.columns) != set(self.data_last.columns):
            extra_columns_master = list(set(self.data_master.columns) - set(self.data_last.columns))
            extra_columns_last = list(set(self.data_last.columns) - set(self.data_master.columns))

            if extra_columns_master:
                mess = f"Error: {self.data_name} dataframes have extra columns in data_master: {', '.join(extra_columns_master)}."
                self.output_log.critical(mess)

            if extra_columns_last:
                mess = f"Error: {self.data_name} dataframes have extra columns in data_last: {', '.join(extra_columns_last)}."
                self.output_log.critical(mess)

            return False

        # Check if the data types of the columns are the same
        for column in self.data_master.columns:
            if self.data_master[column].dtype != self.data_last[column].dtype:
                mess = f'Error: The data type of column {column} is different between the {self.data_name} dataframes.'
                self.output_log.critical(mess)
                return False
        return True

    def db_updater(self):
        # Check data integrity
        if not self.check_data_integrity():
            mess = f'Error: Data integrity check for {self.data_name} failed.'
            self.output_log.critical(mess)
            mess = f'Proceeding to merge of {self.data_name} extra columns.'
            self.output_log.critical(mess)
            # return None
        
        # Create a list of columns that are in data_master but not in data_last
        extra_columns_master = list(set(self.data_master.columns) - set(self.data_last.columns))
        
        # Create a dataframe with the extra columns filled with NaN
        extra_data = pd.DataFrame(columns=extra_columns_master)
        
        # Concatenate dataframes and fill NaN in the extra columns
        db_updated = pd.concat([self.data_master, self.data_last, extra_data], ignore_index=True, sort=False)
        
        # Drop duplicates
        db_updated.drop_duplicates(inplace=True)
        
        mess = f'Info: {self.data_name} update was successful.'
        self.output_log.debug(mess)
        return db_updated, self.output_log
        