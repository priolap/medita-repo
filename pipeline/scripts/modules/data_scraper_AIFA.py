# -*- coding: utf-8 -*-
"""
Created on Thu Mar 14 11:41:56 2024

@author: paola

2024-09-30 User-Agent added for scraping!
"""

import re, os, tqdm, requests
import pandas as pd
from bs4 import BeautifulSoup
from scripts.modules.utils import json_handler as jh

def data_scraper( homepath=None, file_in=None, today=None, UPDATE_ANAG=False,
                 log = None):
    
    
    fold_path = f"{homepath}data/input/AIFA/{today}/"
    
    base_url = "https://www.aifa.gov.it/"
    
    # headers = { 'User-Agent': 
    #            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
    # }
    
    headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.aifa.gov.it/",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


    #==========================================================================
    # SCRAPE INFO FROM HTML OPEN DATA
    #==========================================================================
     
    if UPDATE_ANAG:

        point = "web/guest/spesa-e-consumo-relativi-al-flusso-della-farmaceutica-convenzionata-e-degli-acquisti-diretti"
        URL = f"{base_url}{point}"
        
        # response = requests.get(URL, headers=headers)
        response = requests.get(URL, headers=headers, allow_redirects=True, timeout=30)
        response.raise_for_status()  
    
        soup = BeautifulSoup(response.text, 'html.parser')
        item = soup.find('div', class_='journal-content-article')
        data = []
        
        # parse the html feed and extract the elements
        titolo = item.find_previous('h2', class_='portlet-title-text').text
        
        desc = soup.find('td', string=lambda t: t and "Descrizione:" in t)
        desc = desc.find_next_sibling('td')
        desc = [str(element) for element in desc.contents]
        desc = ''.join(desc).replace('<br/>', ' ')
        desc = desc.replace( '\n', '').replace( '\t','')
        
        links = item.find_all('a')
        pattern = re.compile(r'manuale operativo', re.IGNORECASE)
        
        for link in links:
            # The year part follows the link tag, so we get the next sibling
            year = link.next_sibling
            if pattern.search(year.strip()): 
                pdf =  f"{base_url}{link['href']}"
            elif link['href'].endswith('.csv'):
                href = f"{base_url}{link['href']}"
                file_name = f"{titolo}{year}"
                var_name = f"{titolo}"
                data.append((file_name, var_name, desc, URL, href, pdf))
        
        OUTPUT = pd.DataFrame(data)
        OUTPUT.columns = ['FILE_NAME','VAR_NAME','DESC', 'url_dset', 'download_link', 'url_pdf']
        
        # sort by name
        OUTPUT = OUTPUT.sort_values(by='FILE_NAME', ascending=True)
        OUTPUT.to_csv( homepath + f'config/info_AIFA_raw_{today}.csv', index=False, encoding='cp1252')
        
        # suspend to check the var_code
        log.critical('Updated ANAG Done. Please check variables before continue')
        return

    else:
        """ when the ANAG INFO is ready """
        OUTPUT = pd.read_csv(homepath + f'config/info_AIFA_raw.csv', encoding='cp1252')
        jhandler = jh.JsonHandler( file_tgt= file_in, encoding='utf-8')
        jhandler.json_writer(data=pd.DataFrame(OUTPUT))
        

    # =========================================================================
    # GET DATA FROM CSV / ZIP / XLS
    # =========================================================================
    
    jhandler = jh.JsonHandler( file_tgt= file_in, encoding='utf-8')
    OUTPUT = jhandler.json_reader()
    
    if not os.path.exists(fold_path):
        os.makedirs(fold_path)
        
    # cast to prevent deprecation warnings
    OUTPUT['file_in'] = None
    OUTPUT['EXT_TYPE'] = None
    OUTPUT['last_update'] = None
    
    for idx in range(0,len(OUTPUT)):

        link  = OUTPUT.loc[idx,'download_link']
        name = OUTPUT.loc[idx,'FILE_NAME'].lower()
        name = re.sub(r'\W+', '_', name)
        if name.endswith('_'): name = name[:-1] # last underscore
        
        # get dynamically the extension type
        ext_type = link.split('.')[-1].lower()
        
        # send a GET request to download the CSV file
        from urllib.parse import urljoin
        response = requests.get(urljoin(base_url, link), headers=headers, allow_redirects=True)
        # response = requests.get(link, headers=headers)
                
        if ext_type in ['csv','xls','xlsx','ods']:
            new_name = f'{name.lower()}.{ext_type}'
            fileout_path = fold_path + new_name
        
            with open(fileout_path, 'wb') as file:
                file.write(response.content)       
                
        OUTPUT.at[idx, 'file_in'] = [new_name]
        OUTPUT.at[idx,'EXT_TYPE'] = ext_type
        OUTPUT.at[idx,'last_update'] = today
   
    # export info updated
    jhandler = jh.JsonHandler( file_tgt= file_in, encoding='utf-8')
    jhandler.json_writer(data=OUTPUT)
    
    log.info('success')   
        
