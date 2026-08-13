import datetime
import json
import os
import re
from collections import Counter, defaultdict

IN = "./pennsieve-event-data-2026-05-12T020310Z.json"
OUT = "./curator_event_categories.json"
EVENT_SERIES = "./pennsieve_event_series.json"


def parse_iso8601(value):
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def fiscal_year(dt):
    # Feb 1 boundary (matches report_common): January belongs to the prior year
    return None if dt is None else dt.year if dt.month >= 2 else dt.year - 1


def complete_curation_windows(event_series):
    # per-dataset [request, accept] spans for complete (non-incomplete) cycles
    windows = {}
    for dataset_id, cycles in event_series.items():
        spans = []
        for cycle in cycles:
            if cycle.get("incomplete"):
                continue
            req = parse_iso8601(cycle.get("request_created"))
            acc = parse_iso8601(cycle.get("accept_created"))
            if req and acc:
                spans.append((req, acc))
        if spans:
            windows[dataset_id] = spans
    return windows

CURATORS = {
    589: "Tom",
    832: "Anka",
    1554: "Anka (alt)",
    1186: "Marlena",
    # 531: "Anita",
    # 600: "Jeff",
    601: "Jeff (ncmir)",
    # 611: "Maryann",
}

# RENAME_PACKAGE fixes to SDS format
SDS_ENTITY_RE = re.compile(
    r"^(sub|sam|perf|pool|site|specimen|aff|proc|sourcedata)-", re.IGNORECASE
)
SDS_RESERVED_RE = re.compile(
    r"^(primary|derivative|source|sourcedata|code|docs|protocol|stimulation)$"
    r"|^(dataset_description|subjects|samples|submission|manifest|performances|"
    r"resources|README|CHANGES|code_description)(\.\w+)?$",
    re.IGNORECASE,
)

# Reserved SDS file -> grammatical label, for per-file splitting of File Structure events
RESERVED_FILE_KINDS = (
    ("manifest", "Manifest"),
    ("subjects", "Subjects"),
    ("samples", "Samples"),
    ("dataset_description", "Dataset Description"),
    ("readme", "README"),
)

# file operations on these SDS metadata files -> "Metadata File Operations" category
METADATA_FILE_STEMS = {
    "dataset_description", "subjects", "samples", "sites",
    "performances", "code_description", "submission", "curation",
}

# Records + models where model is auto-generated subject/sample metadata
SUBJECT_SAMPLE_MODEL_RE = re.compile(r"subject|sample", re.IGNORECASE)


def reserved_file_kind(name):
    """Return a grammatical reserved-file label for a package name, or None."""
    if not name:
        return None
    stem = os.path.basename(name).strip().lower()
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    for needle, label in RESERVED_FILE_KINDS:
        if stem == needle:
            return label
    return None


def is_sds_name(name):
    name = (name or "").strip()
    return bool(SDS_ENTITY_RE.match(name) or SDS_RESERVED_RE.match(name))


def is_metadata_file(name):
    """True for SDS metadata files: the named .xlsx metadata files, any *manifest.xlsx,
    or anything starting with README."""
    if not name:
        return False
    base = os.path.basename(str(name)).strip().lower()
    if base.startswith("readme"):
        return True
    if base.endswith("manifest.xlsx"):
        return True
    stem = base.rsplit(".", 1)[0] if "." in base else base
    return stem in METADATA_FILE_STEMS


def split_ext(name):
    if not name:
        return name or "", ""
    
    base = os.path.basename(name)
    
    if "." in base:
        stem, candidate = base.rsplit(".", 1)
        return stem, candidate.lower()
    
    return base, ""


def categorize_rename(detail):
    old = detail.get("oldName", "") or ""
    new = detail.get("newName", "") or ""
    _, eo = split_ext(old)
    _, en = split_ext(new)

    if eo != en:
        if not eo and en:
            return "Add Extension"
        if eo and not en:
            return "Remove Extension"
        return "Change Extension"
    if old == new:
        return "No-op"
    if old.lower() == new.lower():
        return "Case Only"
    if old.strip() == new.strip():
        return "Whitespace Only"
    if is_sds_name(new):
        return "To SDS Entity"
    return "Other Rename"


def is_folder(detail):
    node = detail.get("nodeId", "") or ""
    return node.startswith("N:collection:")


