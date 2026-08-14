import csv
import datetime
import json

from report_common import (
    parse_iso8601,
    true_submission_date,
    nearest_export_key_effective,
    error_types_near_effective,
    drop_excluded_error_types,
    effective_after_event,
    is_excluded_dataset,
)

TEMPORAL_REPORT = "./temporal_report.json"
EVENT_SEQUENCES = "./pennsieve_event_series.json"
OUT = "./lab_submissions_before_after.csv"

WINDOW_START = datetime.datetime(2022, 4, 1, tzinfo=datetime.timezone.utc)


def first_request_date(dataset_id, event_sequences, floor=True):
    true_date = true_submission_date(dataset_id)
    if true_date is not None:
        return None if (floor and true_date < WINDOW_START) else true_date

    events = event_sequences.get(dataset_id)
    if not events:
        return None

    request_dates = [parse_iso8601(event.get("request_created")) for event in events]
    request_dates = [rd for rd in request_dates if rd and (not floor or rd >= WINDOW_START)]
    if not request_dates:
        return None

    return min(request_dates)


def award_number_near(record, event_dt):
    if event_dt is None:
        return ""
    key = nearest_export_key_effective(record, int(event_dt.timestamp()))
    return (record.get("award_number_graph") or {}).get(key, "")


def distinct_errors_at(record, event_dt):
    types = drop_excluded_error_types(error_types_near_effective(record, event_dt))
    return len(types) if types else 0


def main():
    with open(TEMPORAL_REPORT) as f:
        temporal_report = json.load(f)
    with open(EVENT_SEQUENCES) as f:
        event_sequences = json.load(f)

    by_lab = {}  # award -> list of dataset dicts

    for dataset_id, record in temporal_report.items():
        if not record.get("error_graph"):
            continue

        submission = first_request_date(dataset_id, event_sequences, floor=False)
        if submission is None:
            continue

        award = award_number_near(record, submission)
        # a trailing ", second-award" splits one lab across award strings; bin on the first
        award = award.split(",")[0].strip()
        if not award or award == "<unknown>":
            continue

        in_window = submission >= WINDOW_START
        scored = in_window and not effective_after_event(record, submission)

        by_lab.setdefault(award, []).append({
            "award_number": award,
            "period": "after" if in_window else "before",
            "submission_date": submission.date().isoformat(),
            "_submission": submission,
            "dataset_id": dataset_id,
            "title": record.get("title", ""),
            "distinct_errors_at_submission": distinct_errors_at(record, submission) if scored else "",
            "excluded_dataset": "yes" if is_excluded_dataset(dataset_id) else "",
        })

    rows = []
    for award, datasets in sorted(by_lab.items()):
        datasets.sort(key=lambda d: d["_submission"])
        after = [d for d in datasets if d["period"] == "after"]
        before = [d for d in datasets if d["period"] == "before"]
        for rank, d in enumerate(after, start=1):
            d["in_window_rank"] = rank
        for d in before:
            d["in_window_rank"] = ""
        for d in datasets:
            d["before_count"] = len(before)
            d["after_count"] = len(after)
            rows.append(d)

    fields = [
        "award_number", "before_count", "after_count",
        "period", "in_window_rank", "submission_date",
        "dataset_id", "title", "distinct_errors_at_submission", "excluded_dataset",
    ]

    with open(OUT, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote to {OUT}")


if __name__ == "__main__":
    main()
