import csv
import datetime
import glob
import json
import os
import re

from dateutil import parser as dateutil_parser

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

with open("./SPARC_error_map.csv") as f:
    for row in csv.DictReader(f):
        INCLUDED_ERROR_FORMATS.append(row.get("Match Key (verbatim)", ""))
        ERROR_DICTIONARY.append(row)

# error map (SPARC_error_map.csv) resolution: stored error_graph key -> canonical #
# Rows collapse via `colaps to` (points at the canonical `#`). A stored key resolves
# by its tag signature, or by matching the canonical row's Error Title, Type, Match
# Key, or Legacy Title.
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

# exclusion is driven by the canonical row's own Excluded? flag
for num, row in _error_map_rows.items():
    if _canonical_num(row) == num and (row.get("Excluded?") or "").strip().lower() == "yes":
        EXCLUDED_IDS.add(num)


def _title_of(error_type):
    """Recover the stored title: drop the `path:` prefix and any tag suffix."""
    after = error_type.split(":", 1)[1] if ":" in error_type else error_type
    after = re.split(r" (regex|required|expected_type|allowed)\(", after)[0]
    return after.strip()


def get_error_id(error_type):
    """Canonical error-map `#` for a stored error_graph key ('' if unresolved).
    Tag-aware: a tag signature resolves to the field/type-specific row first,
    otherwise falls back to the base title."""
    signature = _tag_signature(error_type)

    if signature is not None and signature in TAG_TO_ID:
        return TAG_TO_ID[signature]

    return TITLE_TO_ID.get(_title_of(error_type), "")


def get_canonical_title(error_type):
    """Canonical error-map Error Title for a stored key (falls back to raw title)."""
    signature = _tag_signature(error_type)

    if signature is not None and signature in TAG_TO_CANON:
        return TAG_TO_CANON[signature]

    title = _title_of(error_type)
    return TITLE_TO_CANON.get(title, title)


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


def parse_date(value):
    """Generalized/lenient date parse for hand-verified values: accepts datetime
    objects, ISO8601 strings, and free-form strings ('around 1/15/2019',
    '12/21/2020'). Naive results are treated as UTC. None when nothing parses."""
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


_true_submission_dates = None


def _curation_start_source():
    """Prefer the newest hand-verified export (curation_start_dates_verified*.csv),
    else the computed curation_start_dates.csv."""
    verified = glob.glob("./curation_start_dates_verified*.csv")
    if verified:
        return max(verified, key=os.path.getmtime)
    return "./curation_start_dates.csv"


def true_submission_date(dataset_id):
    """'True' submission date for a dataset's first publication cycle, from the
    verified export (falling back to the computed csv). Parsed leniently, so
    hand-entered values in mixed formats still resolve. None if absent."""
    global _true_submission_dates

    if _true_submission_dates is None:
        _true_submission_dates = {}
        try:
            # utf-8-sig strips the BOM Excel prepends on CSV export
            with open(_curation_start_source(), encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    value = (row.get("true_submission_date") or "").strip()
                    if value:
                        _true_submission_dates[row["dataset_id"]] = value
        except FileNotFoundError:
            pass

    return parse_date(_true_submission_dates.get(dataset_id))


with open("./error-info.json") as _ef:
    _error_info = {entry["id"]: (entry["description"], entry["format"]) for entry in json.load(_ef)}


def is_excluded_error_type(error_type):
    # Exclusion is driven entirely by the error map's Excluded? column: resolve the
    # stored key to its canonical map #, then check that # against EXCLUDED_IDS.
    # Unresolved keys (id == "") are never excluded.
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
    """True if no curation export has an 'updated' timestamp at or before event_dt
    -- the nearest export postdates the event, so its snapshot can't represent the
    state then. No exports or a None event count as "after"."""
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
