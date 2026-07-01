import csv
import datetime
import json

TEMPORAL_REPORT = "./temporal_report.json"
EVENT_SEQUENCES = "./pennsieve_event_series.json"
OUT = "./far_off_export_datasets.csv"

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


def first_publication_date(events):
    if not events:
        return None
    return parse_iso8601(events[0].get("accept_created"))


def main():
    with open(TEMPORAL_REPORT, "r", encoding="utf-8") as f:
        temporal_report = json.load(f)
    with open(EVENT_SEQUENCES, "r", encoding="utf-8") as f:
        event_sequences = json.load(f)

    rows = []

    for dataset_id, dataset_record in temporal_report.items():
        if is_excluded_dataset(dataset_id):
            continue

        error_graph = dataset_record.get("error_graph", {})
        if not error_graph:
            continue

        pub_date = first_publication_date(event_sequences.get(dataset_id))
        if not pub_date:
            continue

        pub_ts = int(pub_date.timestamp())
        export_ts = sorted(int(ts_str) for ts_str in error_graph)

        if any(ts <= pub_ts for ts in export_ts):
            continue

        earliest_ts = export_ts[0]
        earliest_export = datetime.datetime.fromtimestamp(
            earliest_ts, tz=datetime.timezone.utc
        )
        gap_days = (earliest_ts - pub_ts) / 86400

        rows.append({
            "dataset_id": dataset_id,
            "publication_date": pub_date.isoformat(),
            "earliest_export_date": earliest_export.isoformat(),
            "gap_days": round(gap_days, 1),
        })

    rows.sort(key=lambda r: r["gap_days"], reverse=True)

    with open(OUT, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["dataset_id", "publication_date", "earliest_export_date", "gap_days"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} far-off-export datasets to {OUT}")
    if rows:
        print(f"Largest gap: {rows[0]['gap_days']} days ({rows[0]['dataset_id']})")
        print(f"Smallest gap: {rows[-1]['gap_days']} days ({rows[-1]['dataset_id']})")


if __name__ == "__main__":
    main()