EVENT_MAP = {
    "CREATE_PACKAGE": ("File Organization", "Create"),
    # "DELETE_PACKAGE": ("File Organization", "Delete"),
    "MOVE_PACKAGE": ("File Organization", "Move"),
    "RENAME_PACKAGE": ("File Organization", "Rename"),
    "RESTORE_PACKAGE": ("File Organization", "Restore"),
    "UPDATE_IGNORE_FILES": ("File Organization", "Ignore Files"),

    "UPDATE_README": ("Descriptive Metadata", "README"),
    "UPDATE_NAME": ("Descriptive Metadata", "Title"),
    "UPDATE_DESCRIPTION": ("Descriptive Metadata", "Description"),
    "UPDATE_CHANGELOG": ("Descriptive Metadata", "Changelog"),
    "UPDATE_BANNER_IMAGE": ("Descriptive Metadata", "Banner"),
    "ADD_TAG": ("Descriptive Metadata", "Keywords & Tags"),
    "REMOVE_TAG": ("Descriptive Metadata", "Keywords & Tags"),
    
    "UPDATE_LICENSE": ("Related Identifiers", "License"),
    "ADD_COLLECTION": ("Related Identifiers", "Add"),
    "REMOVE_COLLECTION": ("Related Identifiers", "Remove"),
    "ADD_EXTERNAL_PUBLICATION": ("Related Identifiers", "Add"),
    "REMOVE_EXTERNAL_PUBLICATION": ("Related Identifiers", "Remove"),

    "UPDATE_METADATA": ("Descriptive Metadata", "Metadata Blob"),

    "ADD_CONTRIBUTOR": ("Contributors", "Names & Contributors"),
    "REMOVE_CONTRIBUTOR": ("Contributors", "Names & Contributors"),


    "UPDATE_STATUS": ("Publication Workflow", "Status Change"),
    # "REQUEST_PUBLICATION": ("Publication Workflow", "Publication Request"),
    "ACCEPT_PUBLICATION": ("Publication Workflow", "Publication Accept"),
    "REJECT_PUBLICATION": ("Publication Workflow", "Publication Reject"),
    # "CANCEL_PUBLICATION": ("Publication Workflow", "Publication Cancel"),
    # "REQUEST_EMBARGO": ("Publication Workflow", "Embargo Request"),
    "ACCEPT_EMBARGO": ("Publication Workflow", "Embargo Accept"),
    "REJECT_EMBARGO": ("Publication Workflow", "Embargo Reject"),
    # "CANCEL_EMBARGO": ("Publication Workflow", "Embargo Cancel"),
    # "REQUEST_REVISION": ("Publication Workflow", "Revision Request"),
    "ACCEPT_REVISION": ("Publication Workflow", "Revision Accept"),
    "REJECT_REVISION": ("Publication Workflow", "Revision Reject"),
    # "REQUEST_REMOVAL": ("Publication Workflow", "Removal Request"),
    "ACCEPT_REMOVAL": ("Publication Workflow", "Removal Accept"),
    "REJECT_REMOVAL": ("Publication Workflow", "Removal Reject"),

    "UPDATE_PERMISSION": ("Publication Workflow", "Permission Change"),
    "UPDATE_OWNER": ("Publication Workflow", "Ownership Change"),

    # "CREATE_DATASET": ("Dataset Creation", "Create"),
    # "CREATE_RECORD": ("Records & Models", "Create Record"),
    # "UPDATE_RECORD": ("Records & Models", "Update Record"),
    # "DELETE_RECORD": ("Records & Models", "Delete Record"),
    # "CREATE_MODEL": ("Records & Models", "Create Model"),
    # "CREATE_MODEL_PROPERTY": ("Records & Models", "Create Model Property"),
}


def subcategorize(event_type, detail):
    category, subcat = EVENT_MAP.get(event_type, ("Other", event_type.replace("_", " ").title()))
    
    if not isinstance(detail, dict):
        return category, subcat

    if event_type == "RENAME_PACKAGE":
        if is_metadata_file(detail.get("newName")) or is_metadata_file(detail.get("oldName")):
            category = "Metadata File Operations"
        return category, f"Rename: {categorize_rename(detail)}"
    if event_type in ("CREATE_PACKAGE", "DELETE_PACKAGE", "MOVE_PACKAGE", "RESTORE_PACKAGE"):
        reserved = reserved_file_kind(detail.get("name"))
        if reserved:
            kind = reserved
        else:
            kind = "Folder" if is_folder(detail) else "File"
        if is_metadata_file(detail.get("name")):
            category = "Metadata File Operations"
        return category, f"{subcat} {kind}"

    return category, subcat


RECORD_MODEL_EVENTS = {
    "CREATE_MODEL",
    "CREATE_MODEL_PROPERTY",
    "CREATE_RECORD",
    "UPDATE_RECORD",
    "DELETE_RECORD",
}


def build_model_name_map(event_data):
    """Map model uuid -> model name from CREATE_MODEL events in a dataset."""
    model_names = {}
    for group in event_data.get("eventGroups", []):
        for ev in group.get("events", [group.get("event")]):
            if ev is None or ev.get("eventType") != "CREATE_MODEL":
                continue
            detail = ev.get("detail") or {}
            mid = detail.get("id")
            name = detail.get("name")
            if mid and name:
                model_names[mid] = name
    return model_names


