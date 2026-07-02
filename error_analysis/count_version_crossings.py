import csv
import datetime
import json
from collections import Counter

EVENT_SEQUENCES = "./pennsieve_event_series.json"
SPARCUR_UPDATES = "./sparcur_updates.csv"
DATASET_EXCLUSION = "./dataset_exclusion_list.csv"
BIG_DID = "./big-did.json"
OUT = "./version_update_crossings.csv"

SPARC_ORGANIZATION = "organization:618e8dd9-f8d2-4dc4-9abb-c6aaab2e78a0"

EXCLUDED_DATASET_IDS = []
with open(DATASET_EXCLUSION) as f:
    for row in csv.DictReader(f):
        EXCLUDED_DATASET_IDS.append(row["Dataset ID"])

WHITELIST_DATASET_IDS = []
with open(BIG_DID) as f:
    for did, entry in json.load(f).items():
        if entry["id_organization"] == SPARC_ORGANIZATION:
            WHITELIST_DATASET_IDS.append(did)


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


def parse_mmddyyyy(date_str):
    return datetime.datetime.strptime(date_str, "%m-%d-%Y").replace(
        tzinfo=datetime.timezone.utc
    )


def first_request_date(cycles):
    dates = [parse_iso8601(c.get("request_created")) for c in cycles]
    dates = [d for d in dates if d]
    return min(dates) if dates else None


def first_publication_date(cycles):
    return parse_iso8601(cycles[0].get("accept_created")) if cycles else None


def main():
    with open(EVENT_SEQUENCES, "r", encoding="utf-8") as f:
        event_sequences = json.load(f)

    updates = []
    with open(SPARCUR_UPDATES, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            updates.append((row["version"], parse_mmddyyyy(row["date"])))
    updates.sort(key=lambda u: u[1])

    rows = []
    considered = 0
    crossing = 0
    per_version = Counter()
    crossings_hist = Counter()

    for dataset_id, cycles in event_sequences.items():
        if is_excluded_dataset(dataset_id):
            continue
        if not cycles:
            continue

        req = first_request_date(cycles)
        pub = first_publication_date(cycles)
        if not req or not pub or pub <= req:
            continue

        considered += 1
        crossed = [(ver, date) for ver, date in updates if req < date <= pub]
        crossings_hist[len(crossed)] += 1
        
        if crossed:
            crossing += 1
            for v, _ in crossed:
                per_version[v] += 1
            rows.append({
                "dataset_id": dataset_id,
                "request_date": req.isoformat(),
                "publication_date": pub.isoformat(),
                "span_days": round((pub - req).total_seconds() / 86400, 2),
                "num_versions_crossed": len(crossed),
                "versions_crossed": ";".join(v for v, _ in crossed),
            })

    rows.sort(key=lambda r: (r["num_versions_crossed"], r["span_days"]), reverse=True)

    with open(OUT, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "dataset_id",
                "request_date",
                "publication_date",
                "span_days",
                "num_versions_crossed",
                "versions_crossed",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
