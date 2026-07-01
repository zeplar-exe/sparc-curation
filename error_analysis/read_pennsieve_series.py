import json
from collections import Counter, defaultdict
from typing import Any

IN = "./pennsieve-event-data-2026-05-12T020310Z.json"
OUT = "./pennsieve_event_series.json"

with open(IN, "r", encoding="utf-8") as f:
    data = json.load(f)

sequences = defaultdict(list)

REQUEST_TYPES = {"REQUEST_PUBLICATION", "REQUEST_EMBARGO"}
ACCEPT_TYPES = {"ACCEPT_PUBLICATION", "ACCEPT_EMBARGO"}
FILTER_TYPES = REQUEST_TYPES | ACCEPT_TYPES | {
    "REJECT_PUBLICATION",
    "CANCEL_PUBLICATION",
    "REJECT_EMBARGO",
    "CANCEL_EMBARGO",
}

for dataset_id, event_data in data.items():
    event_groups = event_data["eventGroups"]

    events: list[list[Any]] = [ev.get("events", [ev.get("event")]) for ev in event_groups]
    flat_events = sorted(
        (ev for sub in events for ev in sub if ev["eventType"] in FILTER_TYPES),
        key=lambda ev: ev["createdAt"],
    )

    cycles: list[dict] = []
    collected: list = []
    request_created = None
    accept_created = None

    def finalize(incomplete: bool):
        global collected, request_created, accept_created
        if collected:
            cycles.append({
                "incomplete": incomplete,
                "request_created": request_created,
                "accept_created": accept_created,
                "frequencies": dict(Counter(ev["eventType"] for ev in collected)),
                "length": len(collected),
                "events": list(reversed(collected)),
            })
        collected = []
        request_created = None
        accept_created = None

    for ev in flat_events:
        et = ev["eventType"]
        collected.append(ev)

        if et in REQUEST_TYPES:
            # Keep the earliest request
            if request_created is None:
                request_created = ev["createdAt"]
        elif et in ACCEPT_TYPES:
            accept_created = ev["createdAt"]
            finalize(incomplete=request_created is None)
    
    if request_created is not None:
        finalize(incomplete=True)

    sequences[dataset_id] = cycles

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(sequences, f, indent=2)

print(f"Wrote {len(sequences)} dataset sequence sets to {OUT}")