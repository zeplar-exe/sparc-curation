import csv
import json

from report_common import parse_iso8601

EVENT_SEQUENCES = "./pennsieve_event_series.json"
OUT = "./publication_request_clusters.csv"

REQUEST_TYPES = {"REQUEST_PUBLICATION", "REQUEST_EMBARGO"}

TERMINALS = {
    "ACCEPT_PUBLICATION": "accept",
    "REJECT_PUBLICATION": "reject",
    "CANCEL_PUBLICATION": "cancel",
    "ACCEPT_EMBARGO": "accept",
    "REJECT_EMBARGO": "reject",
}


def iso(dt):
    return dt.isoformat() if dt else ""


def main():
    with open(EVENT_SEQUENCES) as f:
        event_sequences = json.load(f)

    rows = []

    for dataset_id, cycles in event_sequences.items():
        events = [event for cycle in cycles for event in cycle.get("events", [])]
        events = [(parse_iso8601(e.get("createdAt")), e) for e in events]
        events = sorted((e for e in events if e[0] is not None), key=lambda e: e[0])

        open_request = None  # (request_type, request_dt)

        def collect(request_type, request_dt, terminal_event, outcome_dt):
            duration = ""
            if outcome_dt is not None:
                duration = round((outcome_dt - request_dt).total_seconds() / 86400, 3)
            rows.append({
                "dataset_id": dataset_id,
                "request_type": request_type,
                "request_date": iso(request_dt),
                "terminal_event": terminal_event,
                "outcome_date": iso(outcome_dt),
                "duration_days": duration,
            })

        for created, event in events:
            event_type = event.get("eventType")

            if event_type in REQUEST_TYPES:
                if open_request is not None:
                    collect(open_request[0], open_request[1], "", None)
                open_request = (event_type, created)
            elif event_type in TERMINALS:
                if open_request is not None:
                    collect(open_request[0], open_request[1], event_type, created)
                    open_request = None

        if open_request is not None:
            collect(open_request[0], open_request[1], "", None)

    rows.sort(key=lambda r: (r["dataset_id"], r["request_date"]))

    fieldnames = [
        "dataset_id",
        "request_type",
        "request_date",
        "terminal_event",
        "outcome_date",
        "duration_days",
    ]

    with open(OUT, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote to {OUT}")


if __name__ == "__main__":
    main()
