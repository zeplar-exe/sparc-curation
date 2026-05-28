import json
from collections import Counter, defaultdict
from typing import Any

IN = "./pennsieve-event-data-2026-05-12T020310Z.json"
OUT = "./pennsieve_event_series.json"

with open(IN, "r", encoding="utf-8") as f:
    data = json.load(f)

sequences = defaultdict(list)

# need to do a test to make sure that multi-accept-publications are read correctly, 
# and that incomplete sequences are marked as such. Also need to check that 
# request-accept-embargo sequences are read correctly.
# also remind alec to catch you up on the metadata project

# ALSO: we can finally read curation touches: get batches of events that happen 
# within ~2 hours between UPDATE_STATUS events that change to 
# status 5, 6, 7, or 8 (I think, need to go check); keep track of the number of batches, 
# and the number of events in each batch, and the types of events in each batch (Counter). 
# AI: "This will give us a sense of how much curation activity is happening, and what 
# kinds of things curators are doing."
# Plus store the start/end timestamps of each batch
# Make sure it's one of the following userId: 
# Tom 589  Anka 832  Anka alt unused 1554  Marlena 1186
# extras: Anita 531  Jeff 600  Jeff (ncmir) 601  Maryann 611 (edited) 

# so we really just care about:
# DONE: how many batches per publication (box plot and scatterplot)
# DONE: how many events per batch (box plot and scatterplot)
# EXTRANEOUS: what types of events are in each batch (Counter) (stacked bar chart of event types per batch, maybe normalized by batch size)
# EXTRANEOUS: time between batches (box plot)
# DEAD: specific events that consistently occur (matched on type and properties); for ex: [CREATE_MODEL].detail.name

for dataset_id, event_data in data.items():
    event_groups = event_data["eventGroups"]
    
    collected = []
    last_request_index = None
    last_accept_index = None
    created_request = None
    created_accept = None
    
    def finalize(incomplete: bool):
        global collected, last_request_index, last_accept_index, created_request, created_accept
        collected = list(reversed(collected))
        counts = Counter()
        
        for ev in collected:
            counts[ev["eventType"]] += 1
        
        sequences[dataset_id].append({
            "incomplete": incomplete,
            "request_created": created_request,
            "accept_created": created_accept,
            "frequencies": dict(counts),
            "length": len(collected),
            "events": collected,
        })
        last_request_index = None
        last_accept_index = None
        created_request = None
        created_accept = None
        collected = []
    
    filter_types = [
        "ACCEPT_PUBLICATION",
        "REQUEST_PUBLICATION",
        "REJECT_PUBLICATION",
        "CANCEL_PUBLICATION",
        "ACCEPT_EMBARGO",
        "REJECT_EMBARGO",
        "CANCEL_EMBARGO",
        "REQUEST_EMBARGO"
    ]
    
    buffer = []
    events: list[list[Any]] = [ev.get("events", [ev.get("event")]) for ev in event_groups]
    flat_events = [ev for sub in events for ev in sub if ev["eventType"] in filter_types]
    
    for i, ev in enumerate(flat_events):
        et = ev["eventType"]
        
        buffer.append(ev)
        
        if et == "ACCEPT_PUBLICATION" or et == "REQUEST_EMBARGO":
            if last_request_index is None and last_accept_index is not None:
                collected.extend(buffer[:-1])
                finalize(True)
            
            if last_request_index is not None and last_accept_index is not None:
                finalize(False)
            
            buffer = [ev]
            
            last_accept_index = i
            created_accept = ev["createdAt"]
        
        if et == "REQUEST_PUBLICATION" or et == "ACCEPT_EMBARGO":
            last_request_index = i
            collected.extend(buffer)
            buffer = []
            created_request = ev["createdAt"]
    
    incomplete = not (last_request_index is not None and last_accept_index is not None)
    if incomplete:
        collected.extend(buffer)
    finalize(incomplete)

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(sequences, f, indent=2)

print(f"Wrote {len(sequences)} dataset sequence sets to {OUT}")