# This file was created in large part with GitHub Copilot

import csv
import datetime
import json
from collections import Counter, defaultdict

import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


TEMPORAL_REPORT = "./temporal_report.json"
EVENT_SEQUENCES = "./pennsieve_event_series.json"
STATUS_DELIMITED_SEQUENCES = "./pennsieve_status_delimited.json"
SPARCUR_UPDATES = "./sparcur_updates.csv"
CURATION_CLUSTERS = "./pennsieve_curation_clusters.json"
CURATOR_CATEGORIES = "./curator_event_categories.json"

CURATOR_IDS = {
    # 589, 
    832, 
    1554, 
    1186, 
    531, 
    # 600, 
    # 601, 
    611
}

# Whether to use error_index_graph or error_graph for Metric 1
USE_ERROR_INDEX_GRAPH = True

EXCLUDED_DATASET_IDS = []
WHITELIST_DATASET_IDS = []

# we should look over the categorization code; particularly metadata and add/remove_contributor
# what about styling by the way?
# metadata type mix: would be helpful to havae n=X metrics per year; same for event mix

# also need to ask: is my collect() function double counting?


# + ignore all errors that path from #/inputs/
# + need to separate errors by path
    # + put the last two errors in dropped_errors.txt into the slack under no idea
    # + errors that don't have a path?
    # + null path errors get grouped under "this occured with no path"
# + exclude all missing required tsrXb_ABC errors

# + april 1st 2022 - april 1st 2026 for errors
    # check if this loses events
# + make a table of errors X datasets; 1 or 0 on existence to make a frequency table
    # separate datasets by template version when we add that data...
    
# should I remove dataset/org ids from the files? for OSINT purposes?

with open("./dataset_exclusion_list.csv") as f:
    for row in csv.DictReader(f):
        EXCLUDED_DATASET_IDS.append(row["Dataset ID"])

with open("./big-did.json") as f:
    SPARC_ORGANIZATION = "organization:618e8dd9-f8d2-4dc4-9abb-c6aaab2e78a0"
    
    data = json.load(f)
    for id, entry in data.items():
        if entry["id_organization"] == SPARC_ORGANIZATION:
            WHITELIST_DATASET_IDS.append(id)


print(f"Loaded {len(EXCLUDED_DATASET_IDS)} excluded datasets and {len(WHITELIST_DATASET_IDS)} whitelisted datasets.")

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
    _error_info = {entry["id"]: entry["description"] for entry in json.load(_ef)}
EXCLUDED_ERROR_DESCRIPTIONS = [
    _error_info[i] for i in (9, 132, 16, 89, 90, 23, 24, 25, 26, 39, 40, 41, 67, 106, 131, 129)
] # see error-info.json
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
    "JSON value value is of incorrect type expected_type(array)"
]


def is_excluded_error_type(error_type):
    return any(
        error_type == base or error_type.startswith(base + " ")
        for base in EXCLUDED_ERROR_DESCRIPTIONS
    ) or any(error_type == et for et in EXCLUDED_ERROR_TYPES) \
        or "inputs/" in error_type


def drop_excluded_error_types(error_types):
    """Filter out Converter/Manifest noise classes from an error-type dict."""
    if not error_types:
        return error_types
    return {t: c for t, c in error_types.items() if not is_excluded_error_type(t)}


def format_datetime(value):
    if not value:
        return "N/A"
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    return str(value)


def first_publication_date(dataset_id, event_sequences):
    events = event_sequences.get(dataset_id)
    if not events:
        return None
    return parse_iso8601(events[0].get("accept_created"))


def publication_dates(dataset_id, event_sequences):
    events = event_sequences.get(dataset_id) or []
    dates = [parse_iso8601(event.get("accept_created")) for event in events]
    return sorted(date for date in dates if date)


def first_request_date(dataset_id, event_sequences):
    min_date = datetime.datetime(2022, 4, 1, tzinfo=datetime.timezone.utc)
    
    events = event_sequences.get(dataset_id)
    
    if not events:
        return None

    request_dates = [parse_iso8601(event.get("request_created")) for event in events]
    request_dates = [request_date for request_date in request_dates if request_date and request_date >= min_date]
    
    if not request_dates:
        return None

    return min(request_dates)


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
        # Request predates the first export: use the earliest export after it.
        chosen = items[0][1]

    return _positive_error_counts(chosen)


def plot_error_types_by_year(records, title, normalize=False):
    if not records:
        return

    df = pd.DataFrame(records)
    df = df.groupby(["year", "type"]) ["count"].sum().reset_index()
    top_types = (
        df.groupby("type")["count"]
        .sum()
        .nlargest(10)
        .index
    )
    df = df[df["type"].isin(top_types)]

    y = "count"
    if normalize:
        year_totals = df.groupby("year")["count"].transform("sum")
        df["pct"] = df["count"] / year_totals * 100
        y = "pct"

    fig = px.bar(
        df,
        x="year",
        y=y,
        color="type",
        title=title,
        labels={
            "year": "Year",
            "count": "Error Count",
            "pct": "% of Error Types (within year)",
            "type": "Error Type",
        },
    )
    fig.update_layout(barmode="stack")
    if normalize:
        fig.update_yaxes(range=[0, 100], ticksuffix="%")
    fig.show()


def plot_removed_errors_by_year(records, title):
    if not records:
        return

    df = pd.DataFrame(records)
    df = df.groupby(["year", "type"])["count"].sum().reset_index()

    # compute per-year totals for percentage normalization
    year_totals = df.groupby("year")["count"].transform("sum")
    df["pct"] = df["count"] / year_totals * 100

    type_totals = df.groupby("type")["count"].sum().sort_values(ascending=False)
    type_pct_overall = type_totals / type_totals.sum() * 100
    ordered_types = list(type_pct_overall.index)
    display_labels = {
        error_type: f"{error_type} ({type_pct_overall[error_type]:.1f}%)"
        for error_type in ordered_types
    }
    df["legend_type"] = df["type"].map(display_labels)

    fig = px.bar(
        df,
        x="year",
        y="pct",
        color="legend_type",
        title=title,
        category_orders={"legend_type": [display_labels[t] for t in ordered_types]},
        labels={
            "year": "Year",
            "pct": "% of Removed Errors (within year)",
            "legend_type": "Error Type",
        },
    )
    fig.update_layout(barmode="stack")
    fig.update_yaxes(range=[0, 100], ticksuffix="%")
    fig.show()


def curation_session_timespan_hours(cluster):
    if not cluster:
        return None

    start = parse_iso8601(cluster.get("start"))
    end = parse_iso8601(cluster.get("end"))
    if not start or not end or end < start:
        return None

    return (end - start).total_seconds() / 3600


