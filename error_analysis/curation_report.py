import csv
import datetime
import json
from collections import Counter, defaultdict

import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

from report_common import (
    is_excluded_dataset,
    true_submission_date,
    true_publication_date,
    is_excluded_computational,
    reconciliation_publication_year,
    parse_iso8601,
    parse_mmddyyyy,
    fiscal_year,
    get_canonical_title,
    drop_excluded_error_types,
    error_types_near_effective,
    nearest_export_key_effective,
    effective_after_event,
)

# file-wide plotly styling: bigger fonts on every figure
pio.templates["report"] = go.layout.Template(
    layout=dict(
        font=dict(size=18, color="black"),
        title=dict(font=dict(size=24)),
        legend=dict(font=dict(size=16)),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(gridcolor="lightgray", zerolinecolor="lightgray", linecolor="black", showline=True, ticks="outside", tickcolor="black"),
        yaxis=dict(gridcolor="lightgray", zerolinecolor="lightgray", linecolor="black", showline=True, ticks="outside", tickcolor="black"),
    ),
    data=dict(
        # box plots: no fill, black outline; scatters/histograms default to black
        box=[go.Box(fillcolor="rgba(0,0,0,0)", line=dict(color="black"), marker=dict(color="black"))],
        scatter=[go.Scatter(marker=dict(color="black"))],
        histogram=[go.Histogram(marker=dict(color="black"))],
    ),
)
pio.templates.default = "plotly+report"


TEMPORAL_REPORT = "./temporal_report.json"
EVENT_SEQUENCES = "./pennsieve_event_series.json"
STATUS_DELIMITED_SEQUENCES = "./pennsieve_status_delimited.json"
SPARCUR_UPDATES = "./sparcur_updates.csv"
CURATION_CLUSTERS = "./pennsieve_curation_clusters.json"
CURATOR_CATEGORIES = "./curator_event_categories.json"

CURATOR_IDS = {
    589, 
    832, 
    1554, 
    1186, 
    #531, 
    # 600, 
    601, 
    #611
}

# we should look over the categorization code; particularly metadata and add/remove_contributor
# what about styling by the way?
# metadata type mix: would be helpful to havae n=X metrics per year; same for event mix

# + also need to ask: is my collect() function double counting?


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

def format_datetime(value):
    if not value:
        return "N/A"
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    return str(value)


def error_label(error_type):
    # human-readable label for error-type figures: canonical title, path kept as a prefix
    return f"{error_type.split(':', 1)[0]}: {get_canonical_title(error_type)}"


def first_publication_date(dataset_id, event_sequences):
    # prefer the hand-verified A7 publication date; fall back to the first cycle's accept
    true_pub = true_publication_date(dataset_id)
    if true_pub is not None:
        return true_pub
    events = event_sequences.get(dataset_id)
    if not events:
        return None
    return parse_iso8601(events[0].get("accept_created"))


def publication_dates(dataset_id, event_sequences):
    events = event_sequences.get(dataset_id) or []
    dates = [parse_iso8601(event.get("accept_created")) for event in events]
    return sorted(date for date in dates if date)


def submission_dates(dataset_id, event_sequences):
    events = event_sequences.get(dataset_id) or []
    dates = [parse_iso8601(event.get("request_created")) for event in events]
    return sorted(date for date in dates if date)


def first_request_date(dataset_id, event_sequences, floor=True):
    # The 2022-04-01 floor is the error-analysis window; floor=False to opt out
    min_date = datetime.datetime(2022, 4, 1, tzinfo=datetime.timezone.utc)

    # prefer the "true" submission date (curation_start_dates.csv); fall back to the
    # earliest request_created.
    true_date = true_submission_date(dataset_id)

    if true_date is not None:
        return None if (floor and true_date < min_date) else true_date

    events = event_sequences.get(dataset_id)

    if not events:
        return None

    request_dates = [parse_iso8601(event.get("request_created")) for event in events]
    request_dates = [request_date for request_date in request_dates if request_date and (not floor or request_date >= min_date)]

    if not request_dates:
        return None

    return min(request_dates)


def template_version_near(dataset_record, event_dt):
    if event_dt is None:
        return ""

    key = nearest_export_key_effective(dataset_record, int(event_dt.timestamp()))
    graph_value = (dataset_record.get("template_version_graph") or {}).get(key)
    return graph_value or dataset_record.get("template_version") or ""


def award_number_near(dataset_record, event_dt):
    if event_dt is None:
        return ""

    key = nearest_export_key_effective(dataset_record, int(event_dt.timestamp()))
    return (dataset_record.get("award_number_graph") or {}).get(key, "")


def distinct_errors_at(dataset_record, event_dt):
    types = drop_excluded_error_types(error_types_near_effective(dataset_record, event_dt))
    return len(types) if types else 0


def export_failed_at(dataset_record, event_dt):
    # True if the export nearest the event failed completely (error_index 9999),
    # so its error count is unknown rather than zero
    if event_dt is None:
        return True
    key = nearest_export_key_effective(dataset_record, int(event_dt.timestamp()))
    return (dataset_record.get("error_index_graph") or {}).get(key) == 9999


def graph_excluded(dataset_id, dataset_record, event_sequences):
    """Drop a dataset from the error graphs when its submission or publication is
    missing / before the 2022-04 window, or it's a computational scaffold."""
    min_date = datetime.datetime(2022, 4, 1, tzinfo=datetime.timezone.utc)

    submission = first_request_date(dataset_id, event_sequences)

    if submission is None:
        return True

    publication = first_publication_date(dataset_id, event_sequences)

    if publication is not None and publication < min_date:
        return True

    # a reconciliation publication_year before 2022 means an earlier cycle than pennsieve shows
    recon_year = reconciliation_publication_year(dataset_id)

    if recon_year is not None and recon_year < 2022:
        return True

    if is_excluded_computational(dataset_id):
        return True

    # exclude if EITHER the submission or publication export failed (needs the record;
    # None-record callers, e.g. the curation-cluster graphs, skip this)
    if dataset_record is not None:
        if export_failed_at(dataset_record, submission):
            return True
        if publication is not None and export_failed_at(dataset_record, publication):
            return True

    return False


def sub_to_pub_records(event_sequences, min_year=2020):
    # shared source for the submission->publication timing graphs; 2018/2019 dropped
    records = []

    for dataset_id in event_sequences:
        if is_excluded_dataset(dataset_id) or is_excluded_computational(dataset_id):
            continue

        # reconciliation pub_year before 2022 means an earlier hidden cycle -> misleading duration
        recon_year = reconciliation_publication_year(dataset_id)
        if recon_year is not None and recon_year < 2022:
            continue

        req = first_request_date(dataset_id, event_sequences, floor=False)
        pub = first_publication_date(dataset_id, event_sequences)

        if not req or not pub or pub <= req or fiscal_year(req) < min_year:
            continue

        days = (pub - req).days
        records.append({
            "dataset_id": dataset_id,
            "submission_year": fiscal_year(req),
            "publication_year": fiscal_year(pub),
            "days": days,
            "quarters": days / 91.3125,
            "submission_date": req,
            "publication_date": pub,
        })

    return records


def rolling_mean_sem(df, date_col, window="90D"):
    # rolling mean and SEM of days-to-publication over a continuous date axis
    series = df[[date_col, "days"]].dropna().sort_values(date_col).set_index(date_col)["days"]
    roll = series.rolling(window)
    return pd.DataFrame({
        "date": series.index,
        "mean": roll.mean().values,
        "sem": (roll.std() / np.sqrt(roll.count())).values,
        "count": roll.count().values,
    })


def rolling_mean_std(df, date_col, value_col, window="90D"):
    # rolling mean and standard deviation of value_col over a continuous date axis
    series = df[[date_col, value_col]].dropna().sort_values(date_col).set_index(date_col)[value_col]
    roll = series.rolling(window)
    return pd.DataFrame({
        "date": series.index,
        "mean": roll.mean().values,
        "std": roll.std().values,
    })


