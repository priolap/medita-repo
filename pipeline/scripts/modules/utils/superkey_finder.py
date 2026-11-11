# -*- coding: utf-8 -*-
"""
Created on Mon Feb 26 13:36:31 2024

@author: paola
"""

from itertools import combinations
import pandas as pd
import sys

def find_super_key(df):
    columns = df.columns
    n = len(columns)
    
    # Iterate over the number of columns in the combination
    for r in range(1, n + 1):
        # Generate all combinations of columns of length r
        for subset in combinations(columns, r):
            # Check if the current combination results in unique rows
            if not df.duplicated(subset=subset).any():
                return list(subset)  # Return the first unique combination found
                
    return None  # Return None if no unique combination is found

def patch_wrong_joins(df, log):
    """ it sums the values for the duplicate records for the case of 
    Corrispondenze ASL-Comuni e popolazione residente anno 2022
    CORR_COMUPOPL_AASL """
    
    # Identifies all rows for the comune of Torino
    torino_rows = df[df['COMUNE'].str.strip().str.upper() == 'TORINO']

    if torino_rows.empty:
        log.critical('No rows found for Torino! Exiting...')
        sys.exit()
        return df

    # Sum the values for Torino
    total_maschi = torino_rows['MASCHI'].astype(float).sum()
    total_femmine = torino_rows['FEMMINE'].astype(float).sum()
    total_totale = torino_rows['TOTALE'].astype(float).sum()
    
    # Get a representative row for Torino (e.g., the first row)
    torino_rep = torino_rows.iloc[0].copy()
    
    # Update the representative row with the summed values
    torino_rep['MASCHI'] = total_maschi
    torino_rep['FEMMINE'] = total_femmine
    torino_rep['TOTALE'] = total_totale

    # Remove the original Torino rows from the dataframe
    df = df[df['COMUNE'].str.strip().str.upper() != 'TORINO']

    # Append the patched Torino row back into the dataframe
    df = pd.concat([df, pd.DataFrame([torino_rep])], ignore_index=True)
    
    # Reset the index to ensure it's continuous
    df.reset_index(drop=True, inplace=True)

    log.info("patch applied")

    return df, log