with open(TEMPORAL_REPORT) as f, open(EVENT_SEQUENCES) as g, open(STATUS_DELIMITED_SEQUENCES) as h, open(SPARCUR_UPDATES) as i, open(CURATION_CLUSTERS) as j, open(CURATOR_CATEGORIES) as k:
    temporal_report = json.load(f)
    event_sequences = json.load(g)
    status_delimited_sequences = json.load(h)
    sparcur_updates = list(csv.DictReader(i))
    curation_clusters = json.load(j)
    curator_categories = json.load(k)

    def metric_1_standards_adherence(temporal_report, event_sequences, sparcur_updates, use_error_index=USE_ERROR_INDEX_GRAPH):
        records = []
        colors = {
            "precision": "royalblue",
            "sparc": "orange",
            "rejoin": "green",
            "unknown": "gray",
        }
        source_label = "Error Index" if use_error_index else "Error Count"

        for dataset_id, dataset_record in temporal_report.items():
            if is_excluded_dataset(dataset_id):
                continue
            events = event_sequences.get(dataset_id)
            if not events:
                continue

            error_graph = (
                dataset_record.get("error_index_graph", {})
                if use_error_index
                else dataset_record.get("error_graph", {})
            )
            org = (
                "precision" if dataset_record.get("is_precision") else
                "sparc" if dataset_record.get("is_sparc") else
                "rejoin" if dataset_record.get("is_rejoin") else
                "unknown"
            )
            uses_soda = dataset_record.get("uses_soda", False)

            for event in events:
                if event.get("incomplete"):
                    continue
                
                req_created = event.get("request_created")
                pub_created = event.get("accept_created")
                
                if not req_created or not pub_created:
                    continue
                
                req_time = parse_iso8601(req_created)
                pub_time = parse_iso8601(pub_created)
                
                if not req_time or not pub_time:
                    continue
                
                req_ts = int(req_time.timestamp())
                pub_ts = int(pub_time.timestamp())
                req_error_count = error_diff_value_at_or_before(req_ts, error_graph)
                pub_error_count = error_diff_value_at_or_before(pub_ts, error_graph)
                
                if req_error_count is None or pub_error_count is None:
                    continue
                
                if req_error_count == 9999 or pub_error_count == 9999:
                    continue
                
                records.append({
                    "dataset_id": dataset_id,
                    "request_time": req_time,
                    "publish_time": pub_time,
                    "error_diff": pub_error_count - req_error_count,
                    "req_error_count": req_error_count,
                    "pub_error_count": pub_error_count,
                    "uses_soda": uses_soda,
                    "org": org,
                })

        for soda_val, soda_label in [(True, "SODA"), (False, "non-SODA")]:
            for org in ["sparc"]:
                filtered = [r for r in records if r["uses_soda"] == soda_val and r["org"] == org]
                
                if not filtered:
                    continue
                
                x_vals = [r["request_time"] for r in filtered]
                y_vals = [r["error_diff"] for r in filtered]
                y_absmax = max(abs(min(y_vals)), abs(max(y_vals)))
                y_buffer = max(1, y_absmax * 0.05)
                hover_text = [
                    f"Dataset ID: {r['dataset_id']}<br>Request Date: {format_datetime(r['request_time'])}<br>Publication Date: {format_datetime(r['publish_time'])}<br>Diff: {r['error_diff']}<br>At Request: {r.get('req_error_count', 'N/A')}<br>At Publish: {r.get('pub_error_count', 'N/A')}"
                    for r in filtered
                ]

                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=x_vals,
                    y=y_vals,
                    mode="markers",
                    marker=dict(color=colors.get(org, "gray"), size=10, opacity=0.7),
                    name=f"{soda_label} {org} ({len(filtered)})",
                    text=hover_text,
                    hoverinfo="text",
                ))
                
                min_x = min(x_vals)
                
                for update in sparcur_updates:
                    update_date = parse_mmddyyyy(update["date"])
                    
                    if not update_date:
                        continue
                    if min_x.tzinfo is not None and update_date.tzinfo is None:
                        update_date = update_date.replace(tzinfo=min_x.tzinfo)
                    elif min_x.tzinfo is None and update_date.tzinfo is not None:
                        min_x = min_x.replace(tzinfo=update_date.tzinfo)
                    if update_date >= min_x:
                        fig.add_vline(x=update_date, line=dict(color="red", dash="dash"), opacity=0.7)
                        fig.add_annotation(x=update_date, y=1, yref="paper", text=update["version"], showarrow=False)

                fig.add_hline(y=0, line=dict(color="gray", dash="dash"), opacity=0.5)
                fig.update_yaxes(range=[-y_absmax - y_buffer, y_absmax + y_buffer], title=f"{source_label} Difference (Publication - Request)")
                fig.update_xaxes(title="First Request Date")
                fig.update_layout(title=f"Standards Adherence: {source_label} Difference (Publication - Request)<br>{soda_label} {org}")
                fig.show()

    def metric_1b_error_types(temporal_report, event_sequences):
        first_request_error_type_records = []
        publication_error_type_records = []
        for dataset_id, dataset_record in temporal_report.items():
            if is_excluded_dataset(dataset_id):
                continue
            
            error_graph = dataset_record.get("error_graph", {})
            
            if not error_graph:
                continue
            
            req_date = first_request_date(dataset_id, event_sequences)
            
            if req_date:
                req_types = drop_excluded_error_types(error_types_near(int(req_date.timestamp()), error_graph))
                if req_types:
                    for error_type, count in req_types.items():
                        first_request_error_type_records.append({"year": fiscal_year(req_date), "type": error_type, "count": count})
            
            pub_date = first_publication_date(dataset_id, event_sequences)
            
            if pub_date:
                pub_types = drop_excluded_error_types(error_types_near(int(pub_date.timestamp()), error_graph))
                if pub_types:
                    for error_type, count in pub_types.items():
                        publication_error_type_records.append({"year": fiscal_year(pub_date), "type": error_type, "count": count})
        
        plot_error_types_by_year(first_request_error_type_records, "Top 10 Error Types at First Request by Year", normalize=True)
        plot_error_types_by_year(publication_error_type_records, "Top 10 Error Types at Publication by Year", normalize=True)

    def metric_1c_removed_errors(temporal_report, event_sequences):
        removed_error_type_records = []
        for dataset_id, dataset_record in temporal_report.items():
            if is_excluded_dataset(dataset_id):
                continue
            error_graph = dataset_record.get("error_graph", {})
            req_date = first_request_date(dataset_id, event_sequences)
            pub_date = first_publication_date(dataset_id, event_sequences)
            
            if not req_date or not pub_date:
                continue
            
            req_types = drop_excluded_error_types(error_types_near(int(req_date.timestamp()), error_graph))
            pub_types = drop_excluded_error_types(error_types_near(int(pub_date.timestamp()), error_graph))
            
            if not req_types:
                continue
            
            if not pub_types:
                pub_types = {}
            
            for error_type in set(req_types) | set(pub_types):
                req_count = req_types.get(error_type, 0)
                pub_count = pub_types.get(error_type, 0)
                removed_count = req_count - pub_count
                if removed_count > 0:
                    removed_error_type_records.append({"year": fiscal_year(req_date), "type": error_type, "count": removed_count})
        
        plot_removed_errors_by_year(removed_error_type_records, "Removed Errors by Type by First Request Year")

    def metric_1d_error_type_counts(temporal_report, event_sequences):
        req_records = []
        pub_records = []
        
        for dataset_id, dataset_record in temporal_report.items():
            if is_excluded_dataset(dataset_id):
                continue
            
            error_graph = dataset_record.get("error_graph", {})
            
            if not error_graph:
                continue
            
            req_date = first_request_date(dataset_id, event_sequences)
            pub_date = first_publication_date(dataset_id, event_sequences)
            
            if req_date:
                req_types = drop_excluded_error_types(error_types_near(int(req_date.timestamp()), error_graph))
                req_records.append({
                    "dataset_id": dataset_id,
                    "year": fiscal_year(req_date),
                    "error_type_count": len(req_types) if req_types else 0,
                })
            if pub_date:
                pub_types = drop_excluded_error_types(error_types_near(int(pub_date.timestamp()), error_graph))
                pub_records.append({
                    "dataset_id": dataset_id,
                    "year": fiscal_year(pub_date),
                    "error_type_count": len(pub_types) if pub_types else 0,
                })

        for label, records in [("At First Request", req_records), ("At Publication", pub_records)]:
            if not records:
                continue
            df = pd.DataFrame(records)
            fig = px.box(
                df,
                x="year",
                y="error_type_count",
                hover_data=["dataset_id"],
                points="all",
                title=f"Number of Distinct Error Types per Dataset by Year ({label})",
                labels={
                    "year": "Year",
                    "error_type_count": "Distinct Error Types",
                    "dataset_id": "Dataset ID",
                },
            )
            fig.show()

    def metric_2b_quarters_to_publication(event_sequences):
        records = []
        
        for dsid, events in event_sequences.items():
            if is_excluded_dataset(dsid):
                continue
            
            req = first_request_date(dsid, event_sequences)
            pub = first_publication_date(dsid, event_sequences)
            
            if not req or not pub or pub <= req:
                continue
            
            days = (pub - req).days
            quarters = days / 91.3125
            records.append({
                "dataset_id": dsid,
                "request_year": fiscal_year(req),
                "quarters_to_pub": quarters,
                "publication_date": pub,
            })
            
        if not records:
            return
        
        df = pd.DataFrame(records)
        # round up to whole quarters
        df["quarters_bucket"] = np.ceil(df["quarters_to_pub"]).clip(lower=1).astype(int)

        overall = df.groupby("quarters_bucket").size().reset_index(name="count")
        fig = px.bar(
            overall,
            x="quarters_bucket",
            y="count",
            title="Number of Quarters from First Request to Publication (All Datasets)",
            labels={
                "quarters_bucket": "Quarters to Publication",
                "count": "Number of Datasets",
            },
        )
        fig.update_xaxes(dtick=1)
        fig.show()

        # Per request year: grouped bars of datasets per quarter bucket
        by_year = df.groupby(["request_year", "quarters_bucket"]).size().reset_index(name="count")
        by_year["request_year"] = by_year["request_year"].astype(str)
        fig2 = px.bar(
            by_year,
            x="quarters_bucket",
            y="count",
            color="request_year",
            barmode="group",
            title="Number of Quarters from First Request to Publication by Request Year",
            labels={
                "quarters_bucket": "Quarters to Publication",
                "count": "Number of Datasets",
                "request_year": "Request Year",
            },
        )
        fig2.update_xaxes(dtick=1)
        fig2.show()

    def metric_2_time_to_publication(event_sequences):
        durations_by_year = defaultdict(list)
        unpublished_counts_by_year = defaultdict(int)
        
        for dsid, events in event_sequences.items():
            if is_excluded_dataset(dsid):
                continue
            
            if not events:
                continue
            
            req = first_request_date(dsid, event_sequences)
            pub = first_publication_date(dsid, event_sequences)
            
            if req and pub and pub > req:
                #if (pub - req).days > 100:
                #    continue
                durations_by_year[fiscal_year(req)].append({"year": fiscal_year(req), "duration": (pub - req).days, "id": dsid, "publication_date": pub})
            
            if not pub and req:
                unpublished_counts_by_year[fiscal_year(req)] += 1
                
        if durations_by_year:
            box_data = [row for year in sorted(durations_by_year) for row in durations_by_year[year]]
            df = pd.DataFrame(box_data)
            max_duration = int(df["duration"].max())
            year_tick_values = [365 * year for year in range(1, max_duration // 365 + 1)]
            year_tick_text = [f"{year} year" if year == 1 else f"{year} years" for year in range(1, max_duration // 365 + 1)]
            fig = px.box(df, x="year", y="duration", 
                         hover_data=["id", "publication_date"], 
                         points="all", 
                         title="Time from First Request to Publication by Year", 
                         labels={"id": "Dataset ID", "duration": "Days from Request to Publication", "year": "Request Year", "publication_date": "Publication Date"})
            
            if unpublished_counts_by_year:
                unpublished_by_year_text = ", ".join([f"{year}: {count}" for year, count in sorted(unpublished_counts_by_year.items())])
                unpublished_text = f"Note: Datasets with request dates but without publication dates ({unpublished_by_year_text}) are not included in the plot."
                fig.update_layout(margin=dict(b=100), annotations=[dict(text=unpublished_text, showarrow=False, xref="paper", yref="paper", x=0, y=-0.15, xanchor="left", yanchor="auto", font=dict(size=12, color="gray"))])
            if year_tick_values:
                for tick_value, tick_label in zip(year_tick_values, year_tick_text):
                    fig.add_hline(y=tick_value, line=dict(color="gray", dash="dot"), opacity=0.6)
                    fig.add_annotation(x=1.01, xref="paper", y=tick_value, yref="y", text=tick_label, showarrow=False, xanchor="left", yanchor="middle", font=dict(color="gray", size=11))
                fig.update_yaxes(title="Days from Request to Publication")
            
            fig.show()

    def metric_3_event_types(status_delimited_sequences):
        event_type_records = []
        for dataset_id, dataset_sequences in status_delimited_sequences.items():
            if is_excluded_dataset(dataset_id):
                continue
            
            for sequence in dataset_sequences:
                for event in sequence:
                    if event.get("userId") not in CURATOR_IDS:
                        continue
                    
                    created_at = parse_iso8601(event.get("createdAt"))
                    event_type = event.get("type")
                    
                    if not created_at or not event_type:
                        continue
                    
                    event_type_records.append({"year": fiscal_year(created_at), "type": event_type})
        
        if event_type_records:
            df = pd.DataFrame(event_type_records)
            df = df.groupby(["year", "type"]).size().reset_index(name="size")
            top_types = df.groupby("type")["size"].sum().nlargest(10).index
            df = df[df["type"].isin(top_types)]
            fig = px.bar(df, x="year", y="size", color="type", title="Top 10 Event Types per Year", labels={"year": "Year", "size": "Event Count", "type": "Event Type"})
            fig.update_layout(barmode="stack")
            fig.show()

    def metric_4_total_curation_events(temporal_report, event_sequences, status_delimited_sequences):
        curation_event_records = []
        for dataset_id, dataset_record in temporal_report.items():
            if is_excluded_dataset(dataset_id):
                continue
            
            first_request = first_request_date(dataset_id, event_sequences)
            
            if not first_request:
                continue
            
            publication_date = first_publication_date(dataset_id, event_sequences)
            dataset_sequences = status_delimited_sequences.get(dataset_id, [])
            total_curation_events = sum(len(sequence) for sequence in dataset_sequences)
            curation_event_records.append({"dataset_id": dataset_id, "first_request_year": fiscal_year(first_request), "publication_date": publication_date, "total_curation_events": total_curation_events})
        if curation_event_records:
            fig = px.box(pd.DataFrame(curation_event_records), x="first_request_year", y="total_curation_events", hover_data=["dataset_id", "publication_date"], points="all", title="Total Curation Changes per Dataset by First Request Year", labels={"first_request_year": "First Request Year", "total_curation_events": "Total Curation Changes", "dataset_id": "Dataset ID", "publication_date": "Publication Date"})
            fig.update_traces(hovertemplate="First Request Year=%{x}<br>Total Curation Sessions=%{y}<br>Dataset ID=%{customdata[0]}<br>Publication Date=%{customdata[1]}<extra></extra>")
            fig.show()

    def metric_4b_session_timespans(curation_clusters, event_sequences):
        curation_session_timespan_records = []
        for dataset_id, dataset_sequences in curation_clusters.items():
            if is_excluded_dataset(dataset_id):
                continue
            first_request = first_request_date(dataset_id, event_sequences)
            if not first_request:
                continue
            publication_date = first_publication_date(dataset_id, event_sequences)
            for sequence in dataset_sequences:
                for cluster in sequence.get("clusters", []):
                    session_timespan_hours = curation_session_timespan_hours(cluster)
                    if session_timespan_hours is None:
                        continue
                    curation_session_timespan_records.append({
                        "dataset_id": dataset_id,
                        "first_request_year": fiscal_year(first_request),
                        "publication_date": publication_date,
                        "session_timespan_hours": session_timespan_hours,
                        "session_start": parse_iso8601(cluster.get("start")),
                        "session_end": parse_iso8601(cluster.get("end")),
                    })
                    
        if curation_session_timespan_records:
            df = pd.DataFrame(curation_session_timespan_records)
            small_threshold = 1e-3
            keep_df = df[df["session_timespan_hours"] >= small_threshold].copy()
            removed_count = len(df) - len(keep_df)

            if keep_df.empty:
                # nothing meaningful to plot
                return

            # use session_start datetime as the x axis so plot is time-based
            fig = px.scatter(
                keep_df,
                x="session_start",
                y="session_timespan_hours",
                hover_data=["dataset_id", "publication_date", "session_start", "session_end"],
                title="Timespan of Every Curation Session by Session Start",
                labels={
                    "session_start": "Session Start",
                    "session_timespan_hours": "Session Timespan (Hours)",
                    "dataset_id": "Dataset ID",
                    "publication_date": "Publication Date",
                    "session_end": "Session End",
                },
                opacity=0.75,
            )
            fig.update_traces(marker=dict(size=8), hovertemplate="Session Start=%{x}<br>Session Timespan (Hours)=%{y:.2f}<br>Dataset ID=%{customdata[0]}<br>Publication Date=%{customdata[1]}<br>Session Start=%{customdata[2]}<br>Session End=%{customdata[3]}<extra></extra>")

            try:
                x_numeric = np.array(mdates.date2num(keep_df["session_start"]), dtype=float)
                y_numeric = np.array(keep_df["session_timespan_hours"], dtype=float)
                
                if len(x_numeric) >= 2:
                    slope, intercept = np.polyfit(x_numeric, y_numeric, 1)
                    x_line = np.linspace(x_numeric.min(), x_numeric.max(), 100)
                    y_line = slope * x_line + intercept
                    fig.add_trace(go.Scatter(x=mdates.num2date(x_line), y=y_line, mode="lines", line=dict(color="black", width=2), name="Trend line", hoverinfo="skip"))
            except Exception:
                pass

            fig.update_xaxes(title="Session Start", type="date")

            if removed_count > 0:
                total_sessions = len(df)
                caption = f"Note: {removed_count} sessions removed because span < {small_threshold} hours (of {total_sessions} total sessions)."
                fig.update_layout(margin=dict(b=100), annotations=[dict(text=caption, showarrow=False, xref="paper", yref="paper", x=0, y=-0.15, xanchor="left", yanchor="auto", font=dict(size=12, color="gray"))])

            fig.show()

    def metric_4c_total_curation_time(curation_clusters, event_sequences):
        total_time_records = []
        
        for dataset_id, dataset_sequences in curation_clusters.items():
            if is_excluded_dataset(dataset_id):
                continue
            
            first_request = first_request_date(dataset_id, event_sequences)
            
            if not first_request:
                continue
            
            publication_date = first_publication_date(dataset_id, event_sequences)
            
            total_hours = 0
            
            for sequence in dataset_sequences:
                for cluster in sequence.get("clusters", []):
                    session_timespan_hours = curation_session_timespan_hours(cluster)
                    if session_timespan_hours is not None and session_timespan_hours >= 1e-3:
                        total_hours += session_timespan_hours
            
            total_time_records.append({
                "dataset_id": dataset_id,
                "first_request_date": first_request,
                "first_request_year": fiscal_year(first_request),
                "publication_date": publication_date,
                "total_curation_hours": total_hours,
            })
        
        if total_time_records:
            df = pd.DataFrame(total_time_records)
            fig = go.Figure()
            first_request_dates = [record["first_request_date"] for record in total_time_records]
            total_hours_list = [record["total_curation_hours"] for record in total_time_records]
            fig.add_trace(go.Scatter(
                x=first_request_dates,
                y=total_hours_list,
                mode="markers",
                marker=dict(size=10, opacity=0.75, color="purple"),
                text=[f"Dataset ID: {record['dataset_id']}<br>First Request Date: {format_datetime(record['first_request_date'])}<br>Publication Date: {format_datetime(record.get('publication_date'))}<br>Total Curation Time: {record['total_curation_hours']:.2f} hours" for record in total_time_records],
                hoverinfo="text",
                name="Datasets",
            ))
            
            if len(total_time_records) >= 2:
                x_numeric = np.array(mdates.date2num(first_request_dates), dtype=float)
                y_numeric = np.array(total_hours_list, dtype=float)
                slope, intercept = np.polyfit(x_numeric, y_numeric, 1)
                x_line = np.linspace(x_numeric.min(), x_numeric.max(), 100)
                y_line = slope * x_line + intercept
                fig.add_trace(go.Scatter(
                    x=mdates.num2date(x_line),
                    y=y_line,
                    mode="lines",
                    line=dict(color="black", width=2),
                    name="Trend line",
                    hoverinfo="skip",
                ))
            
            fig.update_xaxes(title="First Request Date", type="date")
            fig.update_yaxes(title="Total Curation Time (Hours)")
            fig.update_layout(title="Total Time Spent Curating per Dataset by First Request Date")
            fig.show()

    def metric_4d_gaps_between_sessions(curation_clusters, event_sequences):
        gap_records = []
        for dataset_id, dataset_sequences in curation_clusters.items():
            if is_excluded_dataset(dataset_id):
                continue
            first_request = first_request_date(dataset_id, event_sequences)
            if not first_request:
                continue
            publication_date = first_publication_date(dataset_id, event_sequences)
            
            for sequence in dataset_sequences:
                clusters = sequence.get("clusters", [])
                for i in range(len(clusters) - 1):
                    current_cluster = clusters[i]
                    next_cluster = clusters[i + 1]
                    
                    current_end = parse_iso8601(current_cluster.get("end"))
                    next_start = parse_iso8601(next_cluster.get("start"))
                    
                    if current_end and next_start and next_start > current_end:
                        gap_hours = (next_start - current_end).total_seconds() / 3600
                        gap_records.append({
                            "dataset_id": dataset_id,
                            "first_request_year": fiscal_year(first_request),
                            "publication_date": publication_date,
                            "gap_hours": gap_hours,
                            "gap_start": current_end,
                            "gap_end": next_start,
                        })
        
        if gap_records:
            df = pd.DataFrame(gap_records)
            fig = px.scatter(
                df,
                x="gap_start",
                y="gap_hours",
                hover_data=["dataset_id", "publication_date", "gap_end"],
                title="Gaps Between Curation Sessions by Gap Start",
                labels={
                    "gap_start": "Gap Start",
                    "gap_hours": "Gap Duration (Hours)",
                    "dataset_id": "Dataset ID",
                    "publication_date": "Publication Date",
                    "gap_end": "Gap End",
                },
                opacity=0.75,
            )
            fig.update_traces(marker=dict(size=8), hovertemplate="Gap Start=%{x}<br>Gap Duration (Hours)=%{y:.2f}<br>Dataset ID=%{customdata[0]}<br>Publication Date=%{customdata[1]}<br>Gap End=%{customdata[2]}<extra></extra>")
            
            if len(gap_records) >= 2:
                x_numeric = np.array(mdates.date2num(df["gap_start"]), dtype=float)
                y_numeric = np.array(df["gap_hours"], dtype=float)
                slope, intercept = np.polyfit(x_numeric, y_numeric, 1)
                x_line = np.linspace(x_numeric.min(), x_numeric.max(), 100)
                y_line = slope * x_line + intercept
                fig.add_trace(go.Scatter(
                    x=mdates.num2date(x_line),
                    y=y_line,
                    mode="lines",
                    line=dict(color="black", width=2),
                    name="Trend line",
                    hoverinfo="skip",
                ))
            
            fig.update_xaxes(title="Gap Start", type="date")
            fig.show()

    def metric_4e_total_gaps_per_dataset(curation_clusters, event_sequences):
        total_gaps_records = []
        for dataset_id, dataset_sequences in curation_clusters.items():
            if is_excluded_dataset(dataset_id):
                continue
            first_request = first_request_date(dataset_id, event_sequences)
            if not first_request:
                continue
            publication_date = first_publication_date(dataset_id, event_sequences)
            
            total_gap_hours = 0
            gap_count = 0
            for sequence in dataset_sequences:
                clusters = sequence.get("clusters", [])
                for i in range(len(clusters) - 1):
                    current_cluster = clusters[i]
                    next_cluster = clusters[i + 1]
                    
                    current_end = parse_iso8601(current_cluster.get("end"))
                    next_start = parse_iso8601(next_cluster.get("start"))
                    
                    if current_end and next_start and next_start > current_end:
                        gap_hours = (next_start - current_end).total_seconds() / 3600
                        total_gap_hours += gap_hours
                        gap_count += 1
            
            total_gaps_records.append({
                "dataset_id": dataset_id,
                "first_request_date": first_request,
                "first_request_year": fiscal_year(first_request),
                "publication_date": publication_date,
                "total_gap_hours": total_gap_hours,
                "gap_count": gap_count,
            })
        
        if total_gaps_records:
            df = pd.DataFrame(total_gaps_records)
            fig = go.Figure()
            first_request_dates = [record["first_request_date"] for record in total_gaps_records]
            total_gaps_list = [record["total_gap_hours"] for record in total_gaps_records]
            fig.add_trace(go.Scatter(
                x=first_request_dates,
                y=total_gaps_list,
                mode="markers",
                marker=dict(size=10, opacity=0.75, color="crimson"),
                text=[f"Dataset ID: {record['dataset_id']}<br>First Request Date: {format_datetime(record['first_request_date'])}<br>Publication Date: {format_datetime(record.get('publication_date'))}<br>Total Gap Time: {record['total_gap_hours']:.2f} hours<br>Gap Count: {record['gap_count']}" for record in total_gaps_records],
                hoverinfo="text",
                name="Datasets",
            ))
            
            if len(total_gaps_records) >= 2:
                x_numeric = np.array(mdates.date2num(first_request_dates), dtype=float)
                y_numeric = np.array(total_gaps_list, dtype=float)
                slope, intercept = np.polyfit(x_numeric, y_numeric, 1)
                x_line = np.linspace(x_numeric.min(), x_numeric.max(), 100)
                y_line = slope * x_line + intercept
                fig.add_trace(go.Scatter(
                    x=mdates.num2date(x_line),
                    y=y_line,
                    mode="lines",
                    line=dict(color="black", width=2),
                    name="Trend line",
                    hoverinfo="skip",
                ))
            
            fig.update_xaxes(title="First Request Date", type="date")
            fig.update_yaxes(title="Total Gap Time (Hours)")
            fig.update_layout(title="Total Gaps Between Curation Sessions per Dataset by First Request Date")
            fig.show()

    def metric_5_datasets_vs_clusters(curation_clusters, event_sequences):
        cluster_records = []
        for dataset_id, dataset_sequences in curation_clusters.items():
            if is_excluded_dataset(dataset_id):
                continue
            
            first_request = first_request_date(dataset_id, event_sequences)
            
            if not first_request:
                continue
            
            publication_date = first_publication_date(dataset_id, event_sequences)
            cluster_total = 0
            
            for sequence in dataset_sequences:
                cluster_total += sequence.get("cluster_count", sequence.get("length", 0))
                
            cluster_records.append({
                "dataset_id": dataset_id, 
                "first_request_date": first_request, 
                "first_request_year": fiscal_year(first_request), 
                "publication_date": publication_date, 
                "total_clusters": cluster_total, 
                "sequence_count": len(dataset_sequences)
            })
        if cluster_records:
            fig = go.Figure()
            first_request_dates = [record["first_request_date"] for record in cluster_records]
            total_clusters = [record["total_clusters"] for record in cluster_records]
            fig.add_trace(go.Scatter(x=first_request_dates, y=total_clusters, mode="markers", marker=dict(size=10, opacity=0.75, color="teal"), text=[f"Dataset ID: {record['dataset_id']}<br>First Request Date: {format_datetime(record['first_request_date'])}<br>Publication Date: {format_datetime(record.get('publication_date'))}<br>Total Curations: {record['total_clusters']}<br>Status Sequences: {record['sequence_count']}" for record in cluster_records], hoverinfo="text", name="Datasets"))
            if len(cluster_records) >= 2:
                x_numeric = np.array(mdates.date2num(first_request_dates), dtype=float)
                y_numeric = np.array(total_clusters, dtype=float)
                slope, intercept = np.polyfit(x_numeric, y_numeric, 1)
                x_line = np.linspace(x_numeric.min(), x_numeric.max(), 100)
                y_line = slope * x_line + intercept
                fig.add_trace(go.Scatter(x=mdates.num2date(x_line), y=y_line, mode="lines", line=dict(color="black", width=2), name="Trend line", hoverinfo="skip"))
            fig.update_xaxes(title="First Request Date")
            fig.update_yaxes(title="Curation Sessions")
            fig.update_layout(title="Datasets by First Request Date and Total Curations Sessions")
            fig.show()
            fig = px.box(pd.DataFrame(cluster_records), x="first_request_year", y="total_clusters", hover_data=["dataset_id", "publication_date"], points="all", title="Curation Sessions per Dataset by First Request Year", labels={"first_request_year": "First Request Year", "total_clusters": "Curation Sessions", "dataset_id": "Dataset ID", "publication_date": "Publication Date"})
            fig.show()

    def metric_6_avg_cluster_length(curation_clusters, event_sequences):
        cluster_length_records = []
        for dataset_id, dataset_sequences in curation_clusters.items():
            if is_excluded_dataset(dataset_id):
                continue
            
            first_request = first_request_date(dataset_id, event_sequences)
            
            if not first_request:
                continue
            
            publication_date = first_publication_date(dataset_id, event_sequences)
            cluster_lengths = []
            
            for sequence in dataset_sequences:
                for cluster in sequence.get("clusters", []):
                    cluster_lengths.append(cluster.get("length"))
                    
            if not cluster_lengths:
                continue
            
            cluster_length_records.append({
                "dataset_id": dataset_id, 
                "first_request_date": first_request, 
                "first_request_year": fiscal_year(first_request), 
                "publication_date": publication_date, 
                "average_cluster_length": sum(cluster_lengths) / len(cluster_lengths), 
                "cluster_count": len(cluster_lengths)
            })
            
        if cluster_length_records:
            fig = go.Figure()
            first_request_dates = [record["first_request_date"] for record in cluster_length_records]
            average_cluster_lengths = [record["average_cluster_length"] for record in cluster_length_records]
            fig.add_trace(go.Scatter(x=first_request_dates, y=average_cluster_lengths, mode="markers", marker=dict(size=10, opacity=0.75, color="darkorange"), text=[f"Dataset ID: {record['dataset_id']}<br>First Request Date: {format_datetime(record['first_request_date'])}<br>Publication Date: {format_datetime(record.get('publication_date'))}<br>Average Curation Density: {record['average_cluster_length']:.2f}<br>Clusters: {record['cluster_count']}" for record in cluster_length_records], hoverinfo="text", name="Datasets"))
            if len(cluster_length_records) >= 2:
                x_numeric = np.array(mdates.date2num(first_request_dates), dtype=float)
                y_numeric = np.array(average_cluster_lengths, dtype=float)
                slope, intercept = np.polyfit(x_numeric, y_numeric, 1)
                x_line = np.linspace(x_numeric.min(), x_numeric.max(), 100)
                y_line = slope * x_line + intercept
                fig.add_trace(go.Scatter(x=mdates.num2date(x_line), y=y_line, mode="lines", line=dict(color="black", width=2), name="Trend line", hoverinfo="skip"))
            fig.update_xaxes(title="First Request Date")
            fig.update_yaxes(title="Average Curation Density")
            fig.update_layout(title="Datasets by First Request Date and Average Curation Density")
            fig.show()
            fig = px.box(pd.DataFrame(cluster_length_records), x="first_request_year", y="average_cluster_length", hover_data=["dataset_id", "publication_date"], points="all", title="Average Curation Density per Dataset by First Request Year", labels={"first_request_year": "First Request Year", "average_cluster_length": "Average Curation Density", "dataset_id": "Dataset ID", "publication_date": "Publication Date"})
            fig.show()

    def metric_7_category_mix_by_year(curator_categories, event_sequences):
        per_dataset = curator_categories.get("per_dataset", {})
        records = []
        for dataset_id, category_counts in per_dataset.items():
            if is_excluded_dataset(dataset_id):
                continue
            first_request = first_request_date(dataset_id, event_sequences)
            if not first_request:
                continue
            for category, count in category_counts.items():
                records.append({"year": fiscal_year(first_request), "category": category, "count": count})
        if not records:
            return

        df = pd.DataFrame(records).groupby(["year", "category"])["count"].sum().reset_index()
        # order legend by overall volume
        ordered = list(df.groupby("category")["count"].sum().sort_values(ascending=False).index)

        # raw counts
        fig = px.bar(
            df, x="year", y="count", color="category",
            category_orders={"category": ordered},
            title="Curator Event Category Mix per First Request Year (Counts)",
            labels={"year": "First Request Year", "count": "Curator Events", "category": "Category"},
        )
        fig.update_layout(barmode="stack")
        fig.show()

        year_totals = df.groupby("year")["count"].transform("sum")
        df["pct"] = df["count"] / year_totals * 100
        fig = px.bar(
            df, x="year", y="pct", color="category",
            category_orders={"category": ordered},
            title="Curator Event Category Mix per First Request Year (% within year)",
            labels={"year": "First Request Year", "pct": "% of Curator Events", "category": "Category"},
        )
        fig.update_layout(barmode="stack")
        fig.update_yaxes(range=[0, 100], ticksuffix="%")
        fig.show()

    def metric_7b_metadata_types_by_pub_year(curator_categories, event_sequences):
        # Metadata-subcategory mix per publication year (published datasets only).
        per_dataset_metadata = curator_categories.get("per_dataset_metadata", {})
        records = []
        for dataset_id, subcat_counts in per_dataset_metadata.items():
            if is_excluded_dataset(dataset_id):
                continue
            pub_date = first_publication_date(dataset_id, event_sequences)
            if not pub_date:
                continue
            for subcat, count in subcat_counts.items():
                records.append({"year": fiscal_year(pub_date), "type": subcat, "count": count})
        if not records:
            return

        df = pd.DataFrame(records).groupby(["year", "type"])["count"].sum().reset_index()
        ordered = list(df.groupby("type")["count"].sum().sort_values(ascending=False).index)

        # raw counts
        fig = px.bar(
            df, x="year", y="count", color="type",
            category_orders={"type": ordered},
            title="Metadata Edit Type Mix per Publication Year (Counts)",
            labels={"year": "Publication Year", "count": "Metadata Edits", "type": "Metadata Type"},
        )
        fig.update_layout(barmode="stack")
        fig.show()

        # normalized to % within each year
        year_totals = df.groupby("year")["count"].transform("sum")
        df["pct"] = df["count"] / year_totals * 100
        fig = px.bar(
            df, x="year", y="pct", color="type",
            category_orders={"type": ordered},
            title="Metadata Edit Type Mix per Publication Year (% within year)",
            labels={"year": "Publication Year", "pct": "% of Metadata Edits", "type": "Metadata Type"},
        )
        fig.update_layout(barmode="stack")
        fig.update_yaxes(range=[0, 100], ticksuffix="%")
        fig.show()

    def metric_1e_top_error_types(temporal_report, event_sequences):
        req_dataset_counts = Counter()
        pub_dataset_counts = Counter()
        for dataset_id, dataset_record in temporal_report.items():
            if is_excluded_dataset(dataset_id):
                continue
            error_graph = dataset_record.get("error_graph", {})
            pub_date = first_publication_date(dataset_id, event_sequences)
            
            if not error_graph or not pub_date:
                continue
            
            pub_types = drop_excluded_error_types(
                error_types_near(int(pub_date.timestamp()), error_graph)
            )
            
            if pub_types:
                for error_type in set(pub_types):
                    pub_dataset_counts[error_type] += 1
            
            req_date = first_request_date(dataset_id, event_sequences)
            if req_date:
                req_types = drop_excluded_error_types(
                    error_types_near(int(req_date.timestamp()), error_graph)
                )
                if req_types:
                    for error_type in set(req_types):
                        req_dataset_counts[error_type] += 1
        if not pub_dataset_counts:
            return

        pub_top = pub_dataset_counts.most_common(20)
        req_top = req_dataset_counts.most_common(20)
        pub_df = pd.DataFrame(pub_top, columns=["type", "dataset_count"]).iloc[::-1]
        req_df = pd.DataFrame(req_top, columns=["type", "dataset_count"]).iloc[::-1]
        fig = px.bar(
            pub_df, x="dataset_count", y="type", orientation="h",
            title="Most Common Error Types at Publication (by # of datasets)",
            labels={"dataset_count": "Number of Datasets", "type": "Error Type"},
        )
        fig.show()
        fig2 = px.bar(
            req_df, x="dataset_count", y="type", orientation="h",
            title="Most Common Error Types at First Request (by # of datasets)",
            labels={"dataset_count": "Number of Datasets", "type": "Error Type"},
        )
        fig2.show()

    def metric_1b_subsequent_pub(temporal_report, event_sequences):
        records = []
        for dataset_id, dataset_record in temporal_report.items():
            if is_excluded_dataset(dataset_id):
                continue
            error_graph = dataset_record.get("error_graph", {})
            if not error_graph:
                continue
            for pub_date in publication_dates(dataset_id, event_sequences)[1:]:
                pub_types = drop_excluded_error_types(
                    error_types_near(int(pub_date.timestamp()), error_graph)
                )
                if pub_types:
                    for error_type, count in pub_types.items():
                        records.append({"year": fiscal_year(pub_date), "type": error_type, "count": count})
        plot_error_types_by_year(records, "Top 10 Error Types at Subsequent Publications by Year (% within year)", normalize=True)

    def metric_1d_subsequent_pub(temporal_report, event_sequences):
        pub_records = []
        for dataset_id, dataset_record in temporal_report.items():
            if is_excluded_dataset(dataset_id):
                continue
            error_graph = dataset_record.get("error_graph", {})
            if not error_graph:
                continue
            for pub_date in publication_dates(dataset_id, event_sequences)[1:]:
                pub_types = drop_excluded_error_types(
                    error_types_near(int(pub_date.timestamp()), error_graph)
                )
                pub_records.append({
                    "dataset_id": dataset_id,
                    "year": fiscal_year(pub_date),
                    "error_type_count": len(pub_types) if pub_types else 0,
                })
        if not pub_records:
            return
        df = pd.DataFrame(pub_records)
        fig = px.box(
            df, x="year", y="error_type_count", hover_data=["dataset_id"], points="all",
            title="Number of Distinct Error Types per Dataset by Year (At Subsequent Publications)",
            labels={"year": "Year", "error_type_count": "Distinct Error Types", "dataset_id": "Dataset ID"},
        )
        fig.show()

    def metric_1f_error_dataset_matrix(temporal_report, event_sequences):
        per_dataset = {}
        type_counts = Counter()
        
        for dataset_id, dataset_record in temporal_report.items():
            if is_excluded_dataset(dataset_id):
                continue
            
            error_graph = dataset_record.get("error_graph", {})
            pub_date = first_publication_date(dataset_id, event_sequences)
            
            if not error_graph or not pub_date:
                continue
            
            pub_types = drop_excluded_error_types(error_types_near(int(pub_date.timestamp()), error_graph))
            
            if not pub_types:
                continue
            
            types = set(pub_types)
            per_dataset[dataset_id] = types
            
            for error_type in types:
                type_counts[error_type] += 1
        
        if not per_dataset:
            return

        error_types = [t for t, _ in type_counts.most_common()]
        datasets = sorted(per_dataset, key=lambda d: len(per_dataset[d]), reverse=True)

        row_index = {t: i for i, t in enumerate(error_types)}
        col_index = {d: j for j, d in enumerate(datasets)}
        matrix = np.zeros((len(error_types), len(datasets)), dtype=int)
        
        for dataset_id, types in per_dataset.items():
            col = col_index[dataset_id]
            for error_type in types:
                matrix[row_index[error_type], col] = 1

        y_labels = [f"{t}  (n={type_counts[t]})" for t in error_types]
        x_labels = [d.replace("N:dataset:", "") for d in datasets]

        fig = px.imshow(
            matrix,
            x=x_labels,
            y=y_labels,
            color_continuous_scale=[[0, "#f4f4f4"], [1, "steelblue"]],
            aspect="auto",
            title=f"Error Type × Dataset Existence at Publication "
                  f"({len(datasets)} datasets × {len(error_types)} error types)",
        )
        
        fig.update_traces(xgap=1, ygap=1, hovertemplate="dataset=%{x}<br>error=%{y}<br>present=%{z}<extra></extra>")
        fig.update_xaxes(showticklabels=True, tickangle=90, tickfont=dict(size=6), title="Dataset", side="top")
        fig.update_yaxes(tickfont=dict(size=8), title="Error Type (n = # datasets)", autorange="reversed")
        fig.update_layout(
            coloraxis_showscale=False,
            width=max(1400, len(datasets) * 14 + 500),
            height=max(700, len(error_types) * 18 + 260),
            margin=dict(l=480, t=220),
        )
        fig.show()

    metric_toggles = {
        "metric_1_standards_adherence": False,
        "metric_1b_error_types": False,
        "metric_1c_removed_errors": False,
        "metric_1d_error_type_counts": True,
        "metric_1e_top_error_types": True,
        "metric_1b_subsequent_pub": True,
        "metric_1d_subsequent_pub": True,
        "metric_1f_error_dataset_matrix": True,
        "metric_2_time_to_publication": True,
        "metric_2b_quarters_to_publication": False,
        "metric_3_event_types": False,
        "metric_4_total_curation_events": False,
        "metric_4b_session_timespans": False,
        "metric_4c_total_curation_time": False,
        "metric_4d_gaps_between_sessions": False,
        "metric_4e_total_gaps_per_dataset": False,
        "metric_5_datasets_vs_clusters": False,
        "metric_6_avg_cluster_length": False,
        "metric_7_category_mix_by_year": True,
        "metric_7b_metadata_types_by_pub_year": True,
    }
    
    #for i, k in enumerate(metric_toggles): 
    #    if i != 3: 
    #       metric_toggles[k] = False

    if metric_toggles.get("metric_1_standards_adherence"):
        metric_1_standards_adherence(temporal_report, event_sequences, sparcur_updates)
    if metric_toggles.get("metric_1b_error_types"):
        metric_1b_error_types(temporal_report, event_sequences)
    if metric_toggles.get("metric_1c_removed_errors"):
        metric_1c_removed_errors(temporal_report, event_sequences)
    if metric_toggles.get("metric_1d_error_type_counts"):
        metric_1d_error_type_counts(temporal_report, event_sequences)
    if metric_toggles.get("metric_1e_top_error_types"):
        metric_1e_top_error_types(temporal_report, event_sequences)
    if metric_toggles.get("metric_1b_subsequent_pub"):
        metric_1b_subsequent_pub(temporal_report, event_sequences)
    if metric_toggles.get("metric_1d_subsequent_pub"):
        metric_1d_subsequent_pub(temporal_report, event_sequences)
    if metric_toggles.get("metric_1f_error_dataset_matrix"):
        metric_1f_error_dataset_matrix(temporal_report, event_sequences)
    if metric_toggles.get("metric_2_time_to_publication"):
        metric_2_time_to_publication(event_sequences)
    if metric_toggles.get("metric_2b_quarters_to_publication"):
        metric_2b_quarters_to_publication(event_sequences)
    if metric_toggles.get("metric_3_event_types"):
        metric_3_event_types(status_delimited_sequences)
    if metric_toggles.get("metric_4_total_curation_events"):
        metric_4_total_curation_events(temporal_report, event_sequences, status_delimited_sequences)
    if metric_toggles.get("metric_4b_session_timespans"):
        metric_4b_session_timespans(curation_clusters, event_sequences)
    if metric_toggles.get("metric_4c_total_curation_time"):
        metric_4c_total_curation_time(curation_clusters, event_sequences)
    if metric_toggles.get("metric_4d_gaps_between_sessions"):
        metric_4d_gaps_between_sessions(curation_clusters, event_sequences)
    if metric_toggles.get("metric_4e_total_gaps_per_dataset"):
        metric_4e_total_gaps_per_dataset(curation_clusters, event_sequences)
    if metric_toggles.get("metric_5_datasets_vs_clusters"):
        metric_5_datasets_vs_clusters(curation_clusters, event_sequences)
    if metric_toggles.get("metric_6_avg_cluster_length"):
        metric_6_avg_cluster_length(curation_clusters, event_sequences)
    if metric_toggles.get("metric_7_category_mix_by_year"):
        metric_7_category_mix_by_year(curator_categories, event_sequences)
    if metric_toggles.get("metric_7b_metadata_types_by_pub_year"):
        metric_7b_metadata_types_by_pub_year(curator_categories, event_sequences)
        