def is_subject_sample_event(event_type, detail, model_names):
    """True for auto-generated subject/sample record/model events to be excluded."""
    if event_type not in RECORD_MODEL_EVENTS or not isinstance(detail, dict):
        return False
    if event_type == "CREATE_MODEL":
        name = detail.get("name") or ""
    elif event_type == "CREATE_MODEL_PROPERTY":
        name = detail.get("modelName") or ""
    else:
        name = model_names.get(detail.get("modelId"), "")
    return bool(SUBJECT_SAMPLE_MODEL_RE.search(name))


def main():
    with open(IN, "r", encoding="utf-8") as f:
        data = json.load(f)

    with open(EVENT_SERIES, "r", encoding="utf-8") as f:
        windows = complete_curation_windows(json.load(f))

    by_category = defaultdict(Counter)          # category -> subcat -> count
    by_event_type = Counter()                   # raw eventType -> count
    by_curator = defaultdict(Counter)           # curator name -> category -> count
    by_curator_total = Counter()
    extension_activity = defaultdict(Counter)    # category -> ext -> count
    per_dataset = defaultdict(Counter)          # dataset_id -> category -> count
    per_dataset_metadata = defaultdict(Counter)  # dataset_id -> metadata subcat -> count
    category_year_in_window = defaultdict(Counter)  # category -> fiscal year -> count (in complete curation windows)

    total_events = 0
    curator_events = 0
    excluded_subject_sample = 0

    for dataset_id, event_data in data.items():
        model_names = build_model_name_map(event_data)
        for group in event_data.get("eventGroups", []):
            for ev in group.get("events", [group.get("event")]):
                if ev is None:
                    continue
                total_events += 1
                uid = ev.get("userId")
                if uid not in CURATORS:
                    continue

                et = ev.get("eventType", "UNKNOWN")
                detail = ev.get("detail") or {}

                # Skip auto-generated subject/sample records/models entirely
                if is_subject_sample_event(et, detail, model_names):
                    excluded_subject_sample += 1
                    continue

                curator_events += 1
                category, subcat = subcategorize(et, detail)

                if category == "Other":
                    continue
                
                by_category[category][subcat] += 1
                by_event_type[et] += 1
                curator_name = CURATORS[uid]
                by_curator[curator_name][category] += 1
                by_curator_total[curator_name] += 1
                per_dataset[dataset_id][category] += 1
                if category == "Metadata":
                    per_dataset_metadata[dataset_id][subcat] += 1

                # event-year category mix, restricted to events inside a complete curation window
                created = parse_iso8601(ev.get("createdAt"))
                spans = windows.get(dataset_id)
                if created is not None and spans and any(start <= created <= end for start, end in spans):
                    category_year_in_window[category][fiscal_year(created)] += 1

                if et in ["CREATE_PACKAGE", "DELETE_PACKAGE", "MOVE_PACKAGE"]:
                    name = detail.get("name") if isinstance(detail, dict) else None
                    _, ext = split_ext(name or "")
                    extension_activity[category][ext or "<folder/none>"] += 1

    output = {
        "source": IN,
        "curator_ids": CURATORS,
        "totals": {
            "all_events": total_events,
            "curator_events": curator_events,
            "excluded_subject_sample_events": excluded_subject_sample,
            "datasets_touched_by_curators": len(per_dataset),
        },
        "by_category": {c: dict(sc.most_common()) for c, sc in by_category.items()},
        "category_by_event_year_in_window": {
            category: {str(year): count for year, count in sorted(years.items()) if year is not None}
            for category, years in category_year_in_window.items()
        },
        "by_event_type": dict(by_event_type.most_common()),
        "by_curator": {
            name: {"total": by_curator_total[name], "by_category": dict(cats.most_common())}
            for name, cats in by_curator.items()
        },
        "file_extension_activity": {c: dict(e.most_common()) for c, e in extension_activity.items()},
        "per_dataset": {ds: dict(cats.most_common()) for ds, cats in per_dataset.items()},
        "per_dataset_metadata": {ds: dict(sc.most_common()) for ds, sc in per_dataset_metadata.items()},
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"All Events:      {total_events:>9}")
    print(f"Curator Events:  {curator_events:>9}")
    print(f"Excluded Subj/Sample: {excluded_subject_sample:>9}")
    print(f"Datasets Touched: {len(per_dataset):>9}")
    print(f"\nwrote categorized output -> {OUT}\n")

    print("> Events by category / Subcategory <")
    cat_totals = {c: sum(sc.values()) for c, sc in by_category.items()}
    for category in sorted(cat_totals, key=cat_totals.get, reverse=True):
        print(f"\n{category}  ({cat_totals[category]})")
        for subcat, n in by_category[category].most_common():
            print(f"    {n:>8}  {subcat}")

    print("\n> Events by curator <")
    for name, total in by_curator_total.most_common():
        print(f"    {total:>8}  {name}")


if __name__ == "__main__":
    main()
