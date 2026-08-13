import json
from collections import Counter, defaultdict
from typing import Any

IN = "./pennsieve-event-data-2026-05-12T020310Z.json"
OUT = "./pennsieve_status_delimited.json"

with open(IN, "r", encoding="utf-8") as f:
    data = json.load(f)

all_events = defaultdict(list)

relevant_users = [
    589, # Tom
    832, # Anka
    1554, # Anka alt unused
    1186, # Marlena
    # 531, # Anita
    # 600, # Jeff
    601, # Jeff (ncmir)
    # 611, # Maryann
]

for dataset_id, event_data in data.items():
    event_groups = event_data.get("eventGroups", [])
    events = [ev.get("events", [ev.get("event")]) for ev in event_groups]
    flat_events = [ev for sub in events for ev in sub if ev.get("userId") in relevant_users]
    
    all_events[dataset_id] = sorted(flat_events, key=lambda ev: ev["createdAt"])

sequences = defaultdict(list)

for dataset_id, events in all_events.items():
    collected = []
    
    for event in events:
        et = event["eventType"]
        if et == "UPDATE_STATUS":
            if collected:
                collected.append(event)
                sequences[dataset_id].append(collected)
            collected = [event]
        else:
            collected.append(event)

    if collected:
        sequences[dataset_id].append(collected)

target_stati = [
    4, # 03
    5, # 04_CURATION_IN_PROGRESS_CURATORS
    6, # 05_CURATION_IN_PROGRESS_MBF_CURATORS
    7, # 06_MBF_CURATION_COMPLETE_CURATORS
    8, # 07_CURATION_IN_PROGRESS_SCAFFOLD_REGISTRATION_CURATORS
    9, # 08_SCAFFOLD_REGISTRATION_COMPLETE_CURATORS
    10, # "09_NEEDS_ATTENTION_CURATORS"
]

output_sequences = defaultdict(list)

for dataset_id, dataset_sequences in sequences.items():
    for sequence in dataset_sequences:
        if not sequence[0]["eventType"] == "UPDATE_STATUS":
            continue
        
        if sequence[0]["detail"]["newStatus"]["id"] not in target_stati:
            continue
        
        output = []
        
        for event in sequence:
            detail = event["detail"]
            et = event["eventType"]
            event_message = ""
            
            if et == "ADD_CONTRIBUTOR" or et == "REMOVE_CONTRIBUTOR":
                event_message = f"{et}: {detail['firstName']} {detail['lastName']})"
            elif et in ["CREATE_PACKAGE", "DELETE_PACKAGE", "CREATE_RECORD", "CREATE_MODEL", "ADD_TAG", "REMOVE_TAG", "DELETE_RECORD", "MOVE_PACKAGE", "RESTORE_PACKAGE", "UPDATE_RECORD", "ADD_COLLECTION"]:
                event_message = f"{et}: {detail['name']}"
            elif et in ["CREATE_MODEL_PROPERTY"]:
                event_message = f"{et}: {detail['modelName']}.{detail['propertyName']})"
            elif et in ["RENAME_PACKAGE"]:
                event_message = f"{et}: {detail['oldName']} -> {detail['newName']}"
            elif et == "UPDATE_STATUS":
                event_message = f"{et}: {detail['oldStatus']['name']} -> {detail['newStatus']['name']}"
            else:
                event_message = et
            
            output.append({
                "type": et,
                "event": event_message,
                "createdAt": event["createdAt"],
                "userId": event["userId"],
            })
        
        output_sequences[dataset_id].append(output)
            

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(output_sequences, f, indent=2)
