import csv
import datetime
import json

from report_common import (
    is_excluded_dataset,
    parse_iso8601,
    true_submission_date,
    true_publication_date,
    reconciliation_publication_year,
    is_excluded_computational,
)

CURATION_CLUSTERS = "./pennsieve_curation_clusters.json"
EVENT_SEQUENCES = "./pennsieve_event_series.json"
OUT = "./curation_session_clusters.csv"

WINDOW_START = datetime.datetime(2022, 4, 1, tzinfo=datetime.timezone.utc)


def first_request_date(dataset_id, cycles, floor=True):
    true = true_submission_date(dataset_id)
    if true is not None:
        return None if (floor and true < WINDOW_START) else true
    dates = [parse_iso8601(c.get("request_created")) for c in cycles]
    dates = [d for d in dates if d and (not floor or d >= WINDOW_START)]
    return min(dates) if dates else None


def first_publication_date(dataset_id, cycles):
    true = true_publication_date(dataset_id)
    if true is not None:
        return true
    return parse_iso8601(cycles[0].get("accept_created")) if cycles else None


def graph_excluded(dataset_id, cycles):
    submission = first_request_date(dataset_id, cycles)
    if submission is None:
        return True
    publication = first_publication_date(dataset_id, cycles)
    if publication is not None and publication < WINDOW_START:
        return True
    recon_year = reconciliation_publication_year(dataset_id)
    if recon_year is not None and recon_year < 2022:
        return True
    if is_excluded_computational(dataset_id):
        return True
    return False


def cluster_hours(cluster):
    start = parse_iso8601(cluster.get("start"))
    end = parse_iso8601(cluster.get("end"))
    if not start or not end or end < start:
        return None
    return (end - start).total_seconds() / 3600


def iso(dt):
    return dt.isoformat() if dt else ""


def main():
    with open(CURATION_CLUSTERS) as f:
        curation_clusters = json.load(f)
    with open(EVENT_SEQUENCES) as f:
        event_sequences = json.load(f)

    datasets = []

    for dataset_id, sequences in curation_clusters.items():
        cycles = event_sequences.get(dataset_id, [])

        if is_excluded_dataset(dataset_id) or graph_excluded(dataset_id, cycles):
            continue

        submission = first_request_date(dataset_id, cycles)
        publication = first_publication_date(dataset_id, cycles)

        cluster_rows = []
        for sequence in sequences:
            for cluster in sequence.get("clusters", []):
                start = parse_iso8601(cluster.get("start"))
                end = parse_iso8601(cluster.get("end"))
                hours = max(cluster_hours(cluster), 1)

                if hours is None:
                    continue

                cluster_rows.append({
                    "dataset_id": dataset_id,
                    "first_request_date": iso(submission),
                    "publication_date": iso(publication),
                    "cluster_start": iso(start),
                    "cluster_end": iso(end),
                    "cluster_hours": round(hours, 4),
                    "within_first_cycle": "yes" if (publication is not None and start is not None and start <= publication) else "no",
                })

        if not cluster_rows:
            continue

        total_hours = sum(row["cluster_hours"] for row in cluster_rows)
        for row in cluster_rows:
            row["total_curation_hours"] = round(total_hours, 4)

        cluster_rows.sort(key=lambda row: row["cluster_start"])
        datasets.append((total_hours, cluster_rows))

    datasets.sort(key=lambda entry: entry[0], reverse=True)

    fieldnames = [
        "dataset_id",
        "first_request_date",
        "publication_date",
        "cluster_start",
        "cluster_end",
        "cluster_hours",
        "within_first_cycle",
        "total_curation_hours",
    ]

    with open(OUT, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for _, cluster_rows in datasets:
            writer.writerows(cluster_rows)

    print(f"Wrote to {OUT}")


if __name__ == "__main__":
    main()
