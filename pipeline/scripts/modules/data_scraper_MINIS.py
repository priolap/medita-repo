
# -*- coding: utf-8 -*-
"""
Created on Sat Mar 25 14:15:13 2023
@author: paolap

this routine:
a) scrapes relevant info about author, name, type, link of each data in salute.gov.it
b) returns as output a dataframe of this information
c) given the full list above, downloads from each link 
    - the csv
    - if zip archive, it unzips it and rename it accordingly

NB: if UPDATE_ANAG=True data download cannot be performed due to an issue on RSS xml 
in this case only the information is updated
"""

import re, os, io, zipfile, tqdm, requests, shutil
import pandas as pd
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from scripts.modules.utils import json_handler as jh
import ssl
from requests.adapters import HTTPAdapter
import urllib.parse
import ast, re

def data_scraper( homepath=None, file_in=None, today=None, UPDATE_ANAG=False,
                 log = None):
           
    # General function to scrape the data
    def scrape_data(soup, label):
        block = soup.find('div', text=label)
        if block:
            next_div = block.find_next_sibling('div')
            return next_div.get_text(strip=True) if next_div else 'NA'
        return 'NA'
    
    def clean_varname_title(title):
        # Long dashes -> "-"  (es. "(01/01/2024 – 30/06/2024)")
        title = title.replace("\u2013", "-").replace("\u2014", "-")
        # Remove " - Anno 2021" and " anno 2025"
        title = re.sub(r"\s*-?\s*[Aa]nno\s*\d{4}", "", title)
        # Remove patterns like " - 2010-2019"
        title = re.sub(r"\s*-\s*\d{4}-\d{4}", "", title)
        # Remove patterns like "dal 2010 al 2019"
        title = re.sub(r"\s+dal\s+\d{4}\s+al\s+\d{4}", "", title)
        # Remove "2025 luglio-dicembre" / "2025 gennaio-giugno" at the end
        title = re.sub(r"\s+\d{4}\s+(gennaio-giugno|luglio-dicembre)$", "", title, flags=re.I)
        # Remove a year at the end of the title
        title = re.sub(r"\s+\d{4}$", "", title)
        # Remove date ranges in parentheses like "(01/07/2022 - 31/12/2022)"
        title = re.sub(r"\s*\(\d{2}/\d{2}/\d{4}\s*-\s*\d{2}/\d{2}/\d{4}\)", "", title)
        # Remove month ranges in parentheses like "(07/2025 - 12/2025)"
        title = re.sub(r"\s*\(\d{2}/\d{4}\s*-\s*\d{2}/\d{4}\)", "", title)
        # Remove trailing hyphen and spaces (e.g. " -")
        title = re.sub(r"\s*-\s*$", "", title)
        # Replace multiple whitespaces (if any) with a single space
        title = re.sub(r"\s{2,}", " ", title)
        return title.strip()
    
    # attributes to be scraped
    columns_to_scrape = {
        'topics': 'Argomenti',
        'data_format': 'Formato dati',
        'update_frequency': 'Frequenza Aggiornamento',
        'loading_date': 'Data caricamento',
        'last_update_source': 'Data ultimo aggiornamento',
        'last_meta_mod': 'Data ultima modifica metadato',
        'source': 'Fonte',
        'admin_info': 'Nome Funzionario',
        'permalink': 'Permalink'
    }
    
    home_url = 'https://www.dati.salute.gov.it'
    rss_url = f'{home_url}/rss.xml'
    fold_path = f"{homepath}data/input/MINIS/{today}/"
    
    """ dec-2023, SSL issue """
    class SSLAdapter(HTTPAdapter):
        def __init__(self, ssl_context, **kwargs):
            self.ssl_context = ssl_context
            super().__init__(**kwargs)
    
        def init_poolmanager(self, *args, **kwargs):
            kwargs['ssl_context'] = self.ssl_context
            return super().init_poolmanager(*args, **kwargs)
    
    ssl_context = ssl.create_default_context()
    ssl_context.set_ciphers('DEFAULT:@SECLEVEL=1')
        
    if UPDATE_ANAG:
        
        # import pdb
        # pdb.set_trace()
        
        #=============================================================================
        # SCRAPE INFO FROM RSS DATA
        #=============================================================================
    
        session = requests.Session()
        session.mount('https://', SSLAdapter(ssl_context))
        
        response = session.get(rss_url)
        response.encoding = 'utf-8'
        # parse the XML feed and extract the title elements
        root = ET.fromstring(response.content)
    
        # parse the XML feed and extract the 'titolo' and 'href' elements
        data = []
        ext_allowed = ('.zip', '.xlsx', '.xls', '.csv', '.ods')
        pattern = re.compile(r'(' + '|'.join(map(re.escape, ext_allowed)) + r')$', re.IGNORECASE)
    
        for item in root.findall(".//item"):
            
            file_name = item.find("title").text.strip()
            var_name = clean_varname_title(file_name)
            
            # Get the link
            url = item.find("link").text
            url = url.replace('.itit','.it/it')
            
            # Get description and clean it
            desc = item.find("description").text
            desc = re.sub(r'<.*?>', '', desc, flags=re.DOTALL)
            desc = re.sub("&.*?;", "", desc)
            desc = ' '.join(desc.strip().split())
            desc = desc.replace('Il data-setcontiene', 'Il data-set contiene')
            
            # Add data to the list
            data.append((file_name, var_name, desc, url))
            
        # Create DataFrame
        OUTPUT = pd.DataFrame(data, columns=['FILE_NAME', 'VAR_NAME', 'DESC', 'url'])

        # =============================================================================
        # GET PLAIN-TEXT or XML-TEXT FORMAT FROM SCRAPED HREFS
        # AND ADD DESCRIPTION/ADMIN INFO
        # =============================================================================
        
        progbar = tqdm.tqdm(total=len(OUTPUT), desc='EXTRACTING DATA...')
        # PATCH_EXTRACT_P3: colonna object, cosi' .at accetta elenchi di link (pandas 3)
        OUTPUT['download_link'] = pd.Series([None] * len(OUTPUT), index=OUTPUT.index, dtype=object)
        
        for i, url in enumerate(OUTPUT.url):
            progbar.update(1)
            
            is_csvzip = False
            download_links = []
            
            # SSL auth
            session = requests.Session()
            session.mount('https://', SSLAdapter(ssl_context))
            
            response = session.get(url)
            soup = BeautifulSoup(response.content, "html.parser")
            
            if response.status_code == 503:
                log.critical('Server Not Available')
                OUTPUT.loc[i, 'download_link'] = 'NA'
                
            elif response.status_code == 404:
                log.critical('Page Not Found')
                OUTPUT.loc[i, 'download_link'] = 'NA'
                
            else:
    
                # Iterate over columns and scrape data based on labels
                for column, label in columns_to_scrape.items():
                    OUTPUT.at[i, column] = scrape_data(soup, label)
                    
                # Scrape a case-insensitive check on the last 3 chars
                href_contents = [x['href'] for x in soup.find_all('a', href=True)]
                
                # Filter based on the allowed extensions
                href_filtered = [x for x in href_contents if pattern.search(x)]
                
                # Prioritize _csv.zip files if they exist
                is_csvzip = any([href for href in href_filtered if '_csv.zip' in href.lower()])
                
                # If _csv.zip files exist, return them, otherwise return the filtered non-zip file types or general .zip
                if is_csvzip:
                    download_links = [home_url + href for href in href_filtered if '_csv.zip' in href.lower()]
                else:
                    download_links = [home_url + href for href in href_filtered]
                
                # Decode the Latin-encoded URLs
                download_links = [urllib.parse.unquote(link) for link in download_links]
                download_links = list(set(download_links))
                
                if download_links:
                    OUTPUT.at[i, 'download_link'] = download_links
                else:
                    OUTPUT.at[i, 'download_link'] = 'NA'
             
        progbar.close()
                
        OUTPUT = OUTPUT.sort_values(by='FILE_NAME', ascending=True)
        OUTPUT.to_csv( homepath + f'config/info_MINIS_raw_{today}.csv', index=False, encoding='cp1252')
        
        # suspend to check the var_code
        log.critical('Updated DATA ANAG Done. Please map VARCODE and check NEW variables before continue')
        return
        
    else:
        """ when the ANAG INFO is ready """
        OUTPUT = pd.read_csv(homepath + 'config/info_MINIS_raw.csv', encoding='cp1252')
        jhandler = jh.JsonHandler( file_tgt= file_in, encoding='utf-8')
        jhandler.json_writer(data=pd.DataFrame(OUTPUT))
            
    # =============================================================================
    # GET DATA FROM CSV / ZIP / XLS
    # =============================================================================
    
    jhandler = jh.JsonHandler( file_tgt= file_in, encoding='utf-8')
    OUTPUT = jhandler.json_reader()
    
    if not os.path.exists(fold_path):
        os.makedirs(fold_path)
    
    progbar = tqdm.tqdm(total = len(OUTPUT), desc = 'DOWNLOADING DATA...')

    # cast to prevent deprecation warnings
    OUTPUT['file_in'] = None
    OUTPUT['EXT_TYPE'] = None
    OUTPUT['last_update'] = None
    
    # import pdb
    # pdb.set_trace()
    
    # Loop over each row in OUTPUT DataFrame
    for idx in range(0, len(OUTPUT)):
        print(idx)
        print(OUTPUT.loc[idx, 'FILE_NAME'].lower())
        
        progbar.update(1)
        new_name = []
        
        # Convert the string representation of the list into an actual list
        links = ast.literal_eval(OUTPUT.loc[idx, 'download_link'])
        
        name = OUTPUT.loc[idx, 'FILE_NAME'].lower()
        name = re.sub(r'\W+', '_', name)
        if name.endswith('_'):
            name = name[:-1]  # Remove last underscore if present
        
        # Initialize a temporary counter only if there are multiple files
        total_files = 0
        for l in links:
            ext_type = l.split('.')[-1].lower()
            
            # SSL authorization
            session = requests.Session()
            session.mount('https://', SSLAdapter(ssl_context))
            response = session.get(l)
            
            if ext_type in ['csv', 'xls', 'xlsx', 'ods']:
                total_files += 1
            elif ext_type == 'zip':
                # Handle zip file to calculate file count inside
                zip_file = zipfile.ZipFile(io.BytesIO(response.content))
                zip_files = zip_file.namelist()
                total_files += len(zip_files)
    
        # Re-process each link with the appropriate file naming strategy
        file_counter = 1
        for l in links:
            ext_type = l.split('.')[-1].lower()
            
            # Re-establish SSL for download
            session = requests.Session()
            session.mount('https://', SSLAdapter(ssl_context))
            response = session.get(l)
            
            if ext_type in ['csv', 'xls', 'xlsx', 'ods']:
                if total_files == 1:
                    # Single file, no counter
                    new_name.append(f"{name.lower()}.{ext_type}")
                else:
                    # Multiple files, use counter
                    new_name.append(f"{name.lower()}_{file_counter:02d}.{ext_type}")
                    file_counter += 1
                
                fileout_path = os.path.join(fold_path, new_name[-1])
                
                with open(fileout_path, 'wb') as file:
                    file.write(response.content)
                    
            elif ext_type == 'zip':
                zip_file = zipfile.ZipFile(io.BytesIO(response.content))
                zip_folder = os.path.join(homepath, "unzipped_files")
                os.makedirs(zip_folder, exist_ok=True)
                zip_file.extractall(zip_folder)
                
                # Move files up if they are nested in a directory
                for item in os.listdir(zip_folder):
                    item_path = os.path.join(zip_folder, item)
                    if os.path.isdir(item_path):
                        for subdir_item in os.listdir(item_path):
                            subdir_item_path = os.path.join(item_path, subdir_item)
                            if os.path.isfile(subdir_item_path):
                                root_path = os.path.join(zip_folder, subdir_item)
                                shutil.move(subdir_item_path, root_path)
                        os.rmdir(item_path)
                
                # Iterate over extracted files
                zip_files = os.listdir(zip_folder)
                for item in zip_files:
                    item_ext = item.split('.')[-1].lower()
                    
                    if total_files == 1:
                        # Single file, no counter
                        new_name.append(f"{name.lower()}.{item_ext}")
                    else:
                        # Multiple files, use counter
                        new_name.append(f"{name.lower()}_{file_counter:02d}.{item_ext}")
                        file_counter += 1
                    
                    old_path = os.path.join(zip_folder, item)
                    new_path = os.path.join(fold_path, new_name[-1])
                    
                    if os.path.exists(new_path):
                        os.remove(new_path)
                    shutil.move(old_path, new_path)
            
            # Update the DataFrame with the new file names
            OUTPUT.at[idx, 'file_in'] = new_name
            OUTPUT.at[idx, 'EXT_TYPE'] = ext_type
            OUTPUT.at[idx, 'last_update'] = today
        
        progbar.close()
             
    # export info updated
    jhandler = jh.JsonHandler( file_tgt= file_in, encoding='utf-8')
    jhandler.json_writer(data=OUTPUT)
    
    # remove temp folders
    # shutil.rmtree(zip_folder)
    
    log.info('success')   

