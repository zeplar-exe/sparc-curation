import csv
import datetime
import json
import sys
from datetime import timezone
from collections import Counter, defaultdict
from report_common import is_excluded_dataset, parse_iso8601, is_excluded_error_type, get_error_type_format, get_error_format_dict_data, get_error_id, get_canonical_title, true_submission_date, true_publication_date, is_excluded_computational, dataset_type, doi_v1, reconciliation_publication_year, nearest_export_key_effective, error_types_near_effective, effective_export_ts_by_key

EVENT_SEQUENCES = "./pennsieve_event_series.json"
TEMPORAL_REPORT = "./temporal_report.json"
BIG_DID = "./big-did.json"
OUT = "./SPARC_error_results_matrix_table.generated.csv"

FAIL_RADIUS = 5

# pass --exclude-error-columns to drop excluded error types from the columns; the
# excluded_errors_present count still counts them
EXCLUDE_ERROR_COLUMNS = "--exclude-error-columns" in sys.argv

# the shared nearest-export logic in report_common keys off the 'updated' timestamp
TIMESTAMP_MODE = "updated"

FIXED_FIELDS = [
    "dataset_id",
    "award_number",
    "invent",
    "curation_index",
    "error_index",
    "submission_index",
    "template_version",
    "dataset_type",
    "event_timestamp",
    "doi",
    "failed_completely at submission",
    "included_errors_present",
    "excluded_errors_present",
    "error_type_index",
    "curation_export_download_link",
    "curation_export_export_date",
    "effective_export_timestamp",
    "days_export_to_event",
    "days_export_to_effective",
    "timestamp_mode",
    "title"
]


# / if encounter identical curation-export timestamp between sub and pub, exclude
# + add [meta][dataset_type] graph and include a column in the matrix
# + test using timestamp_updated and timestamp_contents_updated instead of timestamp export start
# + for failed exports, just leave all error fields empty


