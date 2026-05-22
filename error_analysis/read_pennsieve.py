import json
from collections import Counter, defaultdict
from typing import Any

IN = "./pennsieve-event-data-2026-05-12T020310Z.json"
OUT = "./pennsieve_event_series.json"

with open(IN, "r", encoding="utf-8") as f:
    data = json.load(f)

sequences = defaultdict(list)

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
        
        if et == "ACCEPT_PUBLICATION":
            if last_request_index is None and last_accept_index is not None:
                collected.extend(buffer[:-1])
                finalize(True)
            
            if last_request_index is not None and last_accept_index is not None:
                finalize(False)
            
            buffer = [ev]
            
            last_accept_index = i
            created_accept = ev["createdAt"]
        
        if et == "REQUEST_PUBLICATION":
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