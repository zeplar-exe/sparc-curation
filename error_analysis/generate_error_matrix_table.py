import csv
import datetime
import json
from datetime import timezone
from collections import Counter, defaultdict
from report_common import is_excluded_dataset, parse_iso8601, is_excluded_error_type, get_error_type_format, get_error_format_dict_data, get_error_id, true_submission_date

EVENT_SEQUENCES = "./pennsieve_event_series.json"
TEMPORAL_REPORT = "./temporal_report.json"
BIG_DID = "./big-did.json"
OUT = "./SPARC_error_results_matrix_table.generated.csv"

FAIL_RADIUS = 5

TIMESTAMP_MODE = "updated"
TS_MODE_KEY = {
    "export_start": None,
    "updated_contents": "timestamp_updated_contents",
    "updated": "timestamp_updated",
}

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


def nearest_index(target_ts, sorted_ts):
    if not sorted_ts:
        return None
    
    pos = None
    
    for i, ts in enumerate(sorted_ts):
        if ts <= target_ts:
            pos = i
        else:
            break
    
    return pos if pos is not None else 0


def nearest_graph_value(graph, target_ts):
    if not graph:
        return None
    
    items = sorted(((int(k), v) for k, v in graph.items()), key=lambda kv: kv[0])
    pos = nearest_index(target_ts, [t for t, _ in items])
    
    return items[pos][1] if pos is not None else None


def effective_export_ts(export, updated_graph):
    start = export["unix_timestamp"]
    graph_key = TS_MODE_KEY[TIMESTAMP_MODE]
    
    if graph_key is None:
        return start
    
    alt = (updated_graph.get(str(start)) or {}).get(graph_key)
    return alt if alt is not None else start


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

    for dataset_id, cycles in event_sequences.items():
        if is_excluded_dataset(dataset_id):
            continue

        record = temporal_report.get(dataset_id)

        if not record:
            continue

        eligible = []
        
        for cycle in cycles:
            if cycle.get("incomplete"):
                continue
            
            req_dt = parse_iso8601(cycle.get("request_created"))
            acc_dt = parse_iso8601(cycle.get("accept_created"))
            
            if req_dt is None or req_dt <= datetime.datetime(2022, 4, 1, tzinfo=timezone.utc):
                continue
            if acc_dt is None or acc_dt <= datetime.datetime(2022, 4, 1, tzinfo=timezone.utc):
                continue
            
            eligible.append(cycle)
        
        cycles = eligible

        updated_graph = record.get("export_ts_to_updated_ts_graph") or {}
        exports = record.get("export_urls") or []

        if not exports:
            continue

        exports = sorted(exports, key=lambda e: effective_export_ts(e, updated_graph))
        export_ts = [effective_export_ts(e, updated_graph) for e in exports]

        title = record.get("title", "<unknown>")
        error_graph = record.get("error_graph", {})
        curation_index_graph = record.get("curation_index_graph", {})
        error_index_graph = record.get("error_index_graph", {})
        submission_index_graph = record.get("submission_index_graph", {})
        template_version_graph = record.get("template_version_graph", {})
        award_number_graph = record.get("award_number_graph", {})
        dataset_type_graph = record.get("dataset_type_graph", {})
        template_version_single = record.get("template_version")

        dois = big_did.get(dataset_id, {}).get("dois", [])
        doi = dois[-1] if dois else "<no doi>"

        for cycle in eligible[:1]: # first cycle only
            acc_raw = cycle.get("accept_created")
            acc = parse_iso8601(acc_raw)

            true_sub = true_submission_date(dataset_id)
            if true_sub is not None:
                req = true_sub
                req_raw = true_sub.isoformat()
            else:
                req_raw = cycle.get("request_created")
                req = parse_iso8601(req_raw)

            if not req or not acc:
                continue

            for phase, event_dt, event_raw in (
                ("submission", req, req_raw),
                ("publication", acc, acc_raw),
            ):        
                event_ts = int(event_dt.timestamp())
                pos: int = nearest_index(event_ts, export_ts)
                
                export = exports[pos]
                export_unix = export["unix_timestamp"]
                eff_ts = export_ts[pos]
                key = str(export_unix)

                failed = error_index_graph.get(key) == 9999

                snapshot = {m: int(c) for m, c in (error_graph.get(key) or {}).items() if c > 0}
                included = sum(1 for m in snapshot if not is_excluded_error_type(m))
                excluded = sum(1 for m in snapshot if is_excluded_error_type(m))

                template_version = template_version_graph.get(key) or template_version_single or ""
                award_number = award_number_graph.get(key) or ""
                dataset_type = dataset_type_graph.get(key) or ""

                if not failed:
                    for message in snapshot:
                        if is_excluded_error_type(message):
                            continue
                        path = message.split(":")[0]
                        fmt = get_error_type_format(message)
                        # data = get_error_format_dict_data(fmt)
                        # if not data:
                        #    continue
                        full = message # f"{path}:{fmt}"
                        message_totals[full] += 1
                        datasets_by_message[full].add(dataset_id)
                        message_to_path[full] = path
                        message_to_id[full] = get_error_id(message)

                eff = datetime.datetime.fromtimestamp(eff_ts, datetime.timezone.utc)
                print(eff.isoformat().replace('+00:00', 'Z'))
                fixed = {
                    "dataset_id": dataset_id.replace("N:", ""),
                    "award_number": award_number,
                    "invent": phase,
                    "curation_index": curation_index_graph.get(key, ""),
                    "error_index": error_index_graph.get(key, ""),
                    "submission_index": submission_index_graph.get(key, ""),
                    "template_version": template_version,
                    "dataset_type": dataset_type,
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
        writer.writerow(FIXED_FIELDS + message_columns)
        
        summary_row = ["how_many_datasets_have_this_error"] + [""] * (len(FIXED_FIELDS) - 1)
        writer.writerow(summary_row + [len(datasets_by_message[msg]) for msg in message_columns])

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