def main():
    with open(TEMPORAL_REPORT) as f:
        temporal_report = json.load(f)
    with open(EVENT_SEQUENCES) as f:
        event_sequences = json.load(f)
    with open(BIG_DID) as f:
        big_did = json.load(f)

    rows = []
    message_totals = Counter()
    datasets_by_message = defaultdict(set)  # message -> set of dataset ids
    message_to_path = {}  # message -> error path (#/...)
    message_to_id = {}    # message -> canonical error-map # (via collapse)
    message_to_title = {} # message -> human-readable error-map title (raw fallback)

    window_start = datetime.datetime(2022, 4, 1, tzinfo=timezone.utc)

    for dataset_id, cycles in event_sequences.items():
        if is_excluded_dataset(dataset_id) or is_excluded_computational(dataset_id):
            continue

        record = temporal_report.get(dataset_id)

        if not record:
            continue

        complete = [cycle for cycle in cycles if not cycle.get("incomplete")]

        if not complete:
            continue

        first_cycle = complete[0]

        # A7 verified first-cycle dates, falling back to raw events
        true_sub = true_submission_date(dataset_id) or parse_iso8601(first_cycle.get("request_created"))
        true_pub = true_publication_date(dataset_id) or parse_iso8601(first_cycle.get("accept_created"))

        if true_sub is None or true_pub is None:
            continue

        # either date before the 2022-04 window excludes the dataset entirely
        if true_sub <= window_start or true_pub <= window_start:
            continue

        # a reconciliation publication_year before 2022 means an earlier cycle than pennsieve shows
        recon_year = reconciliation_publication_year(dataset_id)

        if recon_year is not None and recon_year < 2022:
            continue

        eligible = [first_cycle]

        exports = record.get("export_urls") or []

        if not exports:
            continue

        export_by_key = {str(e["unix_timestamp"]): e for e in exports}
        eff_ts_by_key = effective_export_ts_by_key(record)

        title = record.get("title", "<unknown>")
        curation_index_graph = record.get("curation_index_graph", {})
        error_index_graph = record.get("error_index_graph", {})
        submission_index_graph = record.get("submission_index_graph", {})
        template_version_graph = record.get("template_version_graph", {})
        award_number_graph = record.get("award_number_graph", {})
        template_version_single = record.get("template_version")

        ds_type = dataset_type(dataset_id)

        # DOI v1 from reconciliation, falling back to big_did
        dois = big_did.get(dataset_id, {}).get("dois", [])
        doi = doi_v1(dataset_id) or (dois[-1] if dois else "<no doi>")

        for cycle in eligible[:1]: # first cycle only
            req, req_raw = true_sub, true_sub.isoformat()
            acc, acc_raw = true_pub, true_pub.isoformat()

            for phase, event_dt, event_raw in (
                ("submission", req, req_raw),
                ("publication", acc, acc_raw),
            ):
                event_ts = int(event_dt.timestamp())
                key = nearest_export_key_effective(record, event_ts)

                export = export_by_key[key]
                export_unix = export["unix_timestamp"]
                eff_ts = eff_ts_by_key[key]

                failed = error_index_graph.get(key) == 9999

                snapshot = error_types_near_effective(record, event_dt) or {}
                included = sum(1 for m in snapshot if not is_excluded_error_type(m))
                excluded = sum(1 for m in snapshot if is_excluded_error_type(m))

                template_version = template_version_graph.get(key) or template_version_single or ""
                award_number = award_number_graph.get(key) or ""

                if not failed:
                    for message in snapshot:
                        if EXCLUDE_ERROR_COLUMNS and is_excluded_error_type(message):
                            continue
                        path = message.split(":")[0]
                        # one column per raw message (no collapse); header shows the title, path its own row
                        full = message
                        message_totals[full] += 1
                        datasets_by_message[full].add(dataset_id)
                        message_to_path[full] = path
                        message_to_id[full] = get_error_id(message)
                        message_to_title[full] = get_canonical_title(message)

                eff = datetime.datetime.fromtimestamp(eff_ts, datetime.timezone.utc)
                fixed = {
                    "dataset_id": dataset_id.replace("N:", ""),
                    "award_number": award_number,
                    "invent": phase,
                    "curation_index": curation_index_graph.get(key, ""),
                    "error_index": error_index_graph.get(key, ""),
                    "submission_index": submission_index_graph.get(key, ""),
                    "template_version": template_version,
                    "dataset_type": ds_type,
                    "event_timestamp": event_raw or "",
                    "doi": doi,
                    "title": title,
                    "failed_completely at submission": failed,
                    "included_errors_present": included,
                    "excluded_errors_present": excluded,
                    "error_type_index": len(snapshot),
                    "curation_export_download_link": export.get("url", ""),
                    "curation_export_export_date": export.get("timestamp", ""),
                    "effective_export_timestamp": eff.isoformat().replace('+00:00', 'Z'),
                    "days_export_to_event": round((export_unix - event_dt.timestamp()) / 86400, 4),
                    "days_export_to_effective": round((eff.timestamp() - event_dt.timestamp()) / 86400, 4),
                    "timestamp_mode": TIMESTAMP_MODE
                }
                rows.append((fixed, snapshot))

    message_columns = [m for m, _ in message_totals.most_common()]

    with open(OUT, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        # header row: human-readable error titles (duplicated where messages share a title)
        writer.writerow(FIXED_FIELDS + [message_to_title.get(msg, msg) for msg in message_columns])

        summary_row = ["how_many_datasets_have_this_error"] + [""] * (len(FIXED_FIELDS) - 1)
        writer.writerow(summary_row + [len(datasets_by_message[msg]) for msg in message_columns])

        # path on its own row
        path_row = ["error_path"] + [""] * (len(FIXED_FIELDS) - 1)
        writer.writerow(path_row + [message_to_path.get(msg, "") for msg in message_columns])

        id_row = ["error_id"] + [""] * (len(FIXED_FIELDS) - 1)
        writer.writerow(id_row + [message_to_id.get(msg, "") for msg in message_columns])

        for fixed, snapshot in rows:
            err_row = [1 if msg in snapshot else 0 for msg in message_columns]
            writer.writerow(
                [fixed[field] for field in FIXED_FIELDS]
                + (err_row if not fixed["failed_completely at submission"] else [float('NaN')] * len(err_row))
            )

    print(f"Wrote {len(rows)} rows x {len(FIXED_FIELDS) + len(message_columns)} columns to {OUT}")
    print(f"Distinct error messages (columns): {len(message_columns)}")


if __name__ == "__main__":
    main()
