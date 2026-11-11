# -*- coding: utf-8 -*-
"""
Created on Wed Jun  7 15:23:41 2023

this routine is made to download data from Istat via API REST
thourgh the SDMX (Statistical Data and Metadata eXchange) xml language
promoted to exchange data from european datawarehouses (istat, eurostat)
@author: paolap
"""

# basics
import pandas as pd
import locale
import datetime as dt
import os, tqdm
import sys

# xml, json and sdmx utilities
import xml.etree.ElementTree as ET
from lxml import html
import requests, json, urllib3, itertools, io
from scripts.modules.utils import json_handler as jh

# PATCH_ISTAT_ESPLORADATI: richieste a esploradati.istat.it entro il limite di 5 al minuto per IP
# PATCH_ISTAT_RATELIMIT_261026: ISTAT blocca l'IP per 1-2 giorni oltre 5 richieste al minuto.
# Ogni richiesta HTTP verso ISTAT (redirect e nuovi tentativi compresi) passa dal limitatore:
#   - al massimo _ISTAT_MAX_FINESTRA invii in _ISTAT_FINESTRA secondi (margine rispetto a 5 in 60);
#   - almeno _ISTAT_MIN_INTERVAL secondi dall'ultima attivita' registrata.
# Invii e risposte sono scritti in logs/istat_requests.log: il limite vale anche tra
# un'esecuzione e la successiva (es. rilancio subito dopo un errore).
import time as _time
_ISTAT_MAX_FINESTRA = 4
_ISTAT_FINESTRA = 65.0
_ISTAT_MIN_INTERVAL = 15.0
_ISTAT_MAX_REDIRECT = 3
_ISTAT_REGISTRO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                '..', '..', 'logs', 'istat_requests.log'))
_istat_cache = {}
_istat_n = [0]
# PATCH_ISTAT_DSD_261026B: copia di ogni risposta XML di ISTAT, per la diagnostica
import re as _re
_ISTAT_XML_DIR = os.path.join(os.path.dirname(_ISTAT_REGISTRO), 'istat_xml')

def _istat_registro_leggi():
    """Tempi degli ultimi invii e dell'ultima attivita' registrata (anche di esecuzioni precedenti)."""
    try:
        with open(_ISTAT_REGISTRO, encoding='utf-8') as f:
            righe = f.readlines()[-200:]
    except FileNotFoundError:
        return [], 0.0
    invii, ultima = [], 0.0
    for riga in righe:
        campi = riga.rstrip('\n').split('\t')
        try:
            t = float(campi[1])
        except (IndexError, ValueError):
            continue
        ultima = max(ultima, t)
        if campi[0] == 'INVIO':
            invii.append(t)
    return invii, ultima

def _istat_registro_scrivi(tipo, url, esito=''):
    os.makedirs(os.path.dirname(_ISTAT_REGISTRO), exist_ok=True)
    ora = _time.time()
    with open(_ISTAT_REGISTRO, 'a', encoding='utf-8') as f:
        f.write(f"{tipo}\t{ora:.3f}\t{dt.datetime.fromtimestamp(ora):%Y-%m-%d %H:%M:%S}\t{esito}\t{url}\n")

def _istat_attendi():
    while True:
        invii, ultima = _istat_registro_leggi()
        ora = _time.time()
        recenti = sorted(t for t in invii if ora - t < _ISTAT_FINESTRA)
        attesa = ultima + _ISTAT_MIN_INTERVAL - ora
        if len(recenti) >= _ISTAT_MAX_FINESTRA:
            attesa = max(attesa, recenti[-_ISTAT_MAX_FINESTRA] + _ISTAT_FINESTRA - ora)
        if attesa <= 0:
            return
        _time.sleep(min(attesa, 60.0) + 0.5)

# PATCH_ISTAT_PROGRESSO_261027I: stato delle richieste di dati nel log (attesa, risposta, MB ricevuti)
import logging as _logging
import threading as _threading
_ISTAT_LOG = _logging.getLogger()
_ISTAT_ATTESA_LOG = 300.0     # messaggio "ancora in attesa" ogni 5 minuti
_ISTAT_PROGRESSO_LOG = 30.0   # messaggio "ricevuti N MB" ogni 30 secondi
_istat_salva_in = [None]      # PATCH_ISTAT_GREZZI_261028K: file in cui scrivere i dati man mano che arrivano

