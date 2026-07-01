import csv
import datetime
import json

EVENT_SEQUENCES = "./pennsieve_event_series.json"
OUT = "./sub_day_publications.csv"

EXCLUDED_DATASET_IDS = []

with open("./dataset_exclusion_list.csv") as f:
    for row in csv.DictReader(f):
        EXCLUDED_DATASET_IDS.append(row["Dataset ID"])

WHITELIST_DATASET_IDS = []
with open("./big-did.json") as f:
    for entry in json.load(f):
        WHITELIST_DATASET_IDS.append(entry)


def is_excluded_dataset(dataset_id):
    if dataset_id.startswith("dataset:"):
        dataset_id = "N:" + dataset_id
    elif not dataset_id.startswith("N:dataset:"):
        dataset_id = "N:dataset:" + dataset_id
    return dataset_id in EXCLUDED_DATASET_IDS or dataset_id not in WHITELIST_DATASET_IDS


def parse_iso8601(date_str):
    if not date_str:
        return None
    return datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))


def first_request_date(cycles):
    dates = [parse_iso8601(c.get("request_created")) for c in cycles]
    dates = [d for d in dates if d]
    return min(dates) if dates else None


def first_publication_date(cycles):
    return parse_iso8601(cycles[0].get("accept_created")) if cycles else None


def main():
    with open(EVENT_SEQUENCES, "r", encoding="utf-8") as f:
        event_sequences = json.load(f)

    rows = []

    for dataset_id, cycles in event_sequences.items():
        if is_excluded_dataset(dataset_id):
            continue
        if not cycles:
            continue

        req = first_request_date(cycles)
        pub = first_publication_date(cycles)
        if not req or not pub or pub <= req:
            continue

        gap_seconds = (pub - req).total_seconds()
        
        if gap_seconds >= 60*60*24:
            continue

        rows.append({
            "dataset_id": dataset_id,
            "request_date": req.isoformat(),
            "publication_date": pub.isoformat(),
            "gap_seconds": round(gap_seconds, 1),
            "gap_minutes": round(gap_seconds / 60, 2),
            "gap_hours": round(gap_seconds / 3600, 3),
            "num_cycles": len(cycles),
        })

    rows.sort(key=lambda r: r["gap_seconds"])

    with open(OUT, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "dataset_id",
                "request_date",
                "publication_date",
                "gap_seconds",
                "gap_minutes",
                "gap_hours",
                "num_cycles",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} sub-day (< 1 day request->publication) datasets to {OUT}")
    if rows:
        print(f"Fastest: {rows[0]['gap_seconds']}s ({rows[0]['dataset_id']})")
        print(f"Slowest sub-day: {rows[-1]['gap_hours']}h ({rows[-1]['dataset_id']})")


if __name__ == "__main__":
    main()
