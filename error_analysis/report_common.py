import csv
import datetime
import glob
import json
import os
import re

from dateutil import parser as dateutil_parser

# Whether to use error_index_graph or error_graph for error-index lookups.
USE_ERROR_INDEX_GRAPH = False

SPARC_ORGANIZATION = "organization:618e8dd9-f8d2-4dc4-9abb-c6aaab2e78a0"

EXCLUDED_DATASET_IDS = []
ERROR_EXCLUDED_DATASET_IDS = []
WHITELIST_DATASET_IDS = []
INCLUDED_ERROR_FORMATS = []
ERROR_DICTIONARY = []
PENNSIEVE_DATASET_MAP = {}

FIRST_PUBLISHED_CACHE = "./pennsieve_first_published.csv"
_first_published = None
RECONCILIATION_SOURCE = "./SPARC_pipeline_published_reconciliation.csv"
_reconciliation_rows = None

EXCLUDED_PATH_PREFIXES = ("#/inputs", "#/specimen_dirs", "#/entity_dirs", "#/meta/techniques", "#/code_description") # for graphs

# old exclusion file (REVA datasets) is still applied before the ground truth
with open("./dataset_exclusion_list.csv") as f:
    for row in csv.DictReader(f):
        EXCLUDED_DATASET_IDS.append(row["Dataset ID"])

with open("./big-did.json") as f:
    for did, entry in json.load(f).items():
        PENNSIEVE_DATASET_MAP[did] = entry["id_published"]

# inclusion ground truth; the pipeline dataset list, keeping only SPARC and dropping sample/test
with open("./all_datasets_pipeline.csv", encoding="utf-8-sig") as f:
    for raw in csv.DictReader(f):
        row = {(key or "").strip(): value for key, value in raw.items()}
        if (row.get("organization") or "").strip() != "SPARC":
            continue
        if (row.get("test dataset exclude") or "").lower() == "sample/test":
            continue
        #if (row.get("status") or "").lower() != "completed":
        #    continue
        WHITELIST_DATASET_IDS.append(row["node_id"].strip())

with open("./SPARC_error_map.csv") as f:
    for row in csv.DictReader(f):
        INCLUDED_ERROR_FORMATS.append(row.get("Match Key (verbatim)", ""))
        ERROR_DICTIONARY.append(row)

# error map (SPARC_error_map.csv): stored error_graph key -> canonical #
# Rows collapse via `colaps to`
_error_map_rows = {row["#"].strip(): row for row in ERROR_DICTIONARY if row.get("#", "").strip()}

TAG_KINDS = ("regex", "required", "expected_type", "allowed")


def _canonical_num(row):
    seen = set()

    while True:
        num = row.get("#", "").strip()
        collapse = (row.get("colaps to") or "").strip()

        if not collapse or collapse not in _error_map_rows or collapse in seen:
            return num

        seen.add(num)
        row = _error_map_rows[collapse]


def _tag_signature(error_type):
    """Normalized (kind, content) tag, so `required(#/meta:'organ')` and
    `required('organ')` both become ('required', 'organ'). None if no tag."""
    best = None

    for kind in TAG_KINDS:
        idx = error_type.find(kind + "(")
        if idx != -1 and (best is None or idx < best[1]):
            best = (kind, idx)

    if best is None:
        return None

    kind, idx = best
    content = error_type[idx + len(kind) + 1:].rstrip()

    if content.endswith(")"):
        content = content[:-1]

    content = content.strip().rstrip('"').strip()

    if kind == "required":
        match = re.search(r"'([^']+)'", content)  # field name only (drop #/path)
        content = match.group(1) if match else content

    return (kind, content)


TITLE_TO_ID = {}
TITLE_TO_CANON = {}
TAG_TO_ID = {}
TAG_TO_CANON = {}
EXCLUDED_IDS = set()

for row in ERROR_DICTIONARY:
    num = _canonical_num(row)
    canon_title = _error_map_rows.get(num, row).get("Error Title", "").strip()

    keys = []
    for column in ("Error Title", "Type (human-readable)"):
        value = (row.get(column) or "").strip()
        if value:
            keys.append(value)

    # A Match Key is a single pattern whose regex()/allowed() body can itself
    # contain '|', so it must NOT be split. Legacy Title may list several titles.
    match_key = (row.get("Match Key (verbatim)") or "").strip()
    if match_key:
        keys.append(match_key)

    for part in (row.get("Legacy Title") or "").split("|"):
        part = part.strip()
        if part:
            keys.append(part)

    for key in keys:
        TITLE_TO_ID.setdefault(key, num)
        TITLE_TO_CANON.setdefault(key, canon_title)

    # field/type/regex-specific rows: index by normalized tag signature
    signature = _tag_signature(match_key) if match_key else None
    if signature:
        TAG_TO_ID.setdefault(signature, num)
        TAG_TO_CANON.setdefault(signature, canon_title)

