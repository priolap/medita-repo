import pandas as pd
import json, re
# import ORM models
from sqlalchemy.ext.declarative import DeclarativeMeta
from dashboard.models import models
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError
from dashboard.models.relations import Metadata, Base
from sqlalchemy import inspect, Table, Column, Integer, String, Float, MetaData

# =============================================================================
def load_json( file_path):
    with open(file_path, 'r', encoding = 'utf-8') as file:
        return json.load(file)
    
def create_table(model_class, engine):
    """Creates a table based on the given SQLAlchemy model class."""
    with engine.connect() as connection:
        model_class.__table__.create(connection, checkfirst=True)

# def create_table( model_class, engine):
#     """ Creates a table based on the given SQLAlchemy model class. """
#     model_class.__table__.create(bind=engine, checkfirst=True)
    
def timeseries_keys( columns, *args):
    for possible_column in args:
        if possible_column in columns:
            return possible_column
    return None
    
def get_model_class( table_name):
    """ Returns the model class for a given table name."""
    # Check if the attribute exists in models and is a SQLAlchemy model
    model_class = getattr(models, table_name, None)
    if isinstance(model_class, DeclarativeMeta):
        return model_class
    else:
        return None
 
def integrity_models_check( model_class, df ,engine):
    """ Validates if the model's columns and the DataFrame's columns match. """
    model_columns = {c.key for c in inspect(model_class).mapper.column_attrs}
    df_columns = set(df.columns)

    extra_df_columns = df_columns - model_columns
    df_columns.add('ID') # add ID to avoid the log
    missing_df_columns = model_columns - df_columns
    
    mess = "Integrity check: success"
    if extra_df_columns:
        mess = f"DataFrame contains extra columns not in model: {extra_df_columns}"
    if missing_df_columns:
        mess = f"Model contains columns not present in DataFrame: {missing_df_columns}"
        
    return mess

def insert_data(model_class, data, engine, log, batch_size=1000):
    """Inserts data into the table based on the given SQLAlchemy model class."""
    
    # Convert the DataFrame into a list of dictionaries
    records = data.to_dict(orient='records')
   
    mess = integrity_models_check(model_class, data, engine)
    log.debug(mess)
    
    try:
        # Use a session with the engine directly
        with Session(engine) as session:
            for i in range(0, len(records), batch_size):
                # Process in batches
                batch = records[i:i + batch_size]
                session.bulk_insert_mappings(model_class, batch)
                session.commit()    
        
    except SQLAlchemyError as e:
        log.error(f"Error during bulk insert: {e}")
        
    return log
          
# def insert_data( model_class, data, engine, log, batch_size=1000):
#     """ Inserts data into the table based on the given SQLAlchemy model class."""
    
#     Session = sessionmaker(bind=engine)
#     # Convert the DataFrame into a list of dictionaries
#     records = data.to_dict(orient='records')
   
#     mess = integrity_models_check( model_class, data,engine )
#     log.debug(mess)
    
#     try:
#         with Session() as session:
#             for i in range(0, len(records), batch_size):
#                 # Process in batches
#                 batch = records[i:i + batch_size]
#                 session.bulk_insert_mappings(model_class, batch)
#                 session.commit()    
        
#     except SQLAlchemyError as e:
#         log.error(f"Error during bulk insert: {e}")
        
#     return log

def generate_metadata_df(sourcelist, path):
    sources = []
    dfmeta = pd.DataFrame()
    
    for outer_key, inner_dict in sourcelist.items():
         for key in inner_dict.keys():
             sources.append(key)
             if key in ['AIFA','MINIS','ISTAT']:
                 key_path = f"{path}config/info_{key}.json"
                 with open(key_path, 'r', encoding='utf-8') as file:
                     key_metadata = pd.DataFrame(json.load(file))
                     key_metadata['source'] = key
                 # Append/concatenate the current DataFrame to the merged DataFrame
                 dfmeta = pd.concat([dfmeta, key_metadata], ignore_index=True)
                
    # converting a single column that contains lists to a string representation
    for c in dfmeta.columns:
        # Check if the first element of each column is a list
        if isinstance(dfmeta[c].dropna().iloc[0], list):
            # Convert the whole column to JSON strings if the first element is a list
            dfmeta[c] = dfmeta[c].apply(lambda x: json.dumps(x) if isinstance(x, list) else x)
            # dfmeta['file_in'] = dfmeta['file_in'].apply(lambda x: json.dumps(x) if isinstance(x, list) else x)
     
    return dfmeta, sources

def populate_metadata_table(df, engine, log):
    """Populates the Metadata table with data from the DataFrame."""
    # Reflect the existing database into a new MetaData instance without binding
    metadata = MetaData()
    
    # Use an explicit connection for reflection
    with engine.connect() as connection:
        metadata.reflect(bind=connection)
    
        # Check if the 'metadata' table exists
        if inspect(connection).has_table('metadata'):  # Adjust case to match your table name
            # Drop the 'metadata' table
            metadata.tables['metadata'].drop(connection)

    # After dropping the table (if it existed), recreate all tables based on the Base model
    Base.metadata.create_all(engine)

    # Start a session with the engine directly
    with Session(engine) as session:
        if df.empty:
            log.error("No data to populate the Metadata table.")
            return
        
