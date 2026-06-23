import difflib
import json
import os
import re
from collections import Counter, defaultdict

IN = "./pennsieve-event-data-2026-05-12T020310Z.json"
OUT = "./curator_event_categories.json"

CURATORS = {
    589: "Tom",
    832: "Anka",
    1554: "Anka (alt)",
    1186: "Marlena",
    531: "Anita",
    600: "Jeff",
    601: "Jeff (ncmir)",
    611: "Maryann",
}

KNOWN_EXTENSIONS = {
    "tif", "tiff", "jpg", "jpeg", "jp2", "jpx", "png", "gif", "bmp", "svg",
    "czi", "lsm", "nd2", "ims", "ima", "oib", "oif", "lif", "vsi", "ndpi",
    "xlsx", "xls", "csv", "tsv", "txt", "json", "xml", "docx", "doc", "pdf",
    "rtf", "md", "dat", "mat", "h5", "hdf5", "nwb", "npy", "npz", "db",
    "sqlite", "ini", "cfg", "log", "results", "pss", "psmethod", "txe", "ext",
    "avi", "mp4", "mov", "mkv", "wav", "mp3", "zip", "gz", "tar", "rar", "7z",
    "py", "m", "r", "ipynb", "sh", "yaml", "yml", "abf", "smr", "edf",
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

TEXT_METADATA_FIELDS = {
    "UPDATE_README": ("oldReadme", "newReadme"),
    "UPDATE_DESCRIPTION": ("oldDescription", "newDescription"),
    "UPDATE_NAME": ("oldName", "newName"),
    "UPDATE_CHANGELOG": ("oldChangelog", "newChangelog"),
    "UPDATE_LICENSE": ("oldLicense", "newLicense"),
    "UPDATE_BANNER_IMAGE": ("oldBanner", "newBanner"),
}

NORMALIZE_RE = re.compile(r"\s+")
DIFF_CHAR_LIMIT = 20000


def is_sds_name(name):
    name = (name or "").strip()
    return bool(SDS_ENTITY_RE.match(name) or SDS_RESERVED_RE.match(name))


def split_ext(name):
    if not name:
        return name or "", ""
    
    base = os.path.basename(name)
    
    if "." in base:
        stem, candidate = base.rsplit(".", 1)
        if candidate.lower() in KNOWN_EXTENSIONS:
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


def _normalize_text(text):
    return NORMALIZE_RE.sub(" ", text or "").strip().lower()


def metadata_edit_stats(event_type, detail):
    keys = TEXT_METADATA_FIELDS.get(event_type)
    if not keys or not isinstance(detail, dict):
        return None
    old = detail.get(keys[0], "") or ""
    new = detail.get(keys[1], "") or ""
    trivial = _normalize_text(old) == _normalize_text(new)
    magnitude = 1.0 - difflib.SequenceMatcher(None, old[:DIFF_CHAR_LIMIT], new[:DIFF_CHAR_LIMIT]).ratio()
    return trivial, magnitude


EVENT_MAP = {
    "CREATE_PACKAGE": ("File Structure", "Create"),
    # "DELETE_PACKAGE": ("File Structure", "Delete"),
    "MOVE_PACKAGE": ("File Structure", "Move"),
    "RENAME_PACKAGE": ("File Structure", "Rename"), 
    "RESTORE_PACKAGE": ("File Structure", "Restore"),
    # split out per-file (such as manifests, subjects, samples, metadata, readme)
    # split metadata edits by readme, title, names/contributors, keywords/tags
    # exclude subject changes
    # normalize by number of datasets/publication events in a single year
    # fix at pub events; includes datasets never published
    # fix at publication graph; need to change bins to be  publicaiton year
    # new figure: ranking of frequent error types
    # for error types do 0 or 1 existence, finding top errors across all datasets
        # for reference; exclude Converter not implemented, Manifest errors
    # exclude post-first publications on any dataset with multiple publications
        # put those subsequent publications (where they exist) into copies of the current figures
    # need updated attrition rate; number of submission in a given year plotted against whether any of the datasets submitted ever published
    # 2022 = feb 2022-feb2023; need to get years on this scale
    
    "UPDATE_README": ("Metadata", "README"),
    "UPDATE_NAME": ("Metadata", "Dataset Name"),
    "UPDATE_DESCRIPTION": ("Metadata", "Description"),
    "UPDATE_CHANGELOG": ("Metadata", "Changelog"),
    "UPDATE_LICENSE": ("Metadata", "License"),
    "UPDATE_BANNER_IMAGE": ("Metadata", "Banner"),

    "UPDATE_METADATA": ("Uncharacterized", "Metadata Blob"),
    "UPDATE_IGNORE_FILES": ("Uncharacterized", "Ignore Files"),
    "ADD_TAG": ("Metadata", "Add Tag"),
    "REMOVE_TAG": ("Metadata", "Remove Tag"),

    "ADD_CONTRIBUTOR": ("Contributors", "Add"),
    "REMOVE_CONTRIBUTOR": ("Contributors", "Remove"),

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
        kind = "Folder" if is_folder(detail) else "File"
        return category, f"{subcat} {kind}"
    
    return category, subcat


def main():
    with open(IN, "r", encoding="utf-8") as f:
        data = json.load(f)

    by_category = defaultdict(Counter)          # category -> subcat -> count
    by_event_type = Counter()                   # raw eventType -> count
    by_curator = defaultdict(Counter)           # curator name -> category -> count
    by_curator_total = Counter()
    extension_activity = defaultdict(Counter)    # category -> ext -> count
    per_dataset = defaultdict(Counter)          # dataset_id -> category -> count
    meta_stats = defaultdict(lambda: {"substantive": 0, "trivial": 0, "magnitude_sum": 0.0})
    per_dataset_meta = defaultdict(lambda: {"substantive_edits": 0, "trivial_edits": 0, "magnitude_sum": 0.0})

    total_events = 0
    curator_events = 0

    for dataset_id, event_data in data.items():
        for group in event_data.get("eventGroups", []):
            for ev in group.get("events", [group.get("event")]):
                if ev is None:
                    continue
                total_events += 1
                uid = ev.get("userId")
                if uid not in CURATORS:
                    continue
                curator_events += 1

                et = ev.get("eventType", "UNKNOWN")
                detail = ev.get("detail") or {}
                category, subcat = subcategorize(et, detail)

                stats = metadata_edit_stats(et, detail)
                if stats is not None:
                    trivial, magnitude = stats
                    base_subcat = subcat
                    subcat = f"{subcat} ({'Trivial' if trivial else 'Substantive'})"
                    ms = meta_stats[base_subcat]
                    pdm = per_dataset_meta[dataset_id]
                    
                    if trivial:
                        ms["trivial"] += 1
                        pdm["trivial_edits"] += 1
                    else:
                        ms["substantive"] += 1
                        ms["magnitude_sum"] += magnitude
                        pdm["substantive_edits"] += 1
                        pdm["magnitude_sum"] += magnitude

                by_category[category][subcat] += 1
                by_event_type[et] += 1
                curator_name = CURATORS[uid]
                by_curator[curator_name][category] += 1
                by_curator_total[curator_name] += 1
                per_dataset[dataset_id][category] += 1

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
            "datasets_touched_by_curators": len(per_dataset),
        },
        "by_category": {c: dict(sc.most_common()) for c, sc in by_category.items()},
        "by_event_type": dict(by_event_type.most_common()),
        "by_curator": {
            name: {"total": by_curator_total[name], "by_category": dict(cats.most_common())}
            for name, cats in by_curator.items()
        },
        "file_extension_activity": {c: dict(e.most_common()) for c, e in extension_activity.items()},
        "metadata_churn": {
            base: {
                "substantive": v["substantive"],
                "trivial": v["trivial"],
                "mean_substantive_magnitude": (
                    round(v["magnitude_sum"] / v["substantive"], 4) if v["substantive"] else 0.0
                ),
            }
            for base, v in meta_stats.items()
        },
        "per_dataset": {ds: dict(cats.most_common()) for ds, cats in per_dataset.items()},
        "per_dataset_metadata_churn": {
            ds: {
                "substantive_edits": v["substantive_edits"],
                "trivial_edits": v["trivial_edits"],
                "total_magnitude": round(v["magnitude_sum"], 4),
            }
            for ds, v in per_dataset_meta.items()
        },
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"All Events:      {total_events:>9}")
    print(f"Curator Events:  {curator_events:>9}")
    print(f"Datasets Touched: {len(per_dataset):>9}")
    print(f"\nwrote categorized output -> {OUT}\n")

    print("> Events by category / Subcategory <")
    cat_totals = {c: sum(sc.values()) for c, sc in by_category.items()}
    for category in sorted(cat_totals, key=cat_totals.get, reverse=True):
        print(f"\n{category}  ({cat_totals[category]})")
        for subcat, n in by_category[category].most_common():
            print(f"    {n:>8}  {subcat}")

    print("\n> Metadata churn (substantive vs trivial, mean magnitude) <")
    for base in sorted(meta_stats, key=lambda b: meta_stats[b]["substantive"], reverse=True):
        v = meta_stats[base]
        mean_mag = v["magnitude_sum"] / v["substantive"] if v["substantive"] else 0.0
        print(f"    {base:<12} substantive={v['substantive']:>5}  trivial={v['trivial']:>5}  mean_mag={mean_mag:.3f}")

    print("\n> Events by curator <")
    for name, total in by_curator_total.most_common():
        print(f"    {total:>8}  {name}")


if __name__ == "__main__":
    main()
