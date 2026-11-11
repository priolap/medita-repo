# -*- coding: utf-8 -*-
"""
Created on Tue Jun 13 14:39:57 2023
@author: paolap
"""

from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, Float, ForeignKey, Index
from sqlalchemy.orm import relationship

Base = declarative_base()

class Metadata(Base):
    __tablename__ = 'metadata'
    
    ID = Column(Integer, primary_key=True)
    FILE_NAME = Column(String)
    VAR_NAME = Column(String)
    VAR_CODE = Column(String)
    TAG = Column(String, nullable=False)
    DESC = Column(String)
    source = Column(String, nullable=False)
    permalink = Column(String)          
    download_link = Column(String)
    url = Column(String)                
    file_in = Column(String)
    file_out = Column(String)
    EXT_TYPE = Column(String)
    data_format = Column(String)        
    last_update = Column(String)
    encoding = Column(String)
    delimiter = Column(String)
    sheets = Column(String)
    outcome = Column(String)
    last_pars = Column(String)
    parsing = Column(String)
    admin_info = Column(String)         
    topics = Column(String)             
    update_frequency = Column(String)   
    last_meta_mod = Column(String)      
    last_update_source = Column(String) 
    loading_date = Column(String)       
    urn = Column(String)

# class Metadata(Base):
#     __tablename__ = 'metadata'
#     ID = Column(Integer, primary_key=True)
#     FILE_NAME = Column(String)
#     VAR_NAME = Column(String)
#     VAR_CODE = Column(String)
#     TAG = Column(String, nullable=False)
#     DESC = Column(String)
#     source = Column(String, nullable=False)
#     url_dset = Column(String)
#     download_link = Column(String)
#     url_pdf = Column(String)
#     file_in = Column(String)
#     file_out = Column(String)
#     EXT_TYPE = Column(String)
#     last_update = Column(String)
#     encoding = Column(String)
#     delimiter = Column(String)
#     sheets = Column(String)
#     outcome = Column(String)
#     last_pars = Column(String)
#     parsing = Column(String)
#     email_admin = Column(String)
#     urn = Column(String)
   