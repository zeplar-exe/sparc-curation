import csv
import json

from report_common import is_excluded_dataset, parse_iso8601, true_submission_date, true_publication_date

EVENT_SEQUENCES = "./pennsieve_event_series.json"
OUT = "./sub_day_publications.csv"


def first_request_date(dataset_id, cycles):
    # ground-truth submission date, falling back to the earliest raw request
    true = true_submission_date(dataset_id)
    if true is not None:
        return true
    dates = [parse_iso8601(c.get("request_created")) for c in cycles]
    dates = [d for d in dates if d]
    return min(dates) if dates else None


def first_publication_date(dataset_id, cycles):
    # ground-truth publication date, falling back to the first cycle's raw accept
    true = true_publication_date(dataset_id)
    if true is not None:
        return true
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

        req = first_request_date(dataset_id, cycles)
        pub = first_publication_date(dataset_id, cycles)
        if not req or not pub or pub <= req:
            continue

        gap_seconds = (pub - req).total_seconds()
        
        if gap_seconds >= 5*60*60*24:
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

    print(f"Wrote {len(rows)} rows to {OUT}")
    if rows:
        print(f"Fastest: {rows[0]['gap_seconds']}s ({rows[0]['dataset_id']})")
        print(f"Slowest sub-day: {rows[-1]['gap_hours']}h ({rows[-1]['dataset_id']})")


if __name__ == "__main__":
    main()
