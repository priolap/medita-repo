# -*- coding: utf-8 -*-
"""
Created on Mon Jul 24 13:30:14 2023

@author: paolap
"""

import logging

def Logger(log_file=None, log_level=None):

    # create a custom logging format with specific columns
    # I want: datetime | [INFO, DEBUG, CRITICAL] | [function name] | message
    log_format = '%(asctime)s | %(levelname)s | %(funcName)s | %(message)s'

    # set up the logging configuration
    logging.basicConfig(
        level=log_level,
        format=log_format
    )

    # custom formatter for the log with the required fields
    custom_formatter = logging.Formatter(log_format)

    # create a new logger
    logger = logging.getLogger()

    # clear any existing handlers to avoid duplicate logs
    logger.handlers.clear()

    # create a new stream handler with the custom formatter
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(custom_formatter)

    # add the stream handler to the logger
    logger.addHandler(stream_handler)

    if log_file:
               
        # create a new file handler with the custom formatter
        file_handler = logging.FileHandler(log_file, mode='w')
        file_handler.setFormatter(custom_formatter)

        # add the file handler to the logger
        logger.addHandler(file_handler)

    return logger
