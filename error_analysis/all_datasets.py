import csv
import datetime
import json
from collections import Counter, defaultdict

import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

EXCLUDED_DATASET_IDS = []
WHITELIST_DATASET_IDS = []

# we should look over the categorization code; particularly metadata and add/remove_contributor
# what about styling by the way?
# metadata type mix: would be helpful to havae n=X metrics per year; same for event mix

# also need to ask: is my collect() function double counting?


# + ignore all errors that path from #/inputs/
# + need to separate errors by path
    # + put the last two errors in dropped_errors.txt into the slack under no idea
    # + errors that don't have a path?
    # + null path errors get grouped under "this occured with no path"
# + exclude all missing required tsrXb_ABC errors

# + april 1st 2022 - april 1st 2026 for errors
    # check if this loses events
# + make a table of errors X datasets; 1 or 0 on existence to make a frequency table
    # separate datasets by template version when we add that data...
    
# should I remove dataset/org ids from the files? for OSINT purposes?

with open("./dataset_exclusion_list.csv") as f:
    for row in csv.DictReader(f):
        EXCLUDED_DATASET_IDS.append(row["Dataset ID"])

with open("./big-did.json") as f:
    SPARC_ORGANIZATION = "organization:618e8dd9-f8d2-4dc4-9abb-c6aaab2e78a0"
    
    data = json.load(f)
    for id, entry in data.items():
        if entry["id_organization"] == SPARC_ORGANIZATION:
            WHITELIST_DATASET_IDS.append(id)

w = csv.DictWriter(open("./all_included_datasets.csv", "w"), fieldnames=["Dataset ID"])

for id in WHITELIST_DATASET_IDS:
    if id not in EXCLUDED_DATASET_IDS:
        w.writerow({"Dataset ID": id})
        
        
# curation start date as determined by update_status
# also: curation start date as determined by request_publication
# also: curation start date as determined by curator first touch
# include span days for all of the above
# include number of publications
# include req/publication date for each differnet publication


# get curation export at request and provide link
# get curation export at publish and provide link

# the full list is available in the google drive under XXX_matrix_table.xlsx