def _istat_richiesta(url, headers, kwargs):
    """Una sola richiesta HTTP verso ISTAT, dopo il limitatore e senza seguire redirect."""
    _istat_attendi()
    _istat_registro_scrivi('INVIO', url)
    _istat_n[0] += 1
    esito = 'ERRORE'
    dati = '/rest/data/' in url
    risposta = _threading.Event()
    t0 = _time.time()
    if dati:
        tmax = kwargs.get('timeout')
        tmax = tmax[1] if isinstance(tmax, tuple) else tmax
        _ISTAT_LOG.info(f'ISTAT: richiesta dati inviata, in attesa della risposta (massimo {tmax} s): {url}')
        def _battito():
            n = 0
            while not risposta.wait(_ISTAT_ATTESA_LOG):
                n += 1
                _ISTAT_LOG.info(f'ISTAT: ancora in attesa della risposta da {n * _ISTAT_ATTESA_LOG / 60:.0f} min: {url}')
        _threading.Thread(target=_battito, daemon=True).start()
    try:
        r = requests.get(url, headers=headers, allow_redirects=False, stream=dati, **kwargs)
        risposta.set()
        esito = str(r.status_code)
        if dati:
            _ISTAT_LOG.info(f'ISTAT: risposta {r.status_code} dopo {_time.time() - t0:.0f} s'
                            + (', download in corso' if r.status_code == 200 else '') + f': {url}')
            if r.status_code == 200:
                # PATCH_ISTAT_GREZZI_261028K: compressione nel log; dati scritti su disco man mano
                _ISTAT_LOG.info(f"ISTAT: compressione della risposta: {r.headers.get('Content-Encoding') or 'nessuna'}")
                dest = _istat_salva_in[0]
                pezzi, ricevuti = [], 0
                t1 = ultimo = _time.time()
                fout = open(dest + '.part', 'wb') if dest else None
                try:
                    for pezzo in r.iter_content(chunk_size=1 << 20):
                        if fout:
                            fout.write(pezzo)
                        else:
                            pezzi.append(pezzo)
                        ricevuti += len(pezzo)
                        if _time.time() - ultimo >= _ISTAT_PROGRESSO_LOG:
                            ultimo = _time.time()
                            _ISTAT_LOG.info(f'ISTAT: ricevuti {ricevuti / 1e6:.0f} MB in {ultimo - t1:.0f} s: {url}')
                finally:
                    if fout:
                        fout.close()
                if fout:
                    os.replace(dest + '.part', dest)
                    r._content = b''  # il contenuto e' nel file dest
                else:
                    r._content = b''.join(pezzi)
                r._content_consumed = True
                del pezzi
                _ISTAT_LOG.info(f'ISTAT: download completato, {ricevuti / 1e6:.1f} MB in {_time.time() - t1:.0f} s: {url}')
            else:
                r.content  # corpo della risposta di errore, letto subito
        return r
    except KeyboardInterrupt:
        esito = 'INTERROTTA'
        raise
    except Exception:
        esito = 'ERRORE'  # PATCH_ISTAT_GREZZI_261028K: anche se la risposta era 200 e il download si e' interrotto
        raise
    finally:
        risposta.set()
        _istat_registro_scrivi('FINE', url, esito)

