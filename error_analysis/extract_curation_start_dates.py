import csv
import json

from report_common import is_excluded_dataset, parse_iso8601

EVENT_SEQUENCES = "./pennsieve_event_series.json"
STATUS_DELIMITED = "./pennsieve_status_delimited.json"
RAW_EVENTS = "./pennsieve-event-data-2026-05-12T020310Z.json"
OUT = "./curation_start_dates.csv"

CURATOR_IDS = {
    # 589,
    832,
    1554,
    1186,
    # 531,
    # 600,
    # 601,
    # 611
}


def main():
    with open(EVENT_SEQUENCES) as f:
        event_sequences = json.load(f)
    with open(STATUS_DELIMITED) as f:
        status_delimited = json.load(f)
    with open(RAW_EVENTS) as f:
        raw_events = json.load(f)

    events_by_dataset = {}
    for dataset_id, sequences in status_delimited.items():
        events = []
        for sequence in sequences:
            for event in sequence:
                raw = event.get("createdAt")
                dt = parse_iso8601(raw)
                if dt:
                    events.append((dt, event.get("type"), event.get("event", ""), raw))
        events.sort(key=lambda e: e[0])
        events_by_dataset[dataset_id] = events
    
    curator_touches_by_dataset = {}
    for dataset_id, event_data in raw_events.items():
        touches = []
        for group in event_data.get("eventGroups", []):
            for event in group.get("events", [group.get("event")]):
                if not event or event.get("userId") not in CURATOR_IDS:
                    continue
                raw = event.get("createdAt")
                dt = parse_iso8601(raw)
                if dt:
                    touches.append((dt, raw))
        touches.sort(key=lambda t: t[0])
        curator_touches_by_dataset[dataset_id] = touches
    del raw_events

    rows = []
    for dataset_id, cycles in event_sequences.items():
        if is_excluded_dataset(dataset_id):
            continue

        pubs = []
        for cycle in cycles[:1]: # limit to first cycle
            accept = parse_iso8601(cycle.get("accept_created"))
            if accept is None:
                continue
            pubs.append((accept, cycle.get("accept_created"), cycle.get("request_created")))
        pubs.sort(key=lambda p: p[0])

        dataset_events = events_by_dataset.get(dataset_id, [])
        dataset_touches = curator_touches_by_dataset.get(dataset_id, [])

        for i, (accept, accept_raw, request_raw) in enumerate(pubs):
            previous_accept = pubs[i - 1][0] if i > 0 else None

            def in_window(dt):
                return (previous_accept is None or dt > previous_accept) and dt < accept

            # 1. first UPDATE_STATUS transitioning into 04_CURATION_IN_PROGRESS_CURATORS
            update_status = ""
            for dt, event_type, event_str, raw in dataset_events:
                if (
                    event_type == "UPDATE_STATUS"
                    and event_str.endswith("-> 04_CURATION_IN_PROGRESS_CURATORS")
                    and in_window(dt)
                ):
                    update_status = raw
                    break

            # 2. first curator action of any kind in the window (raw event stream)
            curator_touch = ""
            for dt, raw in dataset_touches:
                if in_window(dt):
                    curator_touch = raw
                    break

            # 3. the request that opened this cycle (if it falls in the window)
            request = parse_iso8601(request_raw)
            request_publication = request_raw if (request is not None and in_window(request)) else ""

            rows.append({
                "dataset_id": dataset_id,
                "publication_date": accept_raw,
                "curation_start_update_status": update_status,
                "curation_start_request_publication": request_publication,
                "curation_start_curator_first_touch": curator_touch,
            })

    rows.sort(key=lambda r: (r["dataset_id"], r["publication_date"]))

    fieldnames = [
        "dataset_id",
        "publication_date",
        "curation_start_update_status",
        "curation_start_request_publication",
        "curation_start_curator_first_touch",
    ]
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} publication-cycle rows to {OUT}")


if __name__ == "__main__":
    main()
