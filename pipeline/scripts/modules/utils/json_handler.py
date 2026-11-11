# -*- coding: utf-8 -*-
"""
Created on Tue Jul 25 12:49:40 2023

@author: paolap
"""

import json
import pandas as pd

class JsonHandler:
    def __init__(self, file_tgt, encoding):
        self.file_tgt = file_tgt
        self.encoding = encoding

    def json_reader(self):
        
        try:
            with open(self.file_tgt, 'r', encoding=self.encoding) as file:
                data = json.load(file)
                data = pd.DataFrame(data)
            return data

        except UnicodeDecodeError as e:
            print(f"Error: Unable to decode the file using encoding '{self.encoding}'.")
            print(str(e))
            return None

        except FileNotFoundError:
            print(f"Error: File '{self.file_tgt}' not found.")
            return None

        except json.JSONDecodeError as e:
            print("Error: JSON decoding failed. Check the JSON file for errors.")
            print(str(e))
            return None

    def json_writer(self, data):

        try:
            # Convert DataFrame to list of dictionaries
            df_dict_list = data.to_dict(orient='records')

            # Convert the list of dictionaries to JSON
            json_data = json.dumps(df_dict_list, ensure_ascii=False,indent=4)

            # Write the JSON data to the file
            with open(self.file_tgt, 'w', encoding=self.encoding) as json_file:
                json_file.write(json_data)

            print(f"Data exported to {self.file_tgt}")

        except Exception as e:
            print(f"Error: Unable to write data to file '{self.file_tgt}'.")
            print(str(e))