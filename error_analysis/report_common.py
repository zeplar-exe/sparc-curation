import csv
import datetime
import json

# Whether to use error_index_graph or error_graph for error-index lookups.
USE_ERROR_INDEX_GRAPH = True

SPARC_ORGANIZATION = "organization:618e8dd9-f8d2-4dc4-9abb-c6aaab2e78a0"

EXCLUDED_DATASET_IDS = []
WHITELIST_DATASET_IDS = []
INCLUDED_ERROR_FORMATS = []
ERROR_DICTIONARY = []

with open("./dataset_exclusion_list.csv") as f:
    for row in csv.DictReader(f):
        EXCLUDED_DATASET_IDS.append(row["Dataset ID"])

with open("./big-did.json") as f:
    for did, entry in json.load(f).items():
        if entry["id_organization"] == SPARC_ORGANIZATION:
            WHITELIST_DATASET_IDS.append(did)

with open("./SPARC_Pipeline_Error_Dictionary_consolidated.csv") as f:
    for row in csv.DictReader(f):
        INCLUDED_ERROR_FORMATS.append(row["Match Key (verbatim)"])
        ERROR_DICTIONARY.append(row)


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
    return datetime.datetime.strptime(date_str, "%m-%d-%Y")


def fiscal_year(dt):
    """Fiscal year with a Feb 1 boundary: Jan belongs to the prior year.
    FY2022 = Feb 2022 - Jan 2023.
    """
    return None if dt is None else dt.year if dt.month >= 2 else dt.year - 1


with open("./error-info.json") as _ef:
    _error_info = {entry["id"]: (entry["description"], entry["format"]) for entry in json.load(_ef)}
EXCLUDED_ERROR_DESCRIPTIONS = [
    # _error_info[i] for i in (9, 132, 16, 89, 90, 23, 24, 25, 26, 39, 40, 41, 67, 106, 131, 129)
]  # see error-info.json
EXCLUDED_ERROR_TYPES = [
    "JSON value does not match Regex regex(^(OT2OD|OT3OD|U18|TR|U01))",
    "Required JSON property is missing from JSON required('contributor_count')",
    "Required JSON property is missing from JSON required('description')",
    "Required JSON property is missing from JSON required('manifest_records')",
    "Required JSON property is missing from JSON required('path_metadata')",
    "Required JSON property is missing from JSON required('submission_file')",
    "Required JSON property is missing from JSON required('tsr",
    "Required JSON property is missing from JSON required('modality')",
    "Required JSON property is missing from JSON required('organ')",
    "Required JSON property is missing from JSON required('techniques')",
    "JSON value value is of incorrect type expected_type(array)",
]
INCLUDED_ERROR_DESCRIPTIONS = [
    info[0] for info in _error_info.values() if info[1] in INCLUDED_ERROR_FORMATS or any(info[1].startswith(fmt) for fmt in INCLUDED_ERROR_FORMATS) or any(fmt.startswith(info[1]) for fmt in INCLUDED_ERROR_FORMATS)
]
INCLUDED_ERROR_FORMATS = [
    info[1] for info in _error_info.values() if info[1] in INCLUDED_ERROR_FORMATS or any(info[1].startswith(fmt) for fmt in INCLUDED_ERROR_FORMATS) or any(fmt.startswith(info[1]) for fmt in INCLUDED_ERROR_FORMATS)
]

def is_excluded_error_type(error_type):
    return False # now that we're using the dictionary, this should always be false
    path = error_type.split(":", 1)[0]
    err = error_type.split(":", 1)[-1] # if no path, get first item
    a = any(
        err == desc or err.startswith(desc + " ")
        for desc, format in EXCLUDED_ERROR_DESCRIPTIONS
    ) or any(error_type == et for et in EXCLUDED_ERROR_TYPES) \
        or "inputs/" in path
    
    if a:
        return True
    
    if not err in INCLUDED_ERROR_DESCRIPTIONS and not any(err.startswith(desc) for desc in INCLUDED_ERROR_DESCRIPTIONS):
        return True

    return False


def get_error_type_format(error_type):
    if ":" in error_type:
        error_type = error_type.split(":", 1)[1].strip()
    for desc, fmt in _error_info.values():
        if error_type == desc or error_type.startswith(desc):
            return fmt
    return None


def get_error_format_dict_data(format):
    if format.startswith("f'"):
        format = format[2:-1]
    for entry in ERROR_DICTIONARY:
        if entry["Match Key (verbatim)"] == format:
            return entry
    return None


def drop_excluded_error_types(error_types):
    """Filter out Converter/Manifest noise classes from an error-type dict."""
    if not error_types:
        return error_types
    return {t: c for t, c in error_types.items() if not is_excluded_error_type(t)}


