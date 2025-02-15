import os
import platform
from datetime import datetime as dt
import time
from concurrent.futures import ThreadPoolExecutor as PoolExecutor

from json2args import get_parameter
from json2args.logger import logger
from dotenv import load_dotenv
from metacatalog import api
from tqdm import tqdm

from param import load_params
from loader import load_entry_data
from utils import reference_area_to_file
from version import __version__

# always load .env files
load_dotenv()

# parse parameters
kwargs = get_parameter()

# check if a toolname was set in env
toolname = os.environ.get('TOOL_RUN', 'vforwater_loader').lower()

# raise an error if the toolname is not valid
if toolname != 'vforwater_loader':
    raise AttributeError(f"[{dt.now().isocalendar()}] Either no TOOL_RUN environment variable available, or '{toolname}' is not valid.\n")

# use the pydantic model to handle the input parameters
params = load_params(**kwargs)   

# check if a connection evironment variable is given
if 'VFW_POSTGRES_URI' in os.environ:
    connection = os.environ['VFW_POSTGRES_URI']
elif 'METACATALOG_URI' in os.environ:
    connection = os.environ['METACATALOG_URI']
else:
    connection = None

# if we could not derive a connection, we hope for the best and hope that
# defaults are used
session = api.connect_database(connection)

# initialize a new log-file by overwriting any existing one
# build the message for now
MSG = f"""\
This is the V-FOR-WaTer data loader report

The loader version is: {__version__} (Python: {platform.python_version()})
Running on: {platform.platform()}
The following information has been submitted to the tool:

START DATE:         {params.start_date}
END DATE:           {params.end_date}
REFERENCE AREA:     {params.reference_area is not None}
CELL TOUCHES:       {params.cell_touches}

DATASET IDS:
{', '.join(map(str, params.dataset_ids))}

DATABASE CONNECTION: {connection is not None}
DATABASE URI:        {session.bind}

Processing logs:
----------------
"""
with open('/out/processing.log', 'w') as f:
    f.write(MSG)

# Here is the actual tool
# --------------------------------------------------------------------------- #
# mark the start of the tool
logger.info("##TOOL START - Vforwater Loader")
tool_start = time.time()

# debug the params before we do anything with them
#logger.debug(f"JSON dump of parameters received: {params.model_dump_json()}")

# save the reference area to a file for later reuse
if params.reference_area is not None:
    reference_area = reference_area_to_file()

# load the datasets
# save the entries and their data_paths for later use
file_mapping = []
with PoolExecutor() as executor:
    logger.debug(f"START {type(executor).__name__} - Pool to load and clip data source files.")
    logger.info(f"A total of {len(params.dataset_ids)} are requested. Start loading data sources.")
    
    for dataset_id in tqdm(params.dataset_ids):
        try:
            entry = api.find_entry(session, id=dataset_id, return_iterator=True).one()
            
            # load the entry and return the data path
            data_path = load_entry_data(entry, executor)

            # if data_path is None, we skip this step
            if data_path is None:
                logger.error(f"Could not load data for dataset <ID={dataset_id}>. The content of '/out/datasets' might miss something.")
                continue

            # save the mapping from entry to data_path
            file_mapping.append({'entry': entry, 'data_path': data_path})
        except Exception as e:
            logger.exception(f"ERRORED on dataset <ID={dataset_id}>.\nError: {str(e)}")
            continue
    
    # wait until all results are finished
    executor.shutdown(wait=True)
    logger.info(f"STOP {type(executor).__name__} - Pool finished all tasks and shutdown.")

# we're finished.
t2 = time.time()
logger.info(f"Total runtime: {t2 - tool_start:.2f} seconds.")
logger.info("##TOOL FINISH - Vforwater Loader")

# print out the report
with open('/out/processing.log', 'r') as f:
    print(f.read())