# exclusion is driven by the canonical row's own Excluded flag
for num, row in _error_map_rows.items():
    if _canonical_num(row) == num and (row.get("Excluded?") or "").strip().lower() == "yes":
        EXCLUDED_IDS.add(num)


def _title_of(error_type):
    """Recover the stored title: drop the `path:` prefix and any tag suffix."""
    after = error_type.split(":", 1)[1] if ":" in error_type else error_type
    after = re.split(r" (regex|required|expected_type|allowed)\(", after)[0]
    return after.strip()


def get_error_id(error_type):
    """Ground truth error-map # for a stored error_graph key
    A tag (specific regex for ex) signature resolves to the field/type-specific row first,
    otherwise falls back to the base title."""
    signature = _tag_signature(error_type)

    if signature is not None and signature in TAG_TO_ID:
        return TAG_TO_ID[signature]

    return TITLE_TO_ID.get(_title_of(error_type), "")


def get_canonical_title(error_type):
    """Canonical error-map Error Title for a stored key; falls back to the raw
    description (tag kept) when unmapped."""
    signature = _tag_signature(error_type)

    if signature is not None and signature in TAG_TO_CANON:
        return TAG_TO_CANON[signature]

    title = _title_of(error_type)
    if title in TITLE_TO_CANON:
        return TITLE_TO_CANON[title]

    # unmapped: keep the full description including any tag
    return error_type.split(":", 1)[1].strip() if ":" in error_type else error_type


def normalize_dataset_id(dataset_id):
    if dataset_id.startswith("N:dataset:"):
        return dataset_id
    if dataset_id.startswith("dataset:"):
        return "N:" + dataset_id
    return "N:dataset:" + dataset_id


def is_excluded_dataset(dataset_id):
    dataset_id = normalize_dataset_id(dataset_id)
    return dataset_id in EXCLUDED_DATASET_IDS or dataset_id not in WHITELIST_DATASET_IDS


def parse_iso8601(date_str):
    if not date_str:
        return None
    return datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))


def parse_mmddyyyy(date_str):
    return datetime.datetime.strptime(date_str, "%m-%d-%Y")


def parse_date(value):
    """Generalized/lenient date parse for hand-verified values: accepts most free-form strings. 
    None when nothing parses."""
    if value is None:
        return None

    if isinstance(value, datetime.datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            dt = dateutil_parser.parse(text, fuzzy=True)
        except (ValueError, OverflowError):
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)

    return dt


def fiscal_year(dt):
    """Fiscal year with a Feb 1 boundary: Jan belongs to the prior year.
    FY2022 = Feb 2022 - Jan 2023.
    """
    return None if dt is None else dt.year if dt.month >= 2 else dt.year - 1


COMPUTED_CURATION_START = "./curation_start_dates.csv"
_start_rows_cache = {}


def _curation_start_source():
    """Prefer the newest hand-verified export (curation_start_dates_verified*.csv),
    else the computed curation_start_dates.csv."""
    verified = glob.glob("./curation_start_dates_verified*.csv")
    if verified:
        return verified[-1]
    return COMPUTED_CURATION_START