def last_error_count_at_or_before(target_ts, error_graph):
    c = last_error_types_at_or_before(target_ts, error_graph)
    return sum(c.values()) if c else 0


def _nearest_non_failed_index(items, pos):
    n = len(items)
    offset = 1

    while True:
        moved = False
        nxt = pos + offset

        if nxt < n:
            moved = True
            if items[nxt][1] != 9999:
                return items[nxt][1]

        prv = pos - offset

        if prv >= 0:
            moved = True
            if items[prv][1] != 9999:
                return items[prv][1]

        if not moved:
            return 9999

        offset += 1


def last_error_index_at_or_before(target_ts, error_index_graph):
    items = sorted(
        ((int(ts_str), error_index) for ts_str, error_index in error_index_graph.items()),
        key=lambda item: item[0],
    )
    pos = None
    for i, (ts_int, _) in enumerate(items):
        if ts_int <= target_ts:
            pos = i
        else:
            break

    if pos is None:
        return None

    if items[pos][1] == 9999:
        return _nearest_non_failed_index(items, pos)

    return items[pos][1]


def error_diff_value_at_or_before(target_ts, graph):
    if USE_ERROR_INDEX_GRAPH:
        return last_error_index_at_or_before(target_ts, graph)

    return last_error_count_at_or_before(target_ts, graph)


def last_error_types_at_or_before(target_ts, error_graph):
    last_errors = None
    for ts_str, errors in sorted(error_graph.items(), key=lambda item: int(item[0])):
        ts_int = int(ts_str)
        if ts_int <= target_ts:
            last_errors = errors
        else:
            break

    if not last_errors:
        return None

    counts = {}
    for error_type, count in last_errors.items():
        if count > 0:
            counts[error_type] = int(count)
    return counts or None


def _positive_error_counts(errors):
    if not errors:
        return None
    counts = {error_type: int(count) for error_type, count in errors.items() if count > 0}
    return counts or None


def error_types_near(target_ts, error_graph):
    """Error types at the export nearest `target_ts`: prefer the latest export
    at or before it; if the target predates all exports, use the earliest one."""
    items = sorted(((int(ts_str), errors) for ts_str, errors in error_graph.items()), key=lambda item: item[0])

    if not items:
        return None

    chosen = None
    found = False
    for ts_int, errors in items:
        if ts_int <= target_ts:
            chosen = errors
            found = True
        else:
            break

    if not found:
        chosen = items[0][1]

    return _positive_error_counts(chosen)


def effective_after_event(dataset_record, event_dt):
    """True if the dataset has NO curation export whose 'updated' timestamp is at
    or before event_dt -- i.e. the nearest export postdates the event, so its
    error snapshot cannot represent the dataset's state at that event. Uses the
    export_ts_to_updated_ts_graph 'timestamp_updated' value per export (falling
    back to the export-start timestamp when absent). Datasets with no exports,
    or a None event, are treated as "after" (excluded)."""
    if event_dt is None:
        return True
    event_ts = int(event_dt.timestamp())
    export_urls = dataset_record.get("export_urls") or []
    if not export_urls:
        return True
    updated_graph = dataset_record.get("export_ts_to_updated_ts_graph") or {}
    for export in export_urls:
        start = export["unix_timestamp"]
        updated = (updated_graph.get(str(start)) or {}).get("timestamp_updated")
        effective = updated if updated is not None else start
        if effective <= event_ts:
            return False
    return True


def _effective_export_pairs(dataset_record):
    export_urls = dataset_record.get("export_urls") or []
    updated_graph = dataset_record.get("export_ts_to_updated_ts_graph") or {}
    pairs = []
    
    for export in export_urls:
        start = export["unix_timestamp"]
        updated = (updated_graph.get(str(start)) or {}).get("timestamp_updated")
        pairs.append((updated if updated is not None else start, start))
        
    pairs.sort(key=lambda p: p[0])
    
    return pairs


def nearest_export_key_effective(dataset_record, event_ts):
    pairs = _effective_export_pairs(dataset_record)
    
    if not pairs:
        return None
    pos = None
    
    for i, (eff, _) in enumerate(pairs):
        if eff <= event_ts:
            pos = i
        else:
            break
    if pos is None:
        pos = 0
    else:
        while pos > 0 and pairs[pos - 1][0] == pairs[pos][0]:
            pos -= 1
            
    return str(pairs[pos][1])


def error_types_near_effective(dataset_record, event_dt):
    if event_dt is None:
        return None
    
    key = nearest_export_key_effective(dataset_record, int(event_dt.timestamp()))
    
    if key is None:
        return None
    
    return _positive_error_counts((dataset_record.get("error_graph") or {}).get(key))