def overlay_rolling(fig, df, date_col, value_col, window_days=180):
    # add a rolling-average line + transparent ±1 SD band (call after the scatter dots)
    roll = rolling_mean_std(df, date_col, value_col, window=f"{window_days}D")
    fig.add_trace(go.Scatter(x=roll["date"], y=roll["mean"] + roll["std"], mode="lines",
                             line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=roll["date"], y=roll["mean"] - roll["std"], mode="lines",
                             line=dict(width=0), fill="tonexty", fillcolor="rgba(0,0,0,0.12)",
                             name="±1 SD", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=roll["date"], y=roll["mean"], mode="lines",
                             line=dict(color="black", width=2), name=f"Rolling average ({window_days}-day window)", hoverinfo="skip"))


def plot_rolling_mean_sem(roll, title, x_label):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=roll["date"], y=roll["mean"] + roll["sem"], mode="lines",
                             line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=roll["date"], y=roll["mean"] - roll["sem"], mode="lines",
                             line=dict(width=0), fill="tonexty", fillcolor="rgba(65,105,225,0.2)",
                             name="±SEM", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=roll["date"], y=roll["mean"], mode="lines",
                             line=dict(color="royalblue", width=2), name="Rolling mean"))
    fig.update_layout(title=title, xaxis_title=x_label, yaxis_title="Days from Submission to Publication")
    # equal scale: 1 day on y matches 1 day on x (plotly date axis is in ms, so 1 day = 86_400_000)
    fig.update_yaxes(scaleanchor="x", scaleratio=86_400_000)
    fig.show()


def unpublished_by_year(event_sequences, min_year=2020):
    counts = defaultdict(int)
    for dataset_id, cycles in event_sequences.items():
        if is_excluded_dataset(dataset_id):
            continue
        if any(cycle.get("accept_created") for cycle in (cycles or [])):
            continue
        # reconciliation knows it published even without an accept event in the raw cycles
        if reconciliation_publication_year(dataset_id) is not None:
            continue
        req = first_request_date(dataset_id, event_sequences, floor=False)
        if req and fiscal_year(req) >= min_year:
            counts[fiscal_year(req)] += 1
    return counts


def add_unpublished_caption(fig, event_sequences):
    unpublished = unpublished_by_year(event_sequences)
    if unpublished:
        note = "Requested but never published — " + ", ".join(f"{year}: {count}" for year, count in sorted(unpublished.items()))
    else:
        note = "There are no datasets that were requested but never published in the pipeline."
    fig.update_layout(margin=dict(b=100))
    fig.add_annotation(text=note, showarrow=False, xref="paper", yref="paper",
                       x=0, y=-0.18, xanchor="left", font=dict(size=12, color="gray"))


def plot_error_types_by_year(records, title, normalize=False):
    if not records:
        return

    df = pd.DataFrame(records)
    df["type"] = df["type"].map(error_label)  # canonical title, path kept as prefix
    # count = number of distinct datasets that have each error type per year
    if "dataset_id" in df.columns:
        df = df.groupby(["year", "type"])["dataset_id"].nunique().reset_index(name="count")
    else:
        df = df.groupby(["year", "type"])["count"].sum().reset_index()
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
            "count": "Number of Datasets",
            "pct": "% of Datasets (within year)",
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
    df["type"] = df["type"].map(error_label)  # canonical title, path kept as prefix
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

    # every curation session counts for at least an hour; nevermind, going back to none
    return max((end - start).total_seconds() / 3600, 0)


def cluster_in_first_cycle(cluster, submission, publication):
    # True if the cluster starts within the first publication cycle [submission, publication]
    start = parse_iso8601(cluster.get("start"))
    if start is None:
        return False
    if submission is not None and start < submission:
        return False
    if publication is not None and start > publication:
        return False
    return True


def first_cycle_clusters(dataset_sequences, submission, publication):
    # flattened clusters within the first publication cycle [submission, publication]
    return [
        cluster
        for sequence in dataset_sequences
        for cluster in sequence.get("clusters", [])
        if cluster_in_first_cycle(cluster, submission, publication)
    ]


def cluster_stats(temporal_report, curation_clusters, event_sequences):
    # per-dataset first-publication-cycle curation stats (same filtering as metric_4c)
    records = []

    for dataset_id, sequences in curation_clusters.items():
        dataset_record = temporal_report.get(dataset_id)

        if dataset_record is None:
            continue
        if is_excluded_dataset(dataset_id) or graph_excluded(dataset_id, dataset_record, event_sequences):
            continue

        submission = first_request_date(dataset_id, event_sequences)
        publication = first_publication_date(dataset_id, event_sequences)

        hours = []
        for cluster in first_cycle_clusters(sequences, submission, publication):
            span = curation_session_timespan_hours(cluster)
            if span is not None and span >= 1e-3:
                hours.append(span)

        if not hours:
            continue

        records.append({
            "dataset_id": dataset_id,
            "cluster_hours": hours,
            "num_clusters": len(hours),
            "total_hours": sum(hours),
            "days_to_pub": (publication - submission).days if (publication and submission) else None,
        })

    return records