def _start_rows(path):
    if path not in _start_rows_cache:
        rows = {}
        try:
            # utf-8-sig strips the BOM Excel prepends on CSV export
            with open(path, encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    rows[row["dataset_id"]] = row
        except FileNotFoundError:
            pass
        _start_rows_cache[path] = rows
    return _start_rows_cache[path]


def _curation_start_row(dataset_id):
    return _start_rows(_curation_start_source()).get(dataset_id)


def true_submission_date(dataset_id):
    row = _curation_start_row(dataset_id)
    if not row:
        return None

    verified = parse_date(row.get("true_submission_date"))
    publication = parse_date(row.get("publication_date"))

    # if the verified submission->publication span is still under a day, fall back to
    # the original computed submission date
    if verified is not None and publication is not None and publication - verified < datetime.timedelta(days=1):
        computed = _start_rows(COMPUTED_CURATION_START).get(dataset_id)
        if computed:
            fallback = parse_date(computed.get("true_submission_date"))
            if fallback is not None:
                return fallback

    return verified

def _load_first_published():
    global _first_published
    if _first_published is None:
        _first_published = {}
        try:
            with open(FIRST_PUBLISHED_CACHE, encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    _first_published[row["dataset_id"]] = row.get("publication_date") or ""
        except FileNotFoundError:
            pass
    return _first_published


def _cache_first_published(dataset_id, dt):
    cache = _load_first_published()
    iso = dt.isoformat() if dt else ""
    cache[dataset_id] = iso
    write_header = not os.path.exists(FIRST_PUBLISHED_CACHE)
    with open(FIRST_PUBLISHED_CACHE, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["dataset_id", "publication_date"])
        writer.writerow([dataset_id, iso])


def true_publication_date(dataset_id):
    cache = _load_first_published()
    if dataset_id in cache:
        return parse_iso8601(cache[dataset_id]) if cache[dataset_id] else None

    dt = None
    published_id = PENNSIEVE_DATASET_MAP.get(dataset_id)
    if published_id is not None:
        import requests
        res = requests.get(f"https://api.pennsieve.io/discover/datasets/{published_id}/versions")
        if res.status_code == 200:
            dt = parse_date(res.json()[-1]["firstPublishedAt"])
        else:
            print("Failed to fetch publication date from Pennsieve API for dataset_id:", dataset_id)

    # not in the published map, or the API had nothing: fall back to the A7/computed row
    if dt is None:
        row = _curation_start_row(dataset_id)
        dt = parse_date(row.get("publication_date")) if row else None

    _cache_first_published(dataset_id, dt)
    return dt

def _reconciliation_row(dataset_id):
    # keyed by node_id; header keys stripped (the source has a trailing space on "scaffold ")
    global _reconciliation_rows

    if _reconciliation_rows is None:
        _reconciliation_rows = {}
        try:
            with open(RECONCILIATION_SOURCE, encoding="utf-8-sig") as f:
                for raw in csv.DictReader(f):
                    row = {(key or "").strip(): value for key, value in raw.items()}
                    node_id = (row.get("node_id") or "").strip()
                    if node_id:
                        _reconciliation_rows[node_id] = row
        except FileNotFoundError:
            pass

    return _reconciliation_rows.get(normalize_dataset_id(dataset_id))


def dataset_type(dataset_id):
    row = _reconciliation_row(dataset_id)
    return (row.get("dataset_type") or "").strip() if row else ""


def is_scaffold(dataset_id):
    row = _reconciliation_row(dataset_id)
    return bool(row) and (row.get("scaffold") or "").strip().lower() == "yes"


def is_excluded_computational(dataset_id):
    return dataset_type(dataset_id) == "computational" and is_scaffold(dataset_id)


def doi_v1(dataset_id):
    row = _reconciliation_row(dataset_id)
    return (row.get("DOI V1") or "").strip() if row else ""


def reconciliation_publication_year(dataset_id):
    row = _reconciliation_row(dataset_id)
    if not row:
        return None
    value = (row.get("publication_year") or "").strip()
    return int(value) if value.isdigit() else None


with open("./error-info.json") as _ef:
    _error_info = {entry["id"]: (entry["description"], entry["format"]) for entry in json.load(_ef)}


def is_excluded_error_type(error_type):
    # Excluded if the error path excluded or error map marks Excluded?
    if error_type.split(":", 1)[0].startswith(EXCLUDED_PATH_PREFIXES):
        return True
    return get_error_id(error_type) in EXCLUDED_IDS


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
    if c is None:
        return 0
    for k, _ in c:
        if is_excluded_error_type(k):
            del c[k]
    return len(c)
    #return sum(c.values()) if c else 0


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
    """Error types at the export nearest `target_ts`; prefer the latest export
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
    """True if no curation export has an 'updated' timestamp at or before event_dt"""
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
    # last export whose effective ts is at or before the event (matches the matrix's
    # nearest_index; among equal effective ts, keep the latest export)
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

    return str(pairs[pos][1])


def effective_export_ts_by_key(dataset_record):
    # effective (updated) export timestamp keyed by str(export unix_timestamp)
    return {str(start): eff for eff, start in _effective_export_pairs(dataset_record)}


def error_types_near_effective(dataset_record, event_dt):
    if event_dt is None:
        return None
    
    key = nearest_export_key_effective(dataset_record, int(event_dt.timestamp()))
    
    if key is None:
        return None
    
    return _positive_error_counts((dataset_record.get("error_graph") or {}).get(key))
