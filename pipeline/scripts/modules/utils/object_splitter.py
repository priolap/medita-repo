# -*- coding: utf-8 -*-
"""
Created on Thu Mar 21 12:50:44 2024

function to split large files below 100 MB, according to GIT limits
@author: paola
"""
import os
import subprocess

def split_file_to_chunks(rootpath, prefix, log, max_size = 96 * 1024):
    
    log.debug( f'Generating the chunks for {prefix}')
    old_chunks = [x for x in os.listdir(f"{rootpath}/") if x.startswith(f'{prefix}_chunk')]
    
    for oc in old_chunks:
        log.debug('Chunks exist. Removed')
        os.remove(f"{rootpath}/{oc}")
        
    # Define the size of each chunk
    db_file_path = f"/mnt/c/{rootpath[3:]}/DB.sql" 
    output_prefix = "/mnt/c/" + os.path.join(rootpath[3:], f"{prefix}_chunk").replace('\\','/')

    try:
        subprocess.run(['wsl', 'split', '-b', f'{max_size}k','-d',  db_file_path, output_prefix], check=True)
        new_chunks = [x for x in os.listdir(rootpath) if x.startswith(f'{prefix}_chunk')]
        log.debug(f"Splitting complete. {new_chunks} chunks have been created.")
        # count them
        new_chunks = [x for x in os.listdir(rootpath) if x.startswith(f'{prefix}_chunk')]
        log.debug(f"Splitting complete. {len(new_chunks)} chunks have been created.")
        
    except subprocess.CalledProcessError as e:
        log.critical(f"Failed to split file: {e}")
        
    return log


# =============================================================================
# SENZA LINUX SUBSYSTEM
# =============================================================================

def split_db_chunks(self):
    
    self.log.debug( 'Generating the chunks DB')
    
    old_chunks = [x for x in os.listdir("{self.rootpath}/") if x.startswith('DB_chunk')]
    
    for oc in old_chunks:
        self.log.debug('Chunks exist. Removed')
        os.remove(oc)
        
    # Define the size of each chunk
    chunk_size = 96 * 1024 * 1024

    # open the large file
    with open(self.db_path, 'rb') as f:
        chunk_num = 0
        while True:
            # read a chunk of the specified size
            chunk = f.read(chunk_size)
            if not chunk:
                break
            
            chunk_enum = f"{chunk_num:03}"
            # write the chunk to a new file
            with open(f"{self.rootpath}/DB_chunk{chunk_enum}.sql", 'wb') as chunk_file:
                chunk_file.write(chunk)

            chunk_num += 1

    self.log.debug(f"Splitting complete. {chunk_num} chunks have been created.")