def _istat_get(url, **kwargs):
    if '/codelist/' in url and url in _istat_cache:
        return _istat_cache[url]
    kwargs.setdefault('timeout', 300)
    kwargs.pop('allow_redirects', None)
    # PATCH_ISTAT_ACCEPT: intestazioni come istatR (Accept esplicito, niente Accept-Language)
    headers = {k: v for k, v in (kwargs.pop('headers', None) or {}).items() if k.lower() != 'accept-language'}
    headers.setdefault('User-Agent', 'Mozilla/5.0')
    headers.setdefault('Accept', 'application/vnd.sdmx.structure+xml; version=2.1')  # PATCH_ISTAT_CONFORME_261027G
    for tentativo in range(3):
        if tentativo:
            _time.sleep(30 * tentativo)  # pausa in piu' prima di ritentare dopo un errore del server
        r = _istat_richiesta(url, headers, kwargs)
        salti = 0
        while r.status_code in (301, 302, 303, 307, 308):
            salti += 1
            if salti > _ISTAT_MAX_REDIRECT:
                raise RuntimeError(f"ISTAT: piu' di {_ISTAT_MAX_REDIRECT} redirect a partire da {url}, mi fermo.")
            nuovo = requests.compat.urljoin(r.url, r.headers.get('Location', ''))
            print(f"ISTAT redirect {r.status_code}: {r.url} -> {nuovo}")
            r = _istat_richiesta(nuovo, headers, kwargs)
        if r.status_code not in (500, 502, 503, 504):
            break
        print(f"ISTAT {r.status_code} su {url}: tentativo {tentativo + 1} di 3")
    if '/rest/data/' not in url:  # PATCH_ISTAT_DSD_261026B
        try:
            os.makedirs(_ISTAT_XML_DIR, exist_ok=True)
            nome = _re.sub(r'[^A-Za-z0-9_.-]+', '_', url.split('/rest/', 1)[-1])[:150]
            with open(os.path.join(_ISTAT_XML_DIR, f"{nome}.xml"), 'wb') as f:
                f.write(r.content)
        except OSError:
            pass
    if r.status_code in (403, 429):
        raise RuntimeError(f"ISTAT ha rifiutato la richiesta ({r.status_code}): "
                           f"possibile blocco per troppe richieste, mi fermo. URL: {url}")
    if '/rest/data/' in url and r.status_code != 404:  # la 404 sui dati la gestisce data_scraper
        r.raise_for_status()
        ctype = r.headers.get('Content-Type', '')
        if 'csv' not in ctype.lower():
            raise RuntimeError(f"ISTAT non ha restituito un CSV (Content-Type: {ctype}). URL: {url}")
    if '/codelist/' in url and r.status_code == 200:
        _istat_cache[url] = r
    return r

# PATCH_ISTAT_SENZABLOCCHI_261027F: nomi e descrizioni per lingua (esploradati mette l'inglese per primo)
_XML_LANG = '{http://www.w3.org/XML/1998/namespace}lang'

def _istat_nome(el, lingua):
    """Testo del <Name> nella lingua richiesta."""
    if el is None:
        return None
    nomi = el.findall('Name')
    for n in nomi:
        if n.get(_XML_LANG) == lingua:
            return n.text
    return None  # PATCH_ISTAT_CONFORME_261027G: solo la lingua richiesta, nessun ripiego su un'altra

def _istat_obs_count(root):
    """Numero di osservazioni dichiarato da ISTAT (annotazione obs_count di availableconstraint)."""
    for ann in root.iter('Annotation'):
        if ann.get('id') == 'obs_count':
            try:
                return int(ann.findtext('AnnotationTitle'))
            except (TypeError, ValueError):
                return None
    return None

# PATCH_ISTAT_GREZZI_261028K: richiesta di dati scritta direttamente nel file dest
def _istat_get_su_file(url, dest, **kwargs):
    _istat_salva_in[0] = dest
    try:
        return _istat_get(url, **kwargs)
    finally:
        _istat_salva_in[0] = None

