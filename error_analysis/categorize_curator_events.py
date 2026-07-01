import json
import os
import re
from collections import Counter, defaultdict

IN = "./pennsieve-event-data-2026-05-12T020310Z.json"
OUT = "./curator_event_categories.json"

CURATORS = {
    # 589: "Tom",
    832: "Anka",
    1554: "Anka (alt)",
    1186: "Marlena",
    531: "Anita",
    # 600: "Jeff",
    # 601: "Jeff (ncmir)",
    611: "Maryann",
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
    "CREATE_PACKAGE": ("File Structure", "Create"),
    # "DELETE_PACKAGE": ("File Structure", "Delete"),
    "MOVE_PACKAGE": ("File Structure", "Move"),
    "RENAME_PACKAGE": ("File Structure", "Rename"),
    "RESTORE_PACKAGE": ("File Structure", "Restore"),

    "UPDATE_README": ("Metadata", "README"),
    "UPDATE_NAME": ("Metadata", "Title"),
    "UPDATE_DESCRIPTION": ("Metadata", "Description"),
    "UPDATE_CHANGELOG": ("Metadata", "Changelog"),
    "UPDATE_LICENSE": ("Metadata", "License"),
    "UPDATE_BANNER_IMAGE": ("Metadata", "Banner"),

    "UPDATE_METADATA": ("Uncharacterized", "Metadata Blob"),
    "UPDATE_IGNORE_FILES": ("Uncharacterized", "Ignore Files"),
    "ADD_TAG": ("Metadata", "Keywords & Tags"),
    "REMOVE_TAG": ("Metadata", "Keywords & Tags"),

    "ADD_CONTRIBUTOR": ("Metadata", "Names & Contributors"),
    "REMOVE_CONTRIBUTOR": ("Metadata", "Names & Contributors"),

    "ADD_EXTERNAL_PUBLICATION": ("External Publications", "Add"),
    "REMOVE_EXTERNAL_PUBLICATION": ("External Publications", "Remove"),

    "ADD_COLLECTION": ("Collections", "Add"),
    "REMOVE_COLLECTION": ("Collections", "Remove"),

    "CREATE_RECORD": ("Records & Models", "Create Record"),
    "UPDATE_RECORD": ("Records & Models", "Update Record"),
    "DELETE_RECORD": ("Records & Models", "Delete Record"),
    "CREATE_MODEL": ("Records & Models", "Create Model"),
    "CREATE_MODEL_PROPERTY": ("Records & Models", "Create Model Property"),

    "UPDATE_STATUS": ("Publication Lifecycle", "Status Change"),
    "REQUEST_PUBLICATION": ("Publication Lifecycle", "Publication Request"),
    "ACCEPT_PUBLICATION": ("Publication Lifecycle", "Publication Accept"),
    "REJECT_PUBLICATION": ("Publication Lifecycle", "Publication Reject"),
    "CANCEL_PUBLICATION": ("Publication Lifecycle", "Publication Cancel"),
    "REQUEST_EMBARGO": ("Publication Lifecycle", "Embargo Request"),
    "ACCEPT_EMBARGO": ("Publication Lifecycle", "Embargo Accept"),
    "REJECT_EMBARGO": ("Publication Lifecycle", "Embargo Reject"),
    "CANCEL_EMBARGO": ("Publication Lifecycle", "Embargo Cancel"),
    "REQUEST_REVISION": ("Publication Lifecycle", "Revision Request"),
    "ACCEPT_REVISION": ("Publication Lifecycle", "Revision Accept"),
    "REJECT_REVISION": ("Publication Lifecycle", "Revision Reject"),
    "REQUEST_REMOVAL": ("Publication Lifecycle", "Removal Request"),
    "ACCEPT_REMOVAL": ("Publication Lifecycle", "Removal Accept"),
    "REJECT_REMOVAL": ("Publication Lifecycle", "Removal Reject"),

    "UPDATE_PERMISSION": ("Permissions & Ownership", "Permission Change"),
    "UPDATE_OWNER": ("Permissions & Ownership", "Ownership Change"),

    "CREATE_DATASET": ("Dataset Creation", "Create"),
}


def subcategorize(event_type, detail):
    category, subcat = EVENT_MAP.get(event_type, ("Other", event_type.replace("_", " ").title()))
    
    if not isinstance(detail, dict):
        return category, subcat

    if event_type == "RENAME_PACKAGE":
        return category, f"Rename: {categorize_rename(detail)}"
    if event_type in ("CREATE_PACKAGE", "DELETE_PACKAGE", "MOVE_PACKAGE", "RESTORE_PACKAGE"):
        reserved = reserved_file_kind(detail.get("name"))
        if reserved:
            kind = reserved
        else:
            kind = "Folder" if is_folder(detail) else "File"
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

    by_category = defaultdict(Counter)          # category -> subcat -> count
    by_event_type = Counter()                   # raw eventType -> count
    by_curator = defaultdict(Counter)           # curator name -> category -> count
    by_curator_total = Counter()
    extension_activity = defaultdict(Counter)    # category -> ext -> count
    per_dataset = defaultdict(Counter)          # dataset_id -> category -> count
    per_dataset_metadata = defaultdict(Counter)  # dataset_id -> metadata subcat -> count

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

                by_category[category][subcat] += 1
                by_event_type[et] += 1
                curator_name = CURATORS[uid]
                by_curator[curator_name][category] += 1
                by_curator_total[curator_name] += 1
                per_dataset[dataset_id][category] += 1
                if category == "Metadata":
                    per_dataset_metadata[dataset_id][subcat] += 1

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