# def populate_metadata_table(df, engine, log):
#     """Populates the Metadata table with data from the DataFrame."""
#     # Reflect the existing database into a new MetaData instance
#     metadata = MetaData()
#     metadata.reflect(engine)
    
#     # Check if the 'metadata' table exists
#     if inspect(engine).has_table('metadata'):  # Use the correct case for your table name
#         # Drop the 'metadata' table
#         metadata.tables['metadata'].drop(engine)
#     # After dropping the table (if it existed), recreate all tables based on the Base model
#     Base.metadata.create_all(engine)

#     # Start a session
#     Session = sessionmaker(bind=engine)
#     session = Session()

#     if df.empty:
#         log.error("No data to populate the Metadata table.")
#         return
      

    # Iterate through each row in the DataFrame and add it to the 'metadata' table
    for _, row in df.iterrows():
        new_entry = Metadata(
            FILE_NAME           = row['FILE_NAME'],
            VAR_NAME            = row['VAR_NAME'],
            VAR_CODE            = row['VAR_CODE'],
            TAG                 = row['TAG'],
            DESC                = row['DESC'],  
            source              = row['source'],
            permalink           = row['permalink'],
            download_link       = row['download_link'],
            url                 = row['url'],
            file_in             = row['file_in'],
            file_out            = row['file_out'],
            EXT_TYPE            = row['EXT_TYPE'],
            data_format         = row['data_format'],
            last_update         = row['last_update'],
            encoding            = row['encoding'],
            delimiter           = row['delimiter'],
            sheets              = row['sheets'],
            outcome             = row['outcome'],
            last_pars           = row['last_pars'],
            parsing             = row['parsing'],
            admin_info          = row['admin_info'],
            topics              = row['topics'],
            update_frequency    = row['update_frequency'],
            last_meta_mod       = row['last_meta_mod'],
            last_update_source  = row['last_update_source'],
            loading_date        = row['loading_date'],
            urn                 = row.get('urn')  # get for missing/optional
        )
        session.add(new_entry)

    # Commit the changes to the database
    session.commit()
    session.close()

def create_table_from_dataframe(table_name, df, eng):
    """
    Creates a table in the database based on the structure of the provided DataFrame,
    with 'REGIONE' and 'ANNO' as a composite primary key.
    """
    # Initialize metadata without binding to the engine
    metadata = MetaData()
    columns = []

    # Loop through each column in the DataFrame
    for idx, dtype in enumerate(df.dtypes):
        col_name = df.dtypes.index[idx]

        # Determine the SQLAlchemy type for the column based on the dtype
        if re.search(r'int(32|64)', str(dtype)):
            col_type = Integer
        elif re.search(r'float(32|64)', str(dtype)):
            col_type = Float
        else:
            col_type = String
        
        # Check if the column should be part of the primary key
        if col_name in ['REGIONE', 'ANNO']:
            columns.append(Column(col_name, col_type, primary_key=True))
        else:
            columns.append(Column(col_name, col_type))

    # Define the table with the dynamically created columns
    new_table = Table(table_name, metadata, *columns)
    
    # Create the table in the database using a connection
    with eng.connect() as connection:
        metadata.create_all(connection)

    return new_table
       
# def create_table_from_dataframe( table_name, df, eng):
#     """
#     Creates a table in the database based on the structure of the provided DataFrame,
#     with 'REGIONE' and 'ANNO' as a composite primary key.
#     """
#     metadata = MetaData(bind=eng)
#     columns = []

#     # Loop through each column in the DataFrame
#     for idx, dtype in enumerate(df.dtypes):
#         col_name = df.dtypes.index[idx]

#         # Determine the SQLAlchemy type for the column based on the dtype
#         if re.search(r'int(32|64)', str(dtype)):
#             col_type = Integer
#         elif re.search(r'float(32|64)', str(dtype)):
#             col_type = Float
#         else:
#             col_type = String
        
#         # Check if the column should be part of the primary key
#         if col_name in ['REGIONE', 'ANNO']:
#             columns.append(Column(col_name, col_type, primary_key=True))
#         else:
#             columns.append(Column(col_name, col_type))

#     # Define the table with the dynamically created columns
#     new_table = Table(table_name, metadata, *columns)
#     # Create the table in the database
#     metadata.create_all()

#     return new_table

def create_orm_model( table, base):
   """
   Dynamically create an ORM model class for the given table.
   """
   attributes = {"__tablename__": table.name}

   # Loop over the columns in the table
   for column in table.columns:
       # Check the type of each column and create a new Column of the same type
       if isinstance(column.type, Integer):
           col_type = Integer
       elif isinstance(column.type, String):
           col_type = String
       else:
           # fallback to the actual type of the column
           col_type = type(column.type)  

       # Create a new Column object with the same name and type
       # If the column is part of the primary key, preserve that information
       attributes[column.name] = Column(column.name, col_type, primary_key=column.primary_key)

   # Create the new class dynamically
   DynamicModel = type("DynamicModel", (base,), attributes)

   return DynamicModel

# =============================================================================
# AGGREGATING DATA
# =============================================================================