# PATCH_ISTAT_GREZZI_261028K: download di un dataflow un anno alla volta (startPeriod/endPeriod)
def _istat_dati_per_anno(main_url, num_id, ref_id, fold_path, log):
    """Testo CSV completo del dataflow, ottenuto unendo le risposte anno per anno; None se senza dati."""
    url_vincolo = '/'.join([main_url, 'availableconstraint', num_id, 'all', 'all', 'all']) + '?references=none'
    r = _istat_get(url_vincolo, verify=False, timeout=(30, 1800))
    r.raise_for_status()
    root = ET.fromstring(r.content)
    for el in root.iter():
        _, _, el.tag = el.tag.rpartition('}')
    anni = None
    for kv in root.iter('KeyValue'):
        if kv.get('id') == 'TIME_PERIOD':
            s, e = kv.findtext('TimeRange/StartPeriod'), kv.findtext('TimeRange/EndPeriod')
            if s and e:
                anni = (int(s[:4]), int(e[:4]))
    if anni is None:
        raise RuntimeError(f'{ref_id}: periodo (TIME_PERIOD) non indicato da ISTAT, impossibile scaricare per anno')
    log.info(f'{ref_id}: download per anno, dal {anni[0]} al {anni[1]}')
    dir_anni = f"{fold_path}_anni/{ref_id}/"
    os.makedirs(dir_anni, exist_ok=True)
    intestazione, corpi = None, []
    for anno in range(anni[0], anni[1] + 1):
        parte = f"{dir_anni}{anno}.csv"
        if os.path.exists(parte):
            log.info(f'{ref_id}: anno {anno} gia\' scaricato, nessuna richiesta a ISTAT')
        else:
            url = '/'.join([main_url, 'data', num_id, 'all', 'all']) + f'?startPeriod={anno}&endPeriod={anno}'
            r = _istat_get_su_file(url, parte, headers={"Accept": "text/csv", 'User-Agent': 'Mozilla/5.0'},
                                   verify=False, timeout=(30, 3600))
            if r.status_code == 404:
                open(parte, 'wb').close()
            log.info(f'{ref_id}: anno {anno}: {os.path.getsize(parte) / 1e6:.1f} MB'
                     + ('' if r.status_code != 404 else ' (404, nessuna osservazione)'))
            del r
        with open(parte, 'rb') as f:
            testo = f.read().decode('utf-8')
        if not testo.strip():
            continue
        testa, _, corpo = testo.partition('\n')
        if intestazione is None:
            intestazione = testa
        elif testa != intestazione:
            raise RuntimeError(f'{ref_id}: intestazione CSV dell\'anno {anno} diversa da quella degli anni precedenti')
        corpi.append(corpo if corpo.endswith('\n') or not corpo else corpo + '\n')
    if intestazione is None:
        return None
    return intestazione + '\n' + ''.join(corpi)

# no warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Set the default locale to Italian
# locale.setlocale(locale.LC_ALL, 'it_IT.utf8')