with open(TEMPORAL_REPORT) as f, open(EVENT_SEQUENCES) as g, open(STATUS_DELIMITED_SEQUENCES) as h, open(SPARCUR_UPDATES) as i, open(CURATION_CLUSTERS) as j, open(CURATOR_CATEGORIES) as k:
    temporal_report = json.load(f)
    event_sequences = json.load(g)
    status_delimited_sequences = json.load(h)
    sparcur_updates = list(csv.DictReader(i))
    curation_clusters = json.load(j)
    curator_categories = json.load(k)

    def metric_1_standards_adherence(temporal_report, event_sequences, sparcur_updates):
        records = []
        colors = {
            "precision": "royalblue",
            "sparc": "orange",
            "rejoin": "green",
            "unknown": "gray",
        }
        # distinct non-excluded error types (matches the matrix's included_errors_present)
        source_label = "Distinct Error Types"

        for dataset_id, dataset_record in temporal_report.items():
            if is_excluded_dataset(dataset_id) or graph_excluded(dataset_id, dataset_record, event_sequences):
                continue

            # first cycle only, on the same true submission/publication dates as the matrix
            submission = first_request_date(dataset_id, event_sequences)
            publication = first_publication_date(dataset_id, event_sequences)

            if not submission or not publication:
                continue

            # a failed export (error_index 9999) has an unknown count, not zero -> skip
            if export_failed_at(dataset_record, submission) or export_failed_at(dataset_record, publication):
                continue

            org = (
                "precision" if dataset_record.get("is_precision") else
                "sparc" if dataset_record.get("is_sparc") else
                "rejoin" if dataset_record.get("is_rejoin") else
                "unknown"
            )
            uses_soda = dataset_record.get("uses_soda", False)

            req_error_count = distinct_errors_at(dataset_record, submission)
            pub_error_count = distinct_errors_at(dataset_record, publication)

            records.append({
                "dataset_id": dataset_id,
                "request_time": submission,
                "publish_time": publication,
                "error_diff": pub_error_count - req_error_count,
                "req_error_count": req_error_count,
                "pub_error_count": pub_error_count,
                "uses_soda": uses_soda,
                "org": org,
            })

        for soda_val, soda_label in [(True, "SODA"), (False, "non-SODA")]:
            filtered = [r for r in records if r["uses_soda"] == soda_val]

            if not filtered:
                continue

            x_vals = [r["request_time"] for r in filtered]
            y_vals = [r["error_diff"] for r in filtered]
            y_absmax = max(abs(min(y_vals)), abs(max(y_vals)))
            y_buffer = max(1, y_absmax * 0.05)
            hover_text = [
                f"Dataset ID: {r['dataset_id']}<br>Submission Date: {format_datetime(r['request_time'])}<br>Publication Date: {format_datetime(r['publish_time'])}<br>Diff: {r['error_diff']}<br>At Submission: {r.get('req_error_count', 'N/A')}<br>At Publish: {r.get('pub_error_count', 'N/A')}"
                for r in filtered
            ]

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=x_vals,
                y=y_vals,
                mode="markers",
                marker=dict(color="black", size=10, opacity=0.5),
                name=f"{soda_label} ({len(filtered)})",
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
            fig.update_yaxes(range=[-y_absmax - y_buffer, y_absmax + y_buffer], title=f"{source_label} Difference (Publication - Submission)")
            fig.update_xaxes(title="Submission Date")
            fig.update_layout(title=f"Standards Adherence: {source_label} Difference (Publication - Submission)<br>{soda_label}")
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
            pub_date = first_publication_date(dataset_id, event_sequences)

            # exclude datasets whose nearest curation export (by updated ts)
            # postdates the request or publication event
            if graph_excluded(dataset_id, dataset_record, event_sequences) or \
               (req_date and effective_after_event(dataset_record, req_date)) or \
               (pub_date and effective_after_event(dataset_record, pub_date)):
                continue

            if req_date:
                req_types = drop_excluded_error_types(error_types_near_effective(dataset_record, req_date))
                if req_types:
                    for error_type, count in req_types.items():
                        first_request_error_type_records.append({"year": fiscal_year(req_date), "type": error_type, "count": count, "dataset_id": dataset_id})
            
            pub_date = first_publication_date(dataset_id, event_sequences)
            
            if pub_date:
                pub_types = drop_excluded_error_types(error_types_near_effective(dataset_record, pub_date))
                if pub_types:
                    for error_type, count in pub_types.items():
                        publication_error_type_records.append({"year": fiscal_year(pub_date), "type": error_type, "count": count, "dataset_id": dataset_id})
        
        plot_error_types_by_year(first_request_error_type_records, "Top 10 Error Types at Submission by Year (% within year)", normalize=True)
        plot_error_types_by_year(publication_error_type_records, "Top 10 Error Types at Publication by Year (% within year)", normalize=True)

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

            if graph_excluded(dataset_id, dataset_record, event_sequences) or effective_after_event(dataset_record, req_date) or effective_after_event(dataset_record, pub_date):
                continue

            req_types = drop_excluded_error_types(error_types_near_effective(dataset_record, req_date))
            pub_types = drop_excluded_error_types(error_types_near_effective(dataset_record, pub_date))
            
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
        
        plot_removed_errors_by_year(removed_error_type_records, "Removed Errors by Type by Submission Year")

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

            if graph_excluded(dataset_id, dataset_record, event_sequences) or \
               (req_date and effective_after_event(dataset_record, req_date)) or \
               (pub_date and effective_after_event(dataset_record, pub_date)):
                continue

            if req_date:
                req_types = drop_excluded_error_types(error_types_near_effective(dataset_record, req_date))
                req_records.append({
                    "dataset_id": dataset_id,
                    "year": fiscal_year(req_date),
                    "error_type_count": len(req_types) if req_types else 0,
                })
            if pub_date:
                pub_types = drop_excluded_error_types(error_types_near_effective(dataset_record, pub_date))
                pub_records.append({
                    "dataset_id": dataset_id,
                    "year": fiscal_year(pub_date),
                    "error_type_count": len(pub_types) if pub_types else 0,
                })

        for label, records in [("At Submission", req_records), ("At Publication", pub_records)]:
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
        records = sub_to_pub_records(event_sequences)

        if not records:
            return

        df = pd.DataFrame(records)
        # round up to whole quarters
        df["quarters_bucket"] = np.ceil(df["quarters"]).clip(lower=1).astype(int)

        overall = df.groupby("quarters_bucket").size().reset_index(name="count")
        fig = px.bar(
            overall,
            x="quarters_bucket",
            y="count",
            title="Submission-to-Publication Time in Quarters (All Datasets)",
            labels={
                "quarters_bucket": "Quarters to Publication",
                "count": "Number of Datasets",
            },
        )
        fig.update_xaxes(dtick=1)
        fig.show()

        for year_col, x_label, when in (("submission_year", "Submission Year", "Submission"),
                                        ("publication_year", "Publication Year", "Publication")):
            by_year = df.groupby([year_col, "quarters_bucket"]).size().reset_index(name="count")
            by_year[year_col] = by_year[year_col].astype(str)
            fig_year = px.bar(
                by_year,
                x="quarters_bucket",
                y="count",
                color=year_col,
                barmode="group",
                title=f"Submission-to-Publication Time in Quarters, by {when} Year",
                labels={
                    "quarters_bucket": "Quarters to Publication",
                    "count": "Number of Datasets",
                    year_col: x_label,
                },
            )
            fig_year.update_xaxes(dtick=1)
            fig_year.show()

    def metric_2_time_to_publication(event_sequences):
        records = sub_to_pub_records(event_sequences)

        if not records:
            return

        df = pd.DataFrame(records).sort_values("submission_year")
        df["submission_year"] = df["submission_year"].astype(str)

        mean_days = df["days"].mean()
        std_days = df["days"].std()

        max_duration = int(df["days"].max())
        year_tick_values = [365 * year for year in range(1, max_duration // 365 + 1)]
        year_tick_text = [f"{year} year" if year == 1 else f"{year} years" for year in range(1, max_duration // 365 + 1)]

        fig = px.box(df, x="submission_year", y="days",
                     hover_data=["dataset_id", "publication_date"],
                     points="all",
                     title="Submission-to-Publication Time by Submission Year",
                     labels={"dataset_id": "Dataset ID", "days": "Days from Submission to Publication", "submission_year": "Submission Year", "publication_date": "Publication Date"})
        fig.update_traces(boxmean="sd")

        fig.add_annotation(xref="paper", yref="paper", x=0, y=1.08, showarrow=False, xanchor="left",
                           text=f"Overall: mean {mean_days:.0f} d, SD {std_days:.0f} d (n={len(df)})",
                           font=dict(size=13))

        for tick_value, tick_label in zip(year_tick_values, year_tick_text):
            fig.add_hline(y=tick_value, line=dict(color="gray", dash="dot"), opacity=0.6)
            fig.add_annotation(x=1.01, xref="paper", y=tick_value, yref="y", text=tick_label, showarrow=False, xanchor="left", yanchor="middle", font=dict(color="gray", size=11))
        fig.update_yaxes(title="Days from Submission to Publication")

        add_unpublished_caption(fig, event_sequences)
        fig.show()

    def metric_2c_sub_to_pub_sem(event_sequences):
        records = sub_to_pub_records(event_sequences)

        if not records:
            return

        df = pd.DataFrame(records)
        mean, std = df["days"].mean(), df["days"].std()
        df = df[(df["days"] - mean).abs() <= 4 * std]

        for date_col, x_label, when in (("submission_date", "Submission Date", "Submission"),
                                        ("publication_date", "Publication Date", "Publication")):
            roll = rolling_mean_sem(df, date_col)
            plot_rolling_mean_sem(roll, f"Rolling Mean Submission-to-Publication Time by {when} Date (±SEM, 90-day window, within 4 SD)", x_label)

    def metric_2d_sub_to_pub_95th(event_sequences):
        records = sub_to_pub_records(event_sequences)

        if not records:
            return

        df = pd.DataFrame(records)
        p95 = df["days"].quantile(0.95)
        trimmed = df[df["days"] <= p95]

        for year_col, x_label, when in (("submission_year", "Submission Year", "Submission"),
                                        ("publication_year", "Publication Year", "Publication")):
            binned = trimmed.sort_values(year_col).copy()
            binned[year_col] = binned[year_col].astype(str)
            fig = px.box(binned, x=year_col, y="days", points="all",
                         hover_data=["dataset_id", "publication_date"],
                         title=f"Submission-to-Publication Time by {when} Year (≤ 95th pct, {p95:.0f} d)",
                         labels={year_col: x_label, "days": "Days from Submission to Publication", "dataset_id": "Dataset ID", "publication_date": "Publication Date"})
            fig.update_traces(boxmean="sd")
            if year_col == "submission_year":
                add_unpublished_caption(fig, event_sequences)
            fig.show()

    def metric_2e_sub_to_pub_by_pub_year(event_sequences):
        records = sub_to_pub_records(event_sequences)

        if not records:
            return

        df = pd.DataFrame(records).sort_values("publication_year")
        df["publication_year"] = df["publication_year"].astype(str)

        fig = px.box(df, x="publication_year", y="days", points="all",
                     hover_data=["dataset_id", "publication_date"],
                     title="Submission-to-Publication Time by Publication Year",
                     labels={"publication_year": "Publication Year", "days": "Days from Submission to Publication", "dataset_id": "Dataset ID", "publication_date": "Publication Date"})
        fig.update_traces(boxmean="sd")
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
            fig = px.bar(df, x="year", y="size", color="type", title="Top 10 Curator Event Types per Year", labels={"year": "Year", "size": "Event Count", "type": "Event Type"})
            fig.update_layout(barmode="stack")
            fig.show()

    def metric_4_total_curation_events(temporal_report, event_sequences, status_delimited_sequences):
        curation_event_records = []
        for dataset_id, dataset_record in temporal_report.items():
            if is_excluded_dataset(dataset_id) or graph_excluded(dataset_id, None, event_sequences):
                continue

            first_request = first_request_date(dataset_id, event_sequences)

            if not first_request:
                continue

            publication_date = first_publication_date(dataset_id, event_sequences)
            dataset_sequences = status_delimited_sequences.get(dataset_id, [])
            # first publication cycle only: events within [submission, publication]
            total_curation_events = 0
            for sequence in dataset_sequences:
                for event in sequence:
                    created = parse_iso8601(event.get("createdAt"))
                    if created is None or created < first_request:
                        continue
                    if publication_date is not None and created > publication_date:
                        continue
                    total_curation_events += 1
            curation_event_records.append({"dataset_id": dataset_id, "first_request_year": fiscal_year(first_request), "publication_date": publication_date, "total_curation_events": total_curation_events})
        if curation_event_records:
            fig = px.box(pd.DataFrame(curation_event_records), x="first_request_year", y="total_curation_events", hover_data=["dataset_id", "publication_date"], points="all", title="Total Curation Changes per Dataset by Submission Year", labels={"first_request_year": "Submission Year", "total_curation_events": "Total Curation Changes", "dataset_id": "Dataset ID", "publication_date": "Publication Date"})
            fig.update_traces(hovertemplate="Submission Year=%{x}<br>Total Curation Sessions=%{y}<br>Dataset ID=%{customdata[0]}<br>Publication Date=%{customdata[1]}<extra></extra>")
            fig.show()

    def metric_4b_session_timespans(curation_clusters, event_sequences):
        curation_session_timespan_records = []
        for dataset_id, dataset_sequences in curation_clusters.items():
            if is_excluded_dataset(dataset_id) or graph_excluded(dataset_id, None, event_sequences):
                continue
            first_request = first_request_date(dataset_id, event_sequences)
            if not first_request:
                continue
            publication_date = first_publication_date(dataset_id, event_sequences)
            for cluster in first_cycle_clusters(dataset_sequences, first_request, publication_date):
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
            if is_excluded_dataset(dataset_id) or graph_excluded(dataset_id, None, event_sequences):
                continue

            first_request = first_request_date(dataset_id, event_sequences)

            if not first_request:
                continue

            publication_date = first_publication_date(dataset_id, event_sequences)

            total_hours = 0

            for cluster in first_cycle_clusters(dataset_sequences, first_request, publication_date):
                session_timespan_hours = curation_session_timespan_hours(cluster)
                if session_timespan_hours is not None:
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

            window_days = 180
            roll = rolling_mean_std(df, "first_request_date", "total_curation_hours", window=f"{window_days}D")
            fig.add_trace(go.Scatter(x=roll["date"], y=roll["mean"] + roll["std"], mode="lines",
                                     line=dict(width=0), showlegend=False, hoverinfo="skip"))
            fig.add_trace(go.Scatter(x=roll["date"], y=roll["mean"] - roll["std"], mode="lines",
                                     line=dict(width=0), fill="tonexty", fillcolor="rgba(128,0,128,0.15)",
                                     name="±1 SD", hoverinfo="skip"))

            first_request_dates = [record["first_request_date"] for record in total_time_records]
            total_hours_list = [record["total_curation_hours"] for record in total_time_records]
            fig.add_trace(go.Scatter(
                x=first_request_dates,
                y=total_hours_list,
                mode="markers",
                marker=dict(size=10, opacity=0.5, color="purple"),
                text=[f"Dataset ID: {record['dataset_id']}<br>Submission Date: {format_datetime(record['first_request_date'])}<br>Publication Date: {format_datetime(record.get('publication_date'))}<br>Total Curation Time: {record['total_curation_hours']:.2f} hours" for record in total_time_records],
                hoverinfo="text",
                name="Datasets",
            ))

            fig.add_trace(go.Scatter(x=roll["date"], y=roll["mean"], mode="lines",
                                     line=dict(color="black", width=2), name=f"Rolling average ({window_days}-day window)", hoverinfo="skip"))

            fig.update_xaxes(title="Submission Date", type="date")
            fig.update_yaxes(title="Total Curation Time (Hours)")
            fig.update_layout(title="Total Time Spent Curating per Dataset by Submission Date")
            fig.show()

    def metric_4f_curation_touch_days(curation_clusters, event_sequences):
        records = []
        for dataset_id, dataset_sequences in curation_clusters.items():
            if is_excluded_dataset(dataset_id) or graph_excluded(dataset_id, None, event_sequences):
                continue

            first_request = first_request_date(dataset_id, event_sequences)
            publication_date = first_publication_date(dataset_id, event_sequences)

            if not first_request or not publication_date or publication_date <= first_request:
                continue

            days = set()
            for cluster in first_cycle_clusters(dataset_sequences, first_request, publication_date):
                start = parse_iso8601(cluster.get("start"))
                # every calendar date the cluster spans (start .. end inclusive)
                end = parse_iso8601(cluster.get("end"))
                last = end if (end is not None and end >= start) else start
                day = start.date()
                while day <= last.date():
                    days.add(day)
                    day += datetime.timedelta(days=1)

            days_to_pub = (publication_date - first_request).days
            if not days or days_to_pub <= 0:
                continue

            records.append({
                "dataset_id": dataset_id,
                "touch_ratio": len(days) / days_to_pub,
            })

        if not records:
            return

        df = pd.DataFrame(records)
        fig = px.histogram(
            df, x="touch_ratio",
            title="Fraction of Submission-to-Publication Days with a Curation Touch",
            labels={"touch_ratio": "Curation-Touch Days / Days from Submission to Publication"},
        )
        fig.update_layout(yaxis_title="Number of Datasets")
        fig.show()

    def metric_4d_gaps_between_sessions(curation_clusters, event_sequences):
        gap_records = []
        for dataset_id, dataset_sequences in curation_clusters.items():
            if is_excluded_dataset(dataset_id) or graph_excluded(dataset_id, None, event_sequences):
                continue
            first_request = first_request_date(dataset_id, event_sequences)
            if not first_request:
                continue
            publication_date = first_publication_date(dataset_id, event_sequences)

            for sequence in dataset_sequences:
                # first publication cycle only: gaps between consecutive in-window sessions
                clusters = [c for c in sequence.get("clusters", []) if cluster_in_first_cycle(c, first_request, publication_date)]
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
            if is_excluded_dataset(dataset_id) or graph_excluded(dataset_id, None, event_sequences):
                continue
            first_request = first_request_date(dataset_id, event_sequences)
            if not first_request:
                continue
            publication_date = first_publication_date(dataset_id, event_sequences)

            total_gap_hours = 0
            gap_count = 0
            for sequence in dataset_sequences:
                # first publication cycle only: gaps between consecutive in-window sessions
                clusters = [c for c in sequence.get("clusters", []) if cluster_in_first_cycle(c, first_request, publication_date)]
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
                text=[f"Dataset ID: {record['dataset_id']}<br>Submission Date: {format_datetime(record['first_request_date'])}<br>Publication Date: {format_datetime(record.get('publication_date'))}<br>Total Gap Time: {record['total_gap_hours']:.2f} hours<br>Gap Count: {record['gap_count']}" for record in total_gaps_records],
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
            
            fig.update_xaxes(title="Submission Date", type="date")
            fig.update_yaxes(title="Total Gap Time (Hours)")
            fig.update_layout(title="Total Gaps Between Curation Sessions per Dataset by Submission Date")
            fig.show()

    def metric_5_datasets_vs_sessions(curation_clusters, event_sequences):
        cluster_records = []
        for dataset_id, dataset_sequences in curation_clusters.items():
            if is_excluded_dataset(dataset_id) or graph_excluded(dataset_id, None, event_sequences):
                continue

            first_request = first_request_date(dataset_id, event_sequences)

            if not first_request:
                continue

            publication_date = first_publication_date(dataset_id, event_sequences)
            cluster_total = len(first_cycle_clusters(dataset_sequences, first_request, publication_date))

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
            fig.add_trace(go.Scatter(x=first_request_dates, y=total_clusters, mode="markers", marker=dict(size=10, opacity=0.5, color="black"), text=[f"Dataset ID: {record['dataset_id']}<br>Submission Date: {format_datetime(record['first_request_date'])}<br>Publication Date: {format_datetime(record.get('publication_date'))}<br>Total Curations: {record['total_clusters']}<br>Status Sequences: {record['sequence_count']}" for record in cluster_records], hoverinfo="text", name="Datasets"))
            overlay_rolling(fig, pd.DataFrame(cluster_records), "first_request_date", "total_clusters")
            fig.update_xaxes(title="Submission Date")
            fig.update_yaxes(title="Curation Sessions")
            fig.update_layout(title="Curation Sessions per Dataset vs Submission Date")
            fig.show()
            fig = px.box(pd.DataFrame(cluster_records), x="first_request_year", y="total_clusters", hover_data=["dataset_id", "publication_date"], points="all", title="Curation Sessions per Dataset by Submission Year", labels={"first_request_year": "Submission Year", "total_clusters": "Curation Sessions", "dataset_id": "Dataset ID", "publication_date": "Publication Date"})
            fig.show()

    def metric_6_avg_curation_density(curation_clusters, event_sequences):
        cluster_length_records = []
        for dataset_id, dataset_sequences in curation_clusters.items():
            if is_excluded_dataset(dataset_id) or graph_excluded(dataset_id, None, event_sequences):
                continue

            first_request = first_request_date(dataset_id, event_sequences)

            if not first_request:
                continue

            publication_date = first_publication_date(dataset_id, event_sequences)
            cluster_lengths = [
                cluster.get("length")
                for cluster in first_cycle_clusters(dataset_sequences, first_request, publication_date)
            ]

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
            fig.add_trace(go.Scatter(x=first_request_dates, y=average_cluster_lengths, mode="markers", marker=dict(size=10, opacity=0.5, color="black"), text=[f"Dataset ID: {record['dataset_id']}<br>Submission Date: {format_datetime(record['first_request_date'])}<br>Publication Date: {format_datetime(record.get('publication_date'))}<br>Average Curation Density: {record['average_cluster_length']:.2f}<br>Clusters: {record['cluster_count']}" for record in cluster_length_records], hoverinfo="text", name="Datasets"))
            overlay_rolling(fig, pd.DataFrame(cluster_length_records), "first_request_date", "average_cluster_length")
            fig.update_xaxes(title="Submission Date")
            fig.update_yaxes(title="Average Curation Density")
            fig.update_layout(title="Average Curation Density per Dataset vs Submission Date")
            fig.show()
            fig = px.box(pd.DataFrame(cluster_length_records), x="first_request_year", y="average_cluster_length", hover_data=["dataset_id", "publication_date"], points="all", title="Average Curation Density per Dataset by Submission Year", labels={"first_request_year": "Submission Year", "average_cluster_length": "Average Curation Density", "dataset_id": "Dataset ID", "publication_date": "Publication Date"})
            fig.show()

    def metric_7_category_mix_by_year(curator_categories, event_sequences):
        per_dataset = curator_categories.get("per_dataset", {})
        records = []
        for dataset_id, category_counts in per_dataset.items():
            if is_excluded_dataset(dataset_id) or graph_excluded(dataset_id, None, event_sequences):
                continue
            first_request = first_request_date(dataset_id, event_sequences)
            if not first_request:
                continue
            for category, count in category_counts.items():
                if category == "Other":
                    continue
                records.append({"year": fiscal_year(first_request), "category": category, "count": count})
        if not records:
            return

        df = pd.DataFrame(records).groupby(["year", "category"])["count"].sum().reset_index()
        # order legend by overall volume
        ordered = list(df.groupby("category")["count"].sum().sort_values(ascending=False).index)

        fig = px.bar(
            df, x="year", y="count", color="category",
            category_orders={"category": ordered},
            title="Curator Event Category Mix per Submission Year (Counts)",
            labels={"year": "Submission Year", "count": "Curator Events", "category": "Category"},
        )
        fig.update_layout(barmode="stack")
        fig.show()

        year_totals = df.groupby("year")["count"].transform("sum")
        df["pct"] = df["count"] / year_totals * 100
        fig = px.bar(
            df, x="year", y="pct", color="category",
            category_orders={"category": ordered},
            title="Curator Event Category Mix per Submission Year (% within year)",
            labels={"year": "Submission Year", "pct": "% of Curator Events", "category": "Category"},
        )
        fig.update_layout(barmode="stack")
        fig.update_yaxes(range=[75, 100], ticksuffix="%")
        fig.show()

    def metric_7b_metadata_types_by_pub_year(curator_categories, event_sequences):
        """Metadata-subcategory mix per publication year (published datasets only)"""
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

    def metric_7c_category_mix_by_event_year(curator_categories):
        """curator event category mix binned by the event's own year, restricted to events
        inside complete curation windows. Precomputed in categorize_curator_events.py so it
        shares metric_7's categories, including the filename-based Metadata File Operations."""
        by_year = curator_categories.get("category_by_event_year_in_window", {})
        records = [
            {"year": int(year), "category": category, "count": count}
            for category, years in by_year.items()
            for year, count in years.items()
        ]

        if not records:
            return

        df = pd.DataFrame(records)
        ordered = list(df.groupby("category")["count"].sum().sort_values(ascending=False).index)

        fig = px.bar(
            df, x="year", y="count", color="category",
            category_orders={"category": ordered},
            title="Curator Event Category Mix by Event Year, In Complete Curation Windows (Counts)",
            labels={"year": "Event Year", "count": "Curator Events", "category": "Category"},
        )
        fig.update_layout(barmode="stack")
        fig.show()

        year_totals = df.groupby("year")["count"].transform("sum")
        df["pct"] = df["count"] / year_totals * 100
        fig = px.bar(
            df, x="year", y="pct", color="category",
            category_orders={"category": ordered},
            title="Curator Event Category Mix by Event Year, In Complete Curation Windows (% within year)",
            labels={"year": "Event Year", "pct": "% of Curator Events", "category": "Category"},
        )
        fig.update_layout(barmode="stack")
        fig.update_yaxes(range=[50, 100], ticksuffix="%")
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

            req_date = first_request_date(dataset_id, event_sequences)

            if graph_excluded(dataset_id, dataset_record, event_sequences) or \
               (req_date and effective_after_event(dataset_record, req_date)) or \
               effective_after_event(dataset_record, pub_date):
                continue

            pub_types = drop_excluded_error_types(
                error_types_near_effective(dataset_record, pub_date)
            )
            
            if pub_types:
                for label in {error_label(error_type) for error_type in pub_types}:
                    pub_dataset_counts[label] += 1

            req_date = first_request_date(dataset_id, event_sequences)
            if req_date:
                req_types = drop_excluded_error_types(
                    error_types_near_effective(dataset_record, req_date)
                )
                if req_types:
                    for label in {error_label(error_type) for error_type in req_types}:
                        req_dataset_counts[label] += 1
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
        fig.update_yaxes(tickfont=dict(size=13))
        fig.show()
        fig2 = px.bar(
            req_df, x="dataset_count", y="type", orientation="h",
            title="Most Common Error Types at Submission (by # of datasets)",
            labels={"dataset_count": "Number of Datasets", "type": "Error Type"},
        )
        fig2.update_yaxes(tickfont=dict(size=13))
        fig2.show()

    def metric_1f_resolved_by_publication(temporal_report, event_sequences):
        resolved_counts = Counter()

        for dataset_id, dataset_record in temporal_report.items():
            if is_excluded_dataset(dataset_id):
                continue

            req_date = first_request_date(dataset_id, event_sequences)
            pub_date = first_publication_date(dataset_id, event_sequences)

            if not dataset_record.get("error_graph") or not req_date or not pub_date:
                continue

            if graph_excluded(dataset_id, dataset_record, event_sequences) or \
               effective_after_event(dataset_record, req_date) or \
               effective_after_event(dataset_record, pub_date):
                continue

            req_types = drop_excluded_error_types(error_types_near_effective(dataset_record, req_date))
            pub_types = drop_excluded_error_types(error_types_near_effective(dataset_record, pub_date))

            for label in {error_label(error_type) for error_type in set(req_types or {}) - set(pub_types or {})}:
                resolved_counts[label] += 1

        if not resolved_counts:
            return

        df = pd.DataFrame(resolved_counts.most_common(20), columns=["type", "dataset_count"]).iloc[::-1]
        fig = px.bar(
            df, x="dataset_count", y="type", orientation="h",
            title="Error Types Common at Submission but Resolved by Publication (by # of datasets)",
            labels={"dataset_count": "Number of Datasets", "type": "Error Type"},
        )
        fig.update_yaxes(tickfont=dict(size=13))
        fig.show()

    def metric_1j_error_types_subsequent_pub(temporal_report, event_sequences):
        records = []
        for dataset_id, dataset_record in temporal_report.items():
            if is_excluded_dataset(dataset_id) or graph_excluded(dataset_id, dataset_record, event_sequences):
                continue
            error_graph = dataset_record.get("error_graph", {})
            if not error_graph:
                continue
            for pub_date in publication_dates(dataset_id, event_sequences)[1:]:
                if effective_after_event(dataset_record, pub_date):
                    continue
                pub_types = drop_excluded_error_types(
                    error_types_near_effective(dataset_record, pub_date)
                )
                if pub_types:
                    for error_type, count in pub_types.items():
                        records.append({"year": fiscal_year(pub_date), "type": error_type, "count": count, "dataset_id": dataset_id})
        plot_error_types_by_year(records, "Top 10 Error Types at Subsequent Publications by Year (% within year)", normalize=True)

    def metric_1k_error_type_counts_subsequent_sub(temporal_report, event_sequences):
        sub_records = []
        for dataset_id, dataset_record in temporal_report.items():
            if is_excluded_dataset(dataset_id) or graph_excluded(dataset_id, dataset_record, event_sequences):
                continue
            error_graph = dataset_record.get("error_graph", {})
            if not error_graph:
                continue
            for sub_date in submission_dates(dataset_id, event_sequences)[1:]:
                if effective_after_event(dataset_record, sub_date):
                    continue
                sub_types = drop_excluded_error_types(
                    error_types_near_effective(dataset_record, sub_date)
                )
                sub_records.append({
                    "dataset_id": dataset_id,
                    "year": fiscal_year(sub_date),
                    "error_type_count": len(sub_types) if sub_types else 0,
                })
        if not sub_records:
            return
        df = pd.DataFrame(sub_records)
        fig = px.box(
            df, x="year", y="error_type_count", hover_data=["dataset_id"], points="all",
            title="Number of Distinct Error Types per Dataset by Year (At Subsequent Submissions)",
            labels={"year": "Year", "error_type_count": "Distinct Error Types", "dataset_id": "Dataset ID"},
        )
        fig.show()

    def _first_cycle_error_records(temporal_report, event_sequences):
        # distinct errors at submission and publication per dataset (matrix-consistent),
        # first cycle only, skipping failed exports
        records = []
        for dataset_id, dataset_record in temporal_report.items():
            if is_excluded_dataset(dataset_id) or graph_excluded(dataset_id, dataset_record, event_sequences):
                continue
            submission = first_request_date(dataset_id, event_sequences)
            publication = first_publication_date(dataset_id, event_sequences)
            if not submission or not publication:
                continue
            if export_failed_at(dataset_record, submission) or export_failed_at(dataset_record, publication):
                continue
            records.append({
                "dataset_id": dataset_id,
                "at_submission": distinct_errors_at(dataset_record, submission),
                "at_publication": distinct_errors_at(dataset_record, publication),
            })
        return records

    def metric_1l_total_errors_removed(temporal_report, event_sequences):
        records = _first_cycle_error_records(temporal_report, event_sequences)
        if not records:
            return
        df = pd.DataFrame(records)
        df["errors_removed"] = df["at_submission"] - df["at_publication"]
        fig = px.box(
            df, y="errors_removed", points="all", hover_data=["dataset_id", "at_submission", "at_publication"],
            title="Distinct Errors Types Removed from Submission to Publication (per Dataset, all)",
            labels={"errors_removed": "Errors Removed (Submission − Publication)", "dataset_id": "Dataset ID"},
        )
        fig.show()

    def metric_1m_distinct_errors_sub_vs_pub(temporal_report, event_sequences):
        records = _first_cycle_error_records(temporal_report, event_sequences)
        if not records:
            return
        rows = []
        for record in records:
            rows.append({"dataset_id": record["dataset_id"], "phase": "At Submission", "distinct": record["at_submission"]})
            rows.append({"dataset_id": record["dataset_id"], "phase": "At Publication", "distinct": record["at_publication"]})
        df = pd.DataFrame(rows)
        fig = px.box(
            df, x="phase", y="distinct", points="all", hover_data=["dataset_id"],
            category_orders={"phase": ["At Submission", "At Publication"]},
            title="Distinct Errors per Dataset at Submission vs Publication (all)",
            labels={"phase": "", "distinct": "Distinct Errors", "dataset_id": "Dataset ID"},
        )
        fig.show()

    def metric_1g_avg_distinct_errors_by_period(temporal_report, event_sequences):
        """distinct errors at submission per dataset, averaged over datasets binned by the submission year, quarter, month."""
        records = []

        for dataset_id, dataset_record in temporal_report.items():
            if is_excluded_dataset(dataset_id) or graph_excluded(dataset_id, dataset_record, event_sequences):
                continue
            if not dataset_record.get("error_graph"):
                continue

            submission = first_request_date(dataset_id, event_sequences)

            if submission is None or effective_after_event(dataset_record, submission):
                continue

            records.append({"submission": submission, "distinct": distinct_errors_at(dataset_record, submission)})

        if not records:
            return

        df = pd.DataFrame(records)
        df["submission"] = pd.to_datetime(df["submission"], utc=True)

        # fiscal year (Feb 1 boundary) for the Year bin, matching the other error graphs
        fiscal = df["submission"].dt.year - (df["submission"].dt.month < 2).astype(int)
        periods = {
            "Year": fiscal.astype(str),
            "Quarter": df["submission"].dt.year.astype(str) + "-Q" + df["submission"].dt.quarter.astype(str),
            "Month": df["submission"].dt.strftime("%Y-%m"),
        }

        for label, period in periods.items():
            grouped = df.assign(period=period).groupby("period")["distinct"].mean().reset_index()
            fig = px.bar(
                grouped, x="period", y="distinct",
                title=f"Average Distinct Errors per Dataset at Submission (by {label})",
                labels={"period": label, "distinct": "Avg Distinct Errors / Dataset"},
            )
            fig.show()

    def metric_1h_soda_vs_nonsoda_submission(temporal_report, event_sequences):
        """total distinct errors per dataset at submission, SODA vs non-SODA 3.0.0 submissions excluded."""
        records = []

        for dataset_id, dataset_record in temporal_report.items():
            if is_excluded_dataset(dataset_id) or graph_excluded(dataset_id, dataset_record, event_sequences):
                continue
            if not dataset_record.get("error_graph"):
                continue

            submission = first_request_date(dataset_id, event_sequences)

            if submission is None or effective_after_event(dataset_record, submission):
                continue
            if template_version_near(dataset_record, submission) == "3.0.0":
                continue

            group = "SODA" if dataset_record.get("uses_soda") else "non-SODA"
            records.append({"group": group, "distinct": distinct_errors_at(dataset_record, submission), "dataset_id": dataset_id})

        if not records:
            return

        df = pd.DataFrame(records)
        fig = px.box(
            df, x="group", y="distinct", points="all", hover_data=["dataset_id"],
            title="Distinct Errors per Dataset at Submission: SODA vs non-SODA (3.0.0 excluded)",
            labels={"group": "", "distinct": "Distinct Errors / Dataset", "dataset_id": "Dataset ID"},
        )
        fig.show()

    def metric_1i_lab_improvement_across_submissions(temporal_report, event_sequences):
        """errors at submission across a lab's (= award number's) successive submissions:
        a faint line per lab (>=2 datasets), plus a bold mean-across-labs line."""
        ordinal_words = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth",
                         "Seventh", "Eighth", "Ninth", "Tenth"]

        def ordinal_label(n):
            return f"{ordinal_words[n - 1]} Submission" if n <= len(ordinal_words) else f"Submission #{n}"

        by_lab = defaultdict(list)

        for dataset_id, dataset_record in temporal_report.items():
            #if is_excluded_dataset(dataset_id) or graph_excluded(dataset_id, dataset_record, event_sequences):
            #    continue
            if not dataset_record.get("error_graph"):
                continue

            submission = first_request_date(dataset_id, event_sequences)

            if submission is None or effective_after_event(dataset_record, submission):
                continue

            award = award_number_near(dataset_record, submission)

            if not award or award == "<unknown>":
                continue

            by_lab[award].append((submission, distinct_errors_at(dataset_record, submission), dataset_id))

        # cap at the first 8 submissions per lab
        cap = 8
        by_lab = {award: sorted(points)[:cap] for award, points in by_lab.items() if len(points) >= 2}

        if not by_lab:
            return

        max_submissions = max(len(points) for points in by_lab.values())
        categories = [ordinal_label(n) for n in range(1, max_submissions + 1)]

        fig = go.Figure()
        by_ordinal = defaultdict(list)

        for award, points in by_lab.items():
            labels = [ordinal_label(n) for n in range(1, len(points) + 1)]
            distinct = [value for _, value, _ in points]

            for n, value in enumerate(distinct, start=1):
                by_ordinal[n].append(value)

            fig.add_trace(go.Scatter(
                x=labels, y=distinct, mode="lines+markers",
                line=dict(color="darkblue", width=2), marker=dict(size=5), opacity=0.5,
                showlegend=False, hoverinfo="text",
                text=[f"Award: {award}<br>{label}<br>Errors at Submission: {value}<br>Dataset ID: {dataset_id}"
                      for label, value, (_, _, dataset_id) in zip(labels, distinct, points)],
            ))

        # only average over ordinals shared by enough labs, so the tail isn't a single lab
        ordinals = [n for n in sorted(by_ordinal) if len(by_ordinal[n]) >= 3]
        means = [sum(by_ordinal[n]) / len(by_ordinal[n]) for n in ordinals]

        fig.add_trace(go.Scatter(
            x=[ordinal_label(n) for n in ordinals], y=means, mode="lines+markers",
            line=dict(color="darkred", width=5), marker=dict(size=9, color="darkred"),
            name="Mean across labs",
            text=[f"{ordinal_label(n)}<br>Mean: {mean:.2f}<br>Labs: {len(by_ordinal[n])}"
                  for n, mean in zip(ordinals, means)],
            hoverinfo="text",
        ))

        fig.update_layout(
            title=f"Errors at Submission Across a Lab's Successive Submissions (labs with ≥2 datasets, n={len(by_lab)})",
            xaxis_title="Submission (same award number)",
            yaxis_title="Errors at Submission",
        )
        fig.update_xaxes(categoryorder="array", categoryarray=categories)
        fig.show()

    def metric_8_submissions_per_year(temporal_report, event_sequences):
        """number of dataset submissions per submission year (histogram, one bin per year)"""
        years = []
        for dataset_id in temporal_report:
            #if is_excluded_dataset(dataset_id):
            #    continue
            submission = first_request_date(dataset_id, event_sequences, floor=False)
            if submission is None:
                continue
            years.append(fiscal_year(submission))

        if not years:
            return

        df = pd.DataFrame({"submission_year": years})
        fig = px.histogram(df, x="submission_year",
                           title="Dataset Submissions per Submission Year",
                           labels={"submission_year": "Submission Year"})
        fig.update_traces(xbins=dict(size=1))
        fig.update_xaxes(dtick=1)
        fig.update_layout(bargap=0.1, yaxis_title="Number of Datasets")
        fig.show()
        
        years = []
        for dataset_id in temporal_report:
            #if is_excluded_dataset(dataset_id):
            #    continue
            submission = first_request_date(dataset_id, event_sequences, floor=False)
            if submission is None:
                continue
            try:
                pub = first_publication_date(dataset_id, event_sequences)
                if pub is None:
                    continue
            except KeyError:
                continue
            years.append(fiscal_year(submission))

        if not years:
            return

        df = pd.DataFrame({"submission_year": years})
        fig = px.histogram(df, x="submission_year",
                            title="Dataset Submissions per Submission Year",
                            labels={"submission_year": "Submission Year"})
        fig.update_traces(xbins=dict(size=1))
        fig.update_xaxes(dtick=1)
        fig.update_layout(bargap=0.1, yaxis_title="Number of Datasets")
        fig.show()

    def metric_8b_publications_per_year(temporal_report, event_sequences):
        """number of datasets published per publication year (histogram, one bin per year)"""
        years = []
        for dataset_id in temporal_report:
            if is_excluded_dataset(dataset_id):
                continue
            pub = first_publication_date(dataset_id, event_sequences)
            if pub is None:
                continue
            years.append(fiscal_year(pub))

        if not years:
            return

        df = pd.DataFrame({"publication_year": years})
        fig = px.histogram(df, x="publication_year",
                           title="Datasets Published per Publication Year",
                           labels={"publication_year": "Publication Year"})
        fig.update_traces(xbins=dict(size=1))
        fig.update_xaxes(dtick=1)
        fig.update_layout(bargap=0.1, yaxis_title="Number of Datasets")
        fig.show()

    def metric_8c_years_to_pub_by_submission_year(event_sequences):
        records = sub_to_pub_records(event_sequences)

        if not records:
            return

        df = pd.DataFrame(records)
        df["years_to_pub"] = df["days"] / 365.0
        df = df.sort_values("submission_year")
        df["submission_year"] = df["submission_year"].astype(str)

        fig = px.histogram(df, x="years_to_pub", facet_col="submission_year", facet_col_wrap=3,
                           title="Years from Submission to Publication, by Submission Year",
                           labels={"years_to_pub": "Years to Publication"})
        fig.update_traces(xbins=dict(size=1))
        fig.update_layout(yaxis_title="Number of Datasets")
        fig.show()

    def metric_9_cluster_length_histogram(temporal_report, curation_clusters, event_sequences):
        stats = cluster_stats(temporal_report, curation_clusters, event_sequences)
        hours = [span for record in stats for span in record["cluster_hours"]]

        if not hours:
            return

        df = pd.DataFrame({"cluster_hours": hours})
        fig = px.histogram(df, x="cluster_hours",
                           title="Number of Curation Sessions by Session Length",
                           labels={"cluster_hours": "Session Length (Hours)"})
        fig.update_layout(bargap=0.05, yaxis_title="Number of Curation Sessions")
        fig.show()

    def metric_9b_total_hours_vs_clusters(temporal_report, curation_clusters, event_sequences):
        stats = cluster_stats(temporal_report, curation_clusters, event_sequences)

        if not stats:
            return

        df = pd.DataFrame(stats)
        fig = px.scatter(df, x="num_clusters", y="total_hours", hover_data=["dataset_id"],
                         title="Estimated Total Curation Hours vs Number of Curation Sessions",
                         labels={"num_clusters": "Number of Curation Sessions", "total_hours": "Total Curation Hours", "dataset_id": "Dataset ID"})
        fig.update_traces(marker=dict(size=9, opacity=0.7))
        fig.show()

    def metric_9c_sub_to_pub_vs_curation_hours(temporal_report, curation_clusters, event_sequences):
        stats = [record for record in cluster_stats(temporal_report, curation_clusters, event_sequences)
                 if record["days_to_pub"] is not None]

        if not stats:
            return

        df = pd.DataFrame(stats)
        fig = px.scatter(df, x="total_hours", y="days_to_pub", hover_data=["dataset_id"],
                         title="Submission-to-Publication Time vs Estimated Curation Hours",
                         labels={"total_hours": "Total Curation Hours", "days_to_pub": "Days from Submission to Publication", "dataset_id": "Dataset ID"})
        fig.update_traces(marker=dict(size=9, opacity=0.7))
        fig.show()

    metric_toggles = {
        "metric_1_standards_adherence": True,
        "metric_1b_error_types": True,
        "metric_1c_removed_errors": False,
        "metric_1d_error_type_counts": True,
        "metric_1e_top_error_types": True,
        "metric_1f_resolved_by_publication": True,
        "metric_1j_error_types_subsequent_pub": False,
        "metric_1k_error_type_counts_subsequent_sub": False,
        "metric_1l_total_errors_removed": True,
        "metric_1m_distinct_errors_sub_vs_pub": True,
        "metric_1g_avg_distinct_errors_by_period": True,
        "metric_1h_soda_vs_nonsoda_submission": True,
        "metric_1i_lab_improvement_across_submissions": True,
        "metric_2_time_to_publication": True,
        "metric_2b_quarters_to_publication": False,
        "metric_2c_sub_to_pub_sem": True,
        "metric_2d_sub_to_pub_95th": True,
        "metric_2e_sub_to_pub_by_pub_year": True,
        "metric_3_event_types": False,
        "metric_4_total_curation_events": False,
        "metric_4b_session_timespans": False,
        "metric_4c_total_curation_time": False,
        "metric_4d_gaps_between_sessions": False,
        "metric_4e_total_gaps_per_dataset": False,
        "metric_4f_curation_touch_days": True,
        "metric_5_datasets_vs_sessions": False,
        "metric_6_avg_curation_density": False,
        "metric_7_category_mix_by_year": True,
        "metric_7b_metadata_types_by_pub_year": False,
        "metric_7c_category_mix_by_event_year": True,
        "metric_8_submissions_per_year": True,
        "metric_8b_publications_per_year": True,
        "metric_8c_years_to_pub_by_submission_year": True,
        "metric_9_cluster_length_histogram": True,
        "metric_9b_total_hours_vs_clusters": True,
        "metric_9c_sub_to_pub_vs_curation_hours": True,
    }

    # ad hoc: run only these metrics without editing the toggles above (empty set to use the toggles as configured)
    SOLO_METRICS = {
        "metric_9_cluster_length_histogram",
        "metric_9b_total_hours_vs_clusters",
        "metric_9c_sub_to_pub_vs_curation_hours",
        "metric_1_standards_adherence",
        "metric_2_time_to_publication",
        "metric_1h_soda_vs_nonsoda_submission",
        "metric_1e_top_error_types",
        "metric_1f_resolved_by_publication",
        "metric_2_time_to_publication",
        "metric_1d_error_type_counts",
        "metric_7c_category_mix_by_event_year",
        "metric_1i_lab_improvement_across_submissions",
        "metric_4f_curation_touch_days",
        "metric_4c_total_curation_time",
        "metric_1l_total_errors_removed",
        "metric_1m_distinct_errors_sub_vs_pub"
    }
    SOLO_METRICS = {
        "metric_7c_category_mix_by_event_year"
    }
    # for 4f, plot as a histogram; ratio of days with cur touch divided by day sub->pub
    if SOLO_METRICS:
        metric_toggles = {key: key in SOLO_METRICS for key in metric_toggles}

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
    if metric_toggles.get("metric_1f_resolved_by_publication"):
        metric_1f_resolved_by_publication(temporal_report, event_sequences)
    if metric_toggles.get("metric_1j_error_types_subsequent_pub"):
        metric_1j_error_types_subsequent_pub(temporal_report, event_sequences)
    if metric_toggles.get("metric_1k_error_type_counts_subsequent_sub"):
        metric_1k_error_type_counts_subsequent_sub(temporal_report, event_sequences)
    if metric_toggles.get("metric_1l_total_errors_removed"):
        metric_1l_total_errors_removed(temporal_report, event_sequences)
    if metric_toggles.get("metric_1m_distinct_errors_sub_vs_pub"):
        metric_1m_distinct_errors_sub_vs_pub(temporal_report, event_sequences)
    if metric_toggles.get("metric_1g_avg_distinct_errors_by_period"):
        metric_1g_avg_distinct_errors_by_period(temporal_report, event_sequences)
    if metric_toggles.get("metric_1h_soda_vs_nonsoda_submission"):
        metric_1h_soda_vs_nonsoda_submission(temporal_report, event_sequences)
    if metric_toggles.get("metric_1i_lab_improvement_across_submissions"):
        metric_1i_lab_improvement_across_submissions(temporal_report, event_sequences)
    if metric_toggles.get("metric_2_time_to_publication"):
        metric_2_time_to_publication(event_sequences)
    if metric_toggles.get("metric_2b_quarters_to_publication"):
        metric_2b_quarters_to_publication(event_sequences)
    if metric_toggles.get("metric_2c_sub_to_pub_sem"):
        metric_2c_sub_to_pub_sem(event_sequences)
    if metric_toggles.get("metric_2d_sub_to_pub_95th"):
        metric_2d_sub_to_pub_95th(event_sequences)
    if metric_toggles.get("metric_2e_sub_to_pub_by_pub_year"):
        metric_2e_sub_to_pub_by_pub_year(event_sequences)
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
    if metric_toggles.get("metric_4f_curation_touch_days"):
        metric_4f_curation_touch_days(curation_clusters, event_sequences)
    if metric_toggles.get("metric_5_datasets_vs_sessions"):
        metric_5_datasets_vs_sessions(curation_clusters, event_sequences)
    if metric_toggles.get("metric_6_avg_curation_density"):
        metric_6_avg_curation_density(curation_clusters, event_sequences)
    if metric_toggles.get("metric_7_category_mix_by_year"):
        metric_7_category_mix_by_year(curator_categories, event_sequences)
    if metric_toggles.get("metric_7b_metadata_types_by_pub_year"):
        metric_7b_metadata_types_by_pub_year(curator_categories, event_sequences)
    if metric_toggles.get("metric_7c_category_mix_by_event_year"):
        metric_7c_category_mix_by_event_year(curator_categories)
    if metric_toggles.get("metric_8_submissions_per_year"):
        metric_8_submissions_per_year(temporal_report, event_sequences)
    if metric_toggles.get("metric_8b_publications_per_year"):
        metric_8b_publications_per_year(temporal_report, event_sequences)
    if metric_toggles.get("metric_8c_years_to_pub_by_submission_year"):
        metric_8c_years_to_pub_by_submission_year(event_sequences)
    if metric_toggles.get("metric_9_cluster_length_histogram"):
        metric_9_cluster_length_histogram(temporal_report, curation_clusters, event_sequences)
    if metric_toggles.get("metric_9b_total_hours_vs_clusters"):
        metric_9b_total_hours_vs_clusters(temporal_report, curation_clusters, event_sequences)
    if metric_toggles.get("metric_9c_sub_to_pub_vs_curation_hours"):
        metric_9c_sub_to_pub_vs_curation_hours(temporal_report, curation_clusters, event_sequences)

    # for publication: change temporal_report.json to use the subset of the curation exports we actually used
    # for publication: change pennsieve event list to anaonymize users and events and dataset uuids + date shifting + dataset titles
    
    
    # instead of tampermonkey, make a Python script to pull from Cassava
    # standards adherence greapph use set subtraction
    # standard adherence graph; soda, remove template version markers
    # add a third standard adherence graph, combined soda and non soda
    # exclude protocol_url_or_doi missing at the top level (#/) only (but keep #/meta)
        # dig for examples of this
    # exclude not valid under any JSON schema (anyOf) at the top level (but keep #/meta)
    # change subsequent top 10 errors to be at submission not publication
    # for soda vs non-soda, use N=... for soda and nonsoda
    # add standard deviation and std error bars to the mean line in lab graph; stdev per each timepoint
        # two sets of whiskers, plot another trace with 100% dot alpha
        # mean line should be bold dashed (black?)
        # per-graph lines should be gray 
    # note in the methdos section, first submission is first submission with errors
        # if award number is gone, use publication award number
        # look throug big did to find any datasets published before 2021/2022 (is our cutoff april or feb?)
            # from there, we need to include all of those, anything we don't have errors; errors would be none
            # this can be filtered by using the A8 file to filter for anything whose first submisison is before our data
    # remove unpublished captions from sub->pub time
    # use mean AND median on sub->pub boxes (median as dashed, mean as black)
        # else remove diamonds? frmo sub->pub
    # total time spent curating graph should be black
    
    # b859 goes on the exclude list
    # re download dataset exclusion list
