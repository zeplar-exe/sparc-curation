"""Audit positive days_export_to_effective rows in the matrix.

A positive value means the chosen export's effective (updated) timestamp is AFTER
the row's event -- i.e. the event predates every export, so the nearest export is
a fallback. This checks whether the true-submission date (which can be earlier than
the raw request) is what pushed those submission rows negative->positive.

> Thanks Claude.
"""

import csv
import datetime
import json

MATRIX = "./SPARC_error_results_matrix_table.generated.csv"
CURATION_START = "./curation_start_dates.csv"
EVENT_SEQUENCES = "./pennsieve_event_series.json"
OUT = "./effective_positive_audit.csv"

FIXED_TAIL = "timestamp_mode"  # last fixed column before the error columns


def parse_iso8601(date_str):
    if not date_str:
        return None
    return datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))


def main():
    # true submission date per dataset (matrix strips the N: prefix)
    true_submission = {}
    with open(CURATION_START) as f:
        for row in csv.DictReader(f):
            value = (row.get("true_submission_date") or "").strip()
            if value:
                true_submission[row["dataset_id"].replace("N:", "")] = parse_iso8601(value)

    # earliest raw request_created per dataset (also N: stripped)
    raw_request = {}
    with open(EVENT_SEQUENCES) as f:
        for dataset_id, cycles in json.load(f).items():
            requests = [parse_iso8601(c.get("request_created")) for c in cycles]
            requests = [r for r in requests if r]
            if requests:
                raw_request[dataset_id.replace("N:", "")] = min(requests)

    rows = []
    with open(MATRIX) as f:
        for row in csv.DictReader(f):
            # skip the non-standard summary rows (how_many.../error_path/error_id)
            if not (row.get("days_export_to_effective") or "").strip():
                continue
            if float(row["days_export_to_effective"]) <= 0:
                continue

            dataset_id = row["dataset_id"]
            event_dt = parse_iso8601(row["event_timestamp"])
            effective_dt = parse_iso8601(row["effective_export_timestamp"])
            true_dt = true_submission.get(dataset_id)
            request_dt = raw_request.get(dataset_id)

            # which submission date did the matrix actually use for this row?
            using_true = true_dt is not None and event_dt is not None and abs((event_dt - true_dt).total_seconds()) < 1
            source = "true_submission" if using_true else "request/other"

            # would it still be positive with the raw request instead?
            days_if_request = ""
            flips_negative = ""
            if request_dt is not None and effective_dt is not None:
                d = round((effective_dt - request_dt).total_seconds() / 86400, 4)
                days_if_request = d
                flips_negative = "yes" if d <= 0 else ""

            rows.append({
                "dataset_id": dataset_id,
                "invent": row["invent"],
                "days_export_to_effective": row["days_export_to_effective"],
                "submission_source": source,
                "event_timestamp": row["event_timestamp"],
                "true_submission_date": true_dt.isoformat() if true_dt else "",
                "raw_request_date": request_dt.isoformat() if request_dt else "",
                "effective_export_timestamp": row["effective_export_timestamp"],
                "days_if_raw_request": days_if_request,
                "would_flip_negative_with_request": flips_negative,
            })

    fieldnames = [
        "dataset_id", "invent", "days_export_to_effective", "submission_source",
        "event_timestamp", "true_submission_date", "raw_request_date",
        "effective_export_timestamp", "days_if_raw_request",
        "would_flip_negative_with_request",
    ]
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    caused_by_true = sum(1 for r in rows if r["submission_source"] == "true_submission" and r["would_flip_negative_with_request"] == "yes")
    print(f"positive days_export_to_effective rows: {len(rows)} -> {OUT}")
    print(f"  by phase: {dict((p, sum(1 for r in rows if r['invent'] == p)) for p in set(r['invent'] for r in rows))}")
    print(f"  using true_submission: {sum(1 for r in rows if r['submission_source'] == 'true_submission')}")
    print(f"  ...that would go NEGATIVE if the raw request were used: {caused_by_true}")


if __name__ == "__main__":
    main()