def data_scraper( homepath=None, file_in=None, today=None, UPDATE_ANAG=False, log=None ):
    
    # import pdb
    # pdb.set_trace()
    # PATCH_ISTAT_RATELIMIT_261026: per riprendere uno scarico interrotto in un altro giorno
    # (cmd: set MEDITA_ISTAT_CARTELLA=AAAAMMGG); altrimenti la cartella di oggi
    fold_path = f"{homepath}data/input/ISTAT/{os.environ.get('MEDITA_ISTAT_CARTELLA') or today}/"
    # PATCH_ISTAT_ESPLORADATI: cartella creata solo prima del download (vedi sotto)
        
    # paths
    # main_url = "http://sdmx.istat.it/SDMXWS/rest"
    # main_url = "https://sdmx.istat.it/SDMXWS/rest"  # dismesso: redirect in loop (ott. 2026)
    main_url = "https://esploradati.istat.it/SDMXWS/rest"  # PATCH_ISTAT_ESPLORADATI
    json_url = f'{main_url}/dataflow?format=jsonstructure'
    agency_id = 'IT1'

    # =============================================================================
    # RETRIEVE ALL DATA INFORMATION AVAILABLE
    # =============================================================================
    
    if UPDATE_ANAG:
        # PATCH_ISTAT_ESPLORADATI: l'anagrafica resta quella di config/info_ISTAT_raw.csv;
        # una sola richiesta per controllare che i dataflow esistano ancora sul nuovo servizio.
        response = _istat_get(f'{main_url}/dataflow/{agency_id}/all/latest',  # PATCH_ISTAT_CONFORME_261027G
                              headers={'Accept-Language': 'it', 'User-Agent': 'Mozilla/5.0'},
                              verify=True)
        response.raise_for_status()
        tree = ET.iterparse(io.BytesIO(response.content))
        for _, el in tree:
            _, _, el.tag = el.tag.rpartition('}')
        root = tree.root
        lang = '{http://www.w3.org/XML/1998/namespace}lang'
        flows = {}
        for flow in root.iter('Dataflow'):
            names = {n.get(lang): n.text for n in flow.findall('Name')}
            ref = flow.find('Structure/Ref')
            flows[flow.get('id')] = (names.get('it', next(iter(names.values()), '')),
                                     ref.get('id') if ref is not None else '')

        RAW = pd.read_csv(homepath + 'config/info_ISTAT_raw.csv', encoding='cp1252')
        RAW['presente_esploradati'] = RAW['id'].astype(str).isin(flows)
        RAW['nome_esploradati'] = [flows.get(str(i), ('', ''))[0] for i in RAW['id']]
        RAW['dsd_esploradati'] = [flows.get(str(i), ('', ''))[1] for i in RAW['id']]
        RAW['dsd_uguale'] = RAW['dsd_esploradati'] == RAW['VAR_CODE']
        file_check = f"{homepath}config/info_ISTAT_check_{today}.xlsx"
        RAW.to_excel(file_check, index=False)

        mancanti = RAW.loc[~RAW['presente_esploradati'], 'id'].tolist()
        diversi = RAW.loc[RAW['presente_esploradati'] & ~RAW['dsd_uguale'], 'id'].tolist()
        log.info(f'Dataflow disponibili su esploradati: {len(flows)}')
        log.critical(f'ISTAT: {len(RAW) - len(mancanti)}/{len(RAW)} dataflow presenti; '
                     f'mancanti: {mancanti}; DSD diversa: {diversi}. Controlla {file_check}')
        return

    else:
        """ when the ANAG INFO is ready """
        OUTPUT = pd.read_csv(homepath + 'config/info_ISTAT_raw.csv', encoding='cp1252')
        jhandler = jh.JsonHandler( file_tgt= file_in, encoding='utf-8')
        jhandler.json_writer(data=pd.DataFrame(OUTPUT))
        
    # =============================================================================
    # SETUP
    # =============================================================================
    
    if not os.path.exists(fold_path):  # PATCH_ISTAT_ESPLORADATI
        os.makedirs(fold_path)

    jhandler = jh.JsonHandler( file_tgt= file_in, encoding='utf-8')
    DB_INFO = jhandler.json_reader()
    # PATCH_ISTAT_FILEIN_261028L: 'file_in' object, cosi' ogni cella tiene una lista (pandas 3 la convertiva in stringa)
    if 'file_in' in DB_INFO.columns:
        DB_INFO['file_in'] = DB_INFO['file_in'].astype(object)
    else:
        DB_INFO['file_in'] = pd.Series([None] * len(DB_INFO), index=DB_INFO.index, dtype=object)
    
    num_ids = DB_INFO['id']       
    progbar =  tqdm.tqdm( total=len(num_ids), desc = 'CONNECTING VIA REST API...')
    mancanti = []  # PATCH_ISTAT_RATELIMIT_261026
    # PATCH_ISTAT_SALTA_261027H: dataflow da non scaricare in questa esecuzione (cmd: set MEDITA_ISTAT_SALTA=DCIS_DECESSI)
    saltati = [v.strip() for v in os.environ.get('MEDITA_ISTAT_SALTA', '').split(',') if v.strip()]
    if saltati:
        log.warning(f'ISTAT: dataflow da saltare (MEDITA_ISTAT_SALTA): {saltati}')
    # PATCH_ISTAT_GREZZI_261028K: dataflow da scaricare un anno alla volta (cmd: set MEDITA_ISTAT_PERANNO=DCIS_MORTALITA1)
    per_anno = [v.strip() for v in os.environ.get('MEDITA_ISTAT_PERANNO', '').split(',') if v.strip()]
    if per_anno:
        log.warning(f'ISTAT: dataflow da scaricare per anno (MEDITA_ISTAT_PERANNO): {per_anno}')
    log.info(f'ISTAT: cartella dello snapshot {fold_path}; registro richieste {_ISTAT_REGISTRO}')
    
    for kk, num_id in enumerate(num_ids):
        
        progbar.update(1)
        
        ref_id = DB_INFO.loc[DB_INFO.id == num_id,'VAR_CODE'].values[0]
        file_out = f"{fold_path}{ref_id}"
        log.debug( f'processing: {ref_id}' )
        
        # brakets needed for the transform phase
        DB_INFO.at[kk, 'file_in'] = [f"{ref_id}.csv"]  # PATCH_ISTAT_FILEIN_261028L: lista, non stringa

        # PATCH_ISTAT_RATELIMIT_261026: ripresa, nessuna richiesta per un dataset gia' scaricato
        if os.path.exists(f"{file_out}.csv") and os.path.getsize(f"{file_out}.csv") > 0:
            log.info(f'{ref_id}: gia\' presente in {fold_path}, nessuna richiesta a ISTAT')
            continue
        if ref_id in saltati:  # PATCH_ISTAT_SALTA_261027H
            log.critical(f'{ref_id}: saltato su richiesta (MEDITA_ISTAT_SALTA), nessuna richiesta a ISTAT')
            continue
        
        
        # =====================================================================
        # GET ALL DATA WITHOUT INFORMATION DESCRIPTIONS, FROM RESOURCE == DATA
        # =====================================================================

        resource = 'data'
        # specify the endpoint URL with parameters
        chunks_path = [main_url, resource, num_id, 'all', 'all']  # PATCH_ISTAT_CONFORME_261027G: /data/{flowRef}/{key}/{providerRef}
        endpoint_url = '/'.join(chunks_path)

        # send the HTTP request
        # PATCH_ISTAT_GREZZI_261028K: dati grezzi su disco (_grezzi) o per anno (_anni), riusati alla ripresa
        dir_grezzi = f"{fold_path}_grezzi/"
        os.makedirs(dir_grezzi, exist_ok=True)
        grezzo = f"{dir_grezzi}{ref_id}.csv"
        if ref_id in per_anno:
            response = _istat_dati_per_anno(main_url, num_id, ref_id, fold_path, log)
            if response is None:
                log.critical(f'ISTAT: {ref_id} (dataflow {num_id}) senza dati in nessun anno: saltato')
                mancanti.append(ref_id)
                continue
        else:
            if os.path.exists(grezzo):
                log.info(f'{ref_id}: dati grezzi gia\' scaricati ({os.path.getsize(grezzo) / 1e6:.1f} MB), '
                         f'nessuna richiesta di dati a ISTAT')
            else:
                response = _istat_get_su_file(endpoint_url, grezzo,
                                        headers = {"Accept": "text/csv",'User-Agent':'Mozilla/5.0'},
                                        verify=False,
                                        timeout=(30, 3600) )  # PATCH_ISTAT_SENZABLOCCHI_261027F: senza risposta entro un'ora lo scarico si ferma
                if response.status_code == 404:  # PATCH_ISTAT_RATELIMIT_261026
                    log.critical(f'ISTAT: {ref_id} (dataflow {num_id}) non disponibile (404): saltato, '
                                 f'nessun\'altra richiesta per questo dataflow')
                    mancanti.append(ref_id)
                    continue
            with open(grezzo, 'rb') as f:
                response = f.read().decode("utf-8")
        DSET = pd.read_csv(io.StringIO(response))
        n_righe = len(DSET)  # PATCH_ISTAT_SENZABLOCCHI_261027F: per il confronto con obs_count

        #=====================================================================
        #TABLE DB MANIPULATION
        #=====================================================================
            
        # get rid of useless fields
        DSET = DSET.dropna(axis=1, how='all') 
        
        # ======================================================================
        # GET DATAFLOWS DESCRIPTION FROM RESOURCE == DATAFLOW
        # ======================================================================
        
        resource = 'dataflow'
        chunks_path = [main_url, resource, agency_id, num_id, 'latest']  # PATCH_ISTAT_CONFORME_261027G
        endpoint_url = '/'.join(chunks_path)
        
        response = _istat_get(endpoint_url,verify=False)

        tree = ET.iterparse(io.StringIO(response.text))
        for _, el in tree:
            _, _, el.tag = el.tag.rpartition('}') 
        root = tree.root
        
        # ids = [x.get("id") for x in root.iter() if x.get('id') not in [None,'Unknown']]
        names = [x.findall("Name") for x in root.iter() if x.findall('Name') != []]
        # unlist nested lists
        names = list(itertools.chain(*names))
        variable_names = [n.text for n in names]
        # PATCH_ISTAT_SENZABLOCCHI_261027F: nomi per lingua (esploradati mette l'inglese per primo)
        _df = root.find('.//Dataflow')
        nome_it = _istat_nome(_df, 'it') if _df is not None else None  # PATCH_ISTAT_CONFORME_261027G: solo italiano
   
    
        # =====================================================================
        # GET VARIABLE DIMENSION FROM RESOURCE == DATASTRUCTURE
        # =====================================================================
        
        resource = 'datastructure'
        chunks_path = [main_url, resource, agency_id, ref_id, 'latest']  # PATCH_ISTAT_CONFORME_261027G
        endpoint_url = '/'.join(chunks_path)
        
        # Step 5: Send the HTTP request
        response = _istat_get(endpoint_url, verify=False)
     
        tree = ET.iterparse(io.StringIO(response.text))
        for _, el in tree:
            _, _, el.tag = el.tag.rpartition('}') # strip ns#
        root = tree.root
        
        dimensions_l = []
        for dimension in root.iter("Dimension"):
            # PATCH_ISTAT_DSD_261026B: <Dimension> senza id = riferimento (es. AttributeRelationship), non dichiarazione
            if "id" not in dimension.attrib:
                continue
            dimension_name = dimension.attrib["id"]

            refs = [enumeration.find("Ref") for enumeration in dimension.iter("Enumeration")]
            refs = [x for x in refs if x is not None]
            if not refs:  # PATCH_ISTAT_DSD_261026B
                log.warning(f'{ref_id}: dimensione {dimension_name} senza codelist, nessuna descrizione')
                continue
            dimension_id = refs[0].get("id")
    
            dimension_dict = {"dimension": dimension_name, 
                              "dimension_ID": dimension_id}
    
            dimensions_l.append(dimension_dict)
        
        # dimensions_l = pd.DataFrame(dimensions_l)
        dimensions_ids = [x['dimension_ID'] for x in dimensions_l]
        descriptions_l = []
    
        for dimension_id in dimensions_ids:
            chunk_paths = [main_url, 'codelist', agency_id, dimension_id, 'latest']  # PATCH_ISTAT_CONFORME_261027G
            endpoint_url = "/".join(chunk_paths)
            
            response = _istat_get(endpoint_url, verify=False)
            
            tree = ET.iterparse(io.StringIO(response.text))
            for _, el in tree:
                _, _, el.tag = el.tag.rpartition('}') # strip ns#
            root = tree.root
    
            descriptions = [x.findall('Name') for x in root.iter("Codelist")]
            # unlist nested lists
            descriptions = list(itertools.chain(*descriptions))
            descr = [x.text for x in descriptions]
          
            description_dict = {
                "dimension_ID": dimension_id,
                "description_EN": _istat_nome(root.find(".//Codelist"), "en"),  # PATCH_ISTAT_SENZABLOCCHI_261027F
                "description_IT": _istat_nome(root.find(".//Codelist"), "it"),
            }
            descriptions_l.append(description_dict)
    
        dimensions_descriptions = pd.DataFrame(descriptions_l)
        dimensions = pd.DataFrame(dimensions_l).merge(dimensions_descriptions, on="dimension_ID")

    
        # =====================================================================
        # GET VARIABLES' DESCRIPTION FROM EACH ARTEFACT_ID (BIG MATRIX)
        # =====================================================================
        
        resource = 'availableconstraint'
        # PATCH_ISTAT_CONFORME_261027G: /availableconstraint/{flowRef}/{key}/{providerRef}/{componentIds}
        chunks_path = [main_url, resource, num_id, 'all', 'all', 'all']
        endpoint_url = '/'.join(chunks_path) + '?references=all'
        
        # send the HTTP request
        response = _istat_get(endpoint_url, verify=False,headers={'Accept-Language':'it','User-Agent':'Mozilla/5.0'})
     
        tree = ET.iterparse(io.StringIO(response.text))
        for _, el in tree:
            _, _, el.tag = el.tag.rpartition('}') # strip ns#
        root = tree.root
        
        dimensions_values = {}
        senza_it = 0  # PATCH_ISTAT_CONFORME_261027G
    
        for dimension in root.iter("Codelist"):
            dimension_id = dimension.get("id")
    
            values = {}
            value_id_l, value_descr_l = [], []
    
            for value in dimension.iter("Code"):
                value_id = value.get("id")
                value_descr = _istat_nome(value, 'it')  # PATCH_ISTAT_SENZABLOCCHI_261027F: per lingua, non per posizione
                senza_it += value_descr is None  # PATCH_ISTAT_CONFORME_261027G
                value_id_l.append(value_id)
                value_descr_l.append(value_descr)
            
            values["values_ids"] = value_id_l
            values["values_description_IT"] = value_descr_l
            dimensions_values[dimension_id] = values

        if senza_it:  # PATCH_ISTAT_CONFORME_261027G
            log.warning(f'{ref_id}: {senza_it} codici senza descrizione italiana, *_DESC lasciata vuota')
        if not nome_it:  # PATCH_ISTAT_CONFORME_261027G
            log.warning(f'{ref_id}: dataflow senza nome italiano, NAME_ID_IT vuota')

        # PATCH_ISTAT_SENZABLOCCHI_261027F: completezza, righe scaricate contro osservazioni dichiarate da ISTAT
        obs_count = _istat_obs_count(root)
        if obs_count is not None and n_righe != obs_count:
            log.warning(f'{ref_id}: {n_righe} righe scaricate, {obs_count} osservazioni dichiarate da ISTAT')
        else:
            log.info(f'{ref_id}: {n_righe} righe scaricate (osservazioni dichiarate da ISTAT: {obs_count})')
    
    
        # =====================================================================
        # CHOOSE YOUR DIMENSION TO RETRIEVE SPECIFIC INFO ABOUT k-VARIABLE
        # =====================================================================
        
        for dim in dimensions.dimension:
  
            mask = dimensions[dimensions['dimension']==dim]['dimension_ID'].values[0]
            if mask in dimensions_values.keys():
                var_map = pd.DataFrame(dimensions_values[mask])
                var_map.columns = [dim, dim + '_DESC']
        
                try:
                    DSET = DSET.merge(var_map, on=dim, how='left')
                except ValueError:
                    var_map[var_map.columns[0]] = var_map[var_map.columns[0]].astype('int64')
                    DSET = DSET.merge(var_map, on=dim, how='left')
     
        # =====================================================================
        # TO PUT ALL TOGETHER
        #======================================================================
        
        DSET['NAME_ID_IT'] = nome_it  # PATCH_ISTAT_SENZABLOCCHI_261027F
        # PATCH_ISTAT_CONFORME_261027G: NAME_ID_EN tolta, tabelle solo in italiano
        DSET['NUM_ID']     = num_id
        DSET['REF_ID']     = ref_id
    
        # PATCH_ISTAT_RATELIMIT_261026: il .csv esiste solo a scrittura finita (serve alla ripresa)
        DSET.to_csv(f"{file_out}.csv.part", index=False, sep='|')
        os.replace(f"{file_out}.csv.part", f"{file_out}.csv")
            
    
    # PATCH_ISTAT_SALTA_261027H: i saltati senza CSV escono dal catalogo di questo snapshot
    fuori = [v for v in saltati if not os.path.exists(f"{fold_path}{v}.csv")]
    if fuori:
        log.critical(f'ISTAT: {len(fuori)} dataflow saltati e non presenti, tolti da info_ISTAT.json: {fuori}')
        DB_INFO = DB_INFO.loc[~DB_INFO['VAR_CODE'].isin(fuori)].reset_index(drop=True)
    # PATCH_ISTAT_RATELIMIT_261026: i dataflow non disponibili escono dal catalogo di questo snapshot
    if mancanti:
        log.critical(f'ISTAT: {len(mancanti)} dataflow non disponibili, tolti da info_ISTAT.json: {mancanti}')
        DB_INFO = DB_INFO.loc[~DB_INFO['VAR_CODE'].isin(mancanti)].reset_index(drop=True)
    log.info(f'ISTAT: {_istat_n[0]} richieste HTTP in questa esecuzione (dettaglio in {_ISTAT_REGISTRO})')

    # export info updated
    jhandler = jh.JsonHandler( file_tgt= file_in, encoding='utf-8')
    jhandler.json_writer(data=DB_INFO)
    
    progbar.close()
    log.info('success')   
