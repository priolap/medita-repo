import json
import os
import pandas as pd

def numbers_dtypes(home, log, tod):
    # Exclusions of known attributes
    cols_exclusions = [
        'ANNO', 'PARTITA_IVA', 'LONGITUDINE', 'LATITUDINE', 'TIPO_AZIENDA', 
        'NDEG', 'STATO_LOCALIZZAZIONE', 'PRECEDENTE_BOLLO_CEE', 'SUBCODICE',
        'DM_RIFERIMENTO', 'TIPOLOGIA_DM', 'LOCALIZZAZIONE', 'GRUPPO_DM_SIMILI',
        'NUM_REPERTORIO'
    ]
    
    # Columns with specific starting patterns to exclude
    excluded_prefixes = ('MESE', 'PROGRESSIVO', 'CODICE', 'CAP', 'SOTTOTIPO', 'COD')

    # Paths
    json_file_path = f"{home}/config/cols_attributes.json" 
    output_json_path = f"{home}/config/missing_numeric_attributes_{tod}.json"

    # Step 1: Read JSON configuration
    with open(json_file_path, 'r', encoding='ISO-8859-1') as file:
        json_data = json.load(file)
        
    # Extract expected numeric columns from JSON
    numeric_columns_in_json = set()
    for entry in json_data:
        if entry['dtype'] == 'numeric':
            name_in_variants = entry['name_in'].split('|')
            numeric_columns_in_json.update(name_in_variants)
            
    # Check if the folder for the date exists; otherwise, get the latest folder
    if not os.path.exists(f"{home}/data/output/MINIS/{tod}"):
        base_path = f"{home}/data/output/MINIS"
        folders = [f for f in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, f))]
        date_folders = [f for f in folders if f.isdigit() and len(f) == 8]
        date_folders.sort(reverse=True)
        data_folder_path = os.path.join(base_path, date_folders[0])
    else:
        data_folder_path = f"{home}/data/output/MINIS/{tod}"
    
    data_files = [f for f in os.listdir(data_folder_path) if os.path.isfile(os.path.join(data_folder_path, f))]

    # Step 3: Check each file's numeric columns against JSON configuration
    missing_columns_data = []

    for file in data_files:
        print(f"Processing file: {file}")
        df = pd.read_csv(f"{data_folder_path}/{file}", sep='|')
        
        # Extract var_code from the file name
        var_code = os.path.splitext(file)[0]
        
        # Identify numeric columns in the DataFrame
        numeric_columns_in_file = set(df.select_dtypes(include=['number']).columns)
        
        # Apply exclusions: remove excluded columns and those with specific prefixes
        filtered_numeric_columns = {
            col for col in numeric_columns_in_file 
            if col not in cols_exclusions and not col.startswith(excluded_prefixes)
        }
        
        # Find missing columns by comparing with JSON numeric columns
        missing_numeric_columns = filtered_numeric_columns - numeric_columns_in_json
        
        if missing_numeric_columns:
            for col in missing_numeric_columns:
                # Guess `conversion` type based on column name patterns
                if 'TASSO' in col.upper():
                    conversion = 'avg'
                elif col.upper().startswith('NUM'):
                    conversion = 'sum'
                elif col.upper().startswith('TOTALE'):
                    conversion = 'sum'
                else:
                    conversion = 'sum'  # Default guess
                
                # Infer `is_obs` based on column naming conventions
                is_obs = True
                
                # Get an example value from the column
                example_value = df[col].dropna().iloc[0] if not df[col].dropna().empty else None
                
                # Append data to missing_columns_data
                missing_columns_data.append({
                    "name_out": col,
                    "name_in": col,
                    "is_obs": is_obs,
                    "dtype": "numeric",
                    "conversion": conversion,
                    "example_value": example_value,
                    "var_code": var_code
                })
    
    # Convert to DataFrame
    missing_columns_df = pd.DataFrame(missing_columns_data)

    # Drop duplicates
    missing_columns_df = missing_columns_df.drop_duplicates(subset=["var_code", "name_out"])

    # Export DataFrame to JSON
    missing_columns_df.to_json(output_json_path, orient='records', indent=4, force_ascii=False)

    log.debug(f"Summary of missing columns exported to {output_json_path}")
    
    return log
