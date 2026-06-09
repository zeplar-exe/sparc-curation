# This file was created in large part with GitHub Copilot

import csv
import datetime
import json
from collections import defaultdict

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

# Whether to use error_index_graph or error_graph for Metric 1
USE_ERROR_INDEX_GRAPH = True

EXCLUDED_DATASET_IDS = [
    "N:dataset:aa43eda8-b29a-4c25-9840-ecbd57598afc",
    "N:dataset:bc4cc558-727c-4691-ae6d-498b57a10085",
    "N:dataset:ec6ad74e-7b59-409b-8fc7-a304319b6faf",
    "N:dataset:04a5fed9-7ba6-4292-b1a6-9cab5c38895f",
    "N:dataset:a8b2bdc7-54df-46a3-810e-83cdf33cfc3a",
    "N:dataset:2a3d01c0-39d3-464a-8746-54c9d67ebe0f",
    "N:dataset:5c7b9f9d-eeda-4370-a5b8-892020f863c2",
    "N:dataset:33a9f81e-1deb-4c2c-922a-f9eac47ed3e5",
    "N:dataset:1c929cf2-213a-45ed-a867-47a7864c83eb",
    "N:dataset:7a542123-ce8d-4f53-9b74-d259958db1ea",
    "N:dataset:e225ea82-54b5-457f-ad3d-faa640eb13be",
    "N:dataset:bd90e81f-fb33-40ce-93e1-44875efde91b",
    "N:dataset:ffd05134-0014-4fd2-bd10-582499404dc5",
    "N:dataset:edef88f3-bc7c-4105-a104-c12e05b16be9",
    "N:dataset:c5edefba-732d-4c5e-a66c-9081d6885b9e",
    "N:dataset:614ca71d-863f-4bb3-959e-e74e814d8e1a",
    "N:dataset:1d116ae9-5eb7-491c-98bf-6f612ddf13e5",
    "N:dataset:984585fb-b280-4cbb-b18d-3b73542e8590",
    "N:dataset:9eb5e0ff-d6fc-404f-9c76-d5f0a3c3dc02",
    "N:dataset:300fd03e-2dac-4460-a2b7-c24185b7ff07",
    "N:dataset:07a18a83-b044-4042-a4d1-5d472f538a11",
    "N:dataset:8a9ca6e0-12d5-454f-8605-37bbc25d696d",
    "N:dataset:b2573d78-669a-45c5-8af5-8c7df31239ab",
    "N:dataset:96f68ecf-06d7-4207-a413-a0d931552ac7",
    "N:dataset:ae2b1bf9-227b-4eba-b2e2-9fca2897624f"
]


def is_excluded_dataset(dataset_id):
    return dataset_id in EXCLUDED_DATASET_IDS


def parse_iso8601(date_str):
    if not date_str:
        return None
    return datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))


def parse_mmddyyyy(date_str):
    return datetime.datetime.strptime(date_str, "%m-%d-%Y")


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


def first_request_date(dataset_id, event_sequences):
    events = event_sequences.get(dataset_id)
    if not events:
        return None

    request_dates = [parse_iso8601(event.get("request_created")) for event in events]
    request_dates = [request_date for request_date in request_dates if request_date]
    if not request_dates:
        return None

    return min(request_dates)


def last_error_count_at_or_before(target_ts, error_graph):
    c = last_error_types_at_or_before(target_ts, error_graph)
    return sum(c.values()) if c else 0


def last_error_index_at_or_before(target_ts, error_index_graph):
    last_index = None
    for ts_str, error_index in sorted(error_index_graph.items(), key=lambda item: int(item[0])):
        ts_int = int(ts_str)
        if ts_int <= target_ts:
            last_index = error_index
        else:
            break

    return last_index


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


def plot_error_types_by_year(records, title):
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

    fig = px.bar(
        df,
        x="year",
        y="count",
        color="type",
        title=title,
        labels={
            "year": "Year",
            "count": "Error Count",
            "type": "Error Type",
        },
    )
    fig.update_layout(barmode="stack")
    fig.show()


def plot_removed_errors_by_year(records, title):
    if not records:
        return

    df = pd.DataFrame(records)
    df = df.groupby(["year", "type"])["count"].sum().reset_index()
    type_totals = df.groupby("type")["count"].sum().sort_values(ascending=False)
    ordered_types = list(type_totals.index)
    display_labels = {
        error_type: f"{error_type} ({type_totals[error_type]})"
        for error_type in ordered_types
    }
    df["legend_type"] = df["type"].map(display_labels)

    fig = px.bar(
        df,
        x="year",
        y="count",
        color="legend_type",
        title=title,
        category_orders={"legend_type": [display_labels[error_type] for error_type in ordered_types]},
        labels={
            "year": "Year",
            "count": "Removed Error Count",
            "legend_type": "Error Type",
        },
    )
    fig.update_layout(barmode="stack")
    fig.show()


def curation_session_timespan_hours(cluster):
    if not cluster:
        return None

    start = parse_iso8601(cluster.get("start"))
    end = parse_iso8601(cluster.get("end"))
    if not start or not end or end < start:
        return None

    return (end - start).total_seconds() / 3600


with open(TEMPORAL_REPORT) as f, open(EVENT_SEQUENCES) as g, open(STATUS_DELIMITED_SEQUENCES) as h, open(SPARCUR_UPDATES) as i, open(CURATION_CLUSTERS) as j:
    temporal_report = json.load(f)
    event_sequences = json.load(g)
    status_delimited_sequences = json.load(h)
    sparcur_updates = list(csv.DictReader(i))
    curation_clusters = json.load(j)

    # METRIC 1: Standards adherence: error diff over time
    error_diff_records = []

    for dataset_id, dataset_record in temporal_report.items():
        if is_excluded_dataset(dataset_id):
            continue

        events = event_sequences.get(dataset_id)
        if not events:
            continue

        error_graph = (
            dataset_record.get("error_index_graph", {})
            if USE_ERROR_INDEX_GRAPH
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

            error_diff_records.append({
                "dataset_id": dataset_id,
                "request_time": req_time,
                "publish_time": pub_time,
                "error_diff": pub_error_count - req_error_count,
                "req_error_count": req_error_count,
                "pub_error_count": pub_error_count,
                "uses_soda": uses_soda,
                "org": org,
            })

    colors = {
        "precision": "royalblue",
        "sparc": "orange",
        "rejoin": "green",
        "unknown": "gray",
    }
    error_diff_source_label = "Error Index" if USE_ERROR_INDEX_GRAPH else "Error Count"

    for soda_val, soda_label in [(True, "SODA"), (False, "non-SODA")]:
        for org in ["sparc"]: # ["precision"A, "sparc", "rejoin"]:
            filtered = [r for r in error_diff_records if r["uses_soda"] == soda_val and r["org"] == org]
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

            trace_count = len(filtered)

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=x_vals,
                y=y_vals,
                mode="markers",
                marker=dict(color=colors.get(org, "gray"), size=10, opacity=0.7),
                name=f"{soda_label} {org} ({trace_count})",
                text=hover_text,
                hoverinfo="text",
                legendrank=1,
            ))
            fig.add_trace(go.Scatter(
                x=[None],
                y=[None],
                mode="lines",
                line=dict(color="red", dash="dash"),
                name="Sparcur version delimiter",
                hoverinfo="skip",
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
                    fig.add_annotation(
                        x=update_date,
                        y=1,
                        yref="paper",
                        text=update["version"],
                        showarrow=False,
                        xanchor="left",
                        yanchor="top",
                        xshift=8,
                        yshift=-6,
                        textangle=90,
                        font=dict(color="red", size=10),
                    )

            fig.add_hline(y=0, line=dict(color="gray", dash="dash"), opacity=0.5)
            fig.update_yaxes(range=[-y_absmax - y_buffer, y_absmax + y_buffer], title=f"{error_diff_source_label} Difference (Publication - Request)")
            fig.update_xaxes(title="First Request Date")
            fig.update_layout(title=f"Standards Adherence: {error_diff_source_label} Difference (Publication - Request)<br>{soda_label} {org}")
            fig.show()

    # METRIC 1B: Error types at first request by year (stacked)
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
            req_types = last_error_types_at_or_before(int(req_date.timestamp()), error_graph)
            if req_types:
                for error_type, count in req_types.items():
                    first_request_error_type_records.append({
                        "year": req_date.year,
                        "type": error_type,
                        "count": count,
                    })

        pub_date = first_publication_date(dataset_id, event_sequences)
        if pub_date:
            pub_types = last_error_types_at_or_before(int(pub_date.timestamp()), error_graph)
            if pub_types:
                for error_type, count in pub_types.items():
                    publication_error_type_records.append({
                        "year": pub_date.year,
                        "type": error_type,
                        "count": count,
                    })

    plot_error_types_by_year(
        first_request_error_type_records,
        "Top 10 Error Types at First Request by Year",
    )
    plot_error_types_by_year(
        publication_error_type_records,
        "Top 10 Error Types at Publication by Year",
    )

    # METRIC 1C: Removed errors by type (first request -> publication), stacked by year
    removed_error_type_records = []
    for dataset_id, dataset_record in temporal_report.items():
        if is_excluded_dataset(dataset_id):
            continue

        error_graph = dataset_record.get("error_graph", {})

        req_date = first_request_date(dataset_id, event_sequences)
        pub_date = first_publication_date(dataset_id, event_sequences)
        if not req_date or not pub_date:
            continue

        req_types = last_error_types_at_or_before(int(req_date.timestamp()), error_graph)
        pub_types = last_error_types_at_or_before(int(pub_date.timestamp()), error_graph)
        if not req_types:
            continue
        if not pub_types:
            pub_types = {}

        for error_type in set(req_types) | set(pub_types):
            req_count = req_types.get(error_type, 0)
            pub_count = pub_types.get(error_type, 0)
            removed_count = req_count - pub_count
            if removed_count > 0:
                removed_error_type_records.append({
                    "year": req_date.year,
                    "type": error_type,
                    "count": removed_count,
                })

    plot_removed_errors_by_year(
        removed_error_type_records,
        "Removed Errors by Type by First Request Year",
    )

    # METRIC 2: Time from first request to publication (box plot per year)
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
            durations_by_year[req.year].append({
                "year": req.year,
                "duration": (pub - req).days,
                "id": dsid,
                "publication_date": pub,
            })
        if not pub:
            if req:
                unpublished_counts_by_year[req.year] += 1

    if durations_by_year:
        box_data = [row for year in sorted(durations_by_year) for row in durations_by_year[year]]
        df = pd.DataFrame(box_data)
        max_duration = int(df["duration"].max())
        year_tick_values = [365 * year for year in range(1, max_duration // 365 + 1)]
        year_tick_text = [f"{year} year" if year == 1 else f"{year} years" for year in range(1, max_duration // 365 + 1)]
        fig = px.box(
            df,
            x="year",
            y="duration",
            hover_data=["id", "publication_date"],
            points="all",
            title="Time from First Request to Publication by Year",
            labels={
                "id": "Dataset ID",
                "duration": "Days from Request to Publication",
                "year": "Request Year",
                "publication_date": "Publication Date",
            },
        )
        
        if unpublished_counts_by_year:
            unpublished_by_year_text = ", ".join([f"{year}: {count}" for year, count in sorted(unpublished_counts_by_year.items())])
            unpublished_text = f"Note: Datasets with request dates but without publication dates ({unpublished_by_year_text}) are not included in the plot."
            fig.update_layout(
                margin=dict(b=100),
                annotations=[
                    dict(
                        text=unpublished_text,
                        showarrow=False,
                        xref="paper", yref="paper",
                        x=0, y=-0.15, # Position relative to the plot's bounding box
                        xanchor="left", yanchor="auto",
                        font=dict(size=12, color="gray")
                    )
                ]
            )
        if year_tick_values:
            for tick_value, tick_label in zip(year_tick_values, year_tick_text):
                fig.add_hline(y=tick_value, line=dict(color="gray", dash="dot"), opacity=0.6)
                fig.add_annotation(
                    x=1.01,
                    xref="paper",
                    y=tick_value,
                    yref="y",
                    text=tick_label,
                    showarrow=False,
                    xanchor="left",
                    yanchor="middle",
                    font=dict(color="gray", size=11),
                )
            fig.update_yaxes(title="Days from Request to Publication")
        fig.show()

    # METRIC 3: Event types per year (stacked bar chart)
    event_type_records = []
    for dataset_id, dataset_sequences in status_delimited_sequences.items():
        if is_excluded_dataset(dataset_id):
            continue

        for sequence in dataset_sequences:
            for event in sequence:
                created_at = parse_iso8601(event.get("createdAt"))
                event_type = event.get("type")
                if not created_at or not event_type:
                    continue
                event_type_records.append({
                    "year": created_at.year,
                    "type": event_type,
                })

    if event_type_records:
        df = pd.DataFrame(event_type_records)
        df = df.groupby(["year", "type"]).size().reset_index(name="size")
        top_types = (
            df.groupby("type")["size"]
            .sum()
            .nlargest(10)
            .index
        )
        df = df[df["type"].isin(top_types)]
        fig = px.bar(
            df,
            x="year",
            y="size",
            color="type",
            title="Top 10 Event Types per Year",
            labels={
                "year": "Year",
                "size": "Event Count",
                "type": "Event Type",
            },
        )
        fig.update_layout(barmode="stack")
        fig.show()

    # METRIC 4: Total curation events per dataset by first request year
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

        curation_event_records.append({
            "dataset_id": dataset_id,
            "first_request_year": first_request.year,
            "publication_date": publication_date,
            "total_curation_events": total_curation_events,
        })

    if curation_event_records:
        fig = px.box(
            pd.DataFrame(curation_event_records),
            x="first_request_year",
            y="total_curation_events",
            hover_data=["dataset_id", "publication_date"],
            points="all",
            title="Total Curation Changes per Dataset by First Request Year",
            labels={
                "first_request_year": "First Request Year",
                "total_curation_events": "Total Curation Changes",
                "dataset_id": "Dataset ID",
                "publication_date": "Publication Date",
            },
        )
        fig.update_traces(
            hovertemplate="First Request Year=%{x}<br>Total Curation Sessions=%{y}<br>Dataset ID=%{customdata[0]}<br>Publication Date=%{customdata[1]}<extra></extra>",
        )
        fig.show()

    # METRIC 4B: Timespan of every curation session by first request year
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
                    "first_request_year": first_request.year,
                    "publication_date": publication_date,
                    "session_timespan_hours": session_timespan_hours,
                    "session_start": parse_iso8601(cluster.get("start")),
                    "session_end": parse_iso8601(cluster.get("end")),
                })

    if curation_session_timespan_records:
        fig = px.scatter(
            pd.DataFrame(curation_session_timespan_records),
            x="first_request_year",
            y="session_timespan_hours",
            hover_data=["dataset_id", "publication_date", "session_start", "session_end"],
            title="Timespan of Every Curation Session by First Request Year",
            labels={
                "first_request_year": "First Request Year",
                "session_timespan_hours": "Session Timespan (Hours)",
                "dataset_id": "Dataset ID",
                "publication_date": "Publication Date",
                "session_start": "Session Start",
                "session_end": "Session End",
            },
            opacity=0.75,
        )
        fig.update_traces(
            marker=dict(size=8),
            hovertemplate="First Request Year=%{x}<br>Session Timespan (Hours)=%{y:.2f}<br>Dataset ID=%{customdata[0]}<br>Publication Date=%{customdata[1]}<br>Session Start=%{customdata[2]}<br>Session End=%{customdata[3]}<extra></extra>",
        )
        fig.show()

    # METRIC 5: Datasets by first request date vs summed curations
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
            "first_request_year": first_request.year,
            "publication_date": publication_date,
            "total_clusters": cluster_total,
            "sequence_count": len(dataset_sequences),
        })

    if cluster_records:
        fig = go.Figure()
        first_request_dates = [record["first_request_date"] for record in cluster_records]
        total_clusters = [record["total_clusters"] for record in cluster_records]
        fig.add_trace(go.Scatter(
            x=first_request_dates,
            y=total_clusters,
            mode="markers",
            marker=dict(size=10, opacity=0.75, color="teal"),
            text=[
                f"Dataset ID: {record['dataset_id']}<br>First Request Date: {format_datetime(record['first_request_date'])}<br>Publication Date: {format_datetime(record.get('publication_date'))}<br>Total Curations: {record['total_clusters']}<br>Status Sequences: {record['sequence_count']}"
                for record in cluster_records
            ],
            hoverinfo="text",
            name="Datasets",
        ))

        if len(cluster_records) >= 2:
            x_numeric = np.array(mdates.date2num(first_request_dates), dtype=float)
            y_numeric = np.array(total_clusters, dtype=float)
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

        fig.update_xaxes(title="First Request Date")
        fig.update_yaxes(title="Curation Sessions")
        fig.update_layout(title="Datasets by First Request Date and Total Curations Sessions")
        fig.show()

        fig = px.box(
            pd.DataFrame(cluster_records),
            x="first_request_year",
            y="total_clusters",
            hover_data=["dataset_id", "publication_date"],
            points="all",
            title="Curation Sessions per Dataset by First Request Year",
            labels={
                "first_request_year": "First Request Year",
                "total_clusters": "Curation Sessions",
                "dataset_id": "Dataset ID",
                "publication_date": "Publication Date",
            },
        )
        fig.show()

    # METRIC 6: Datasets by first request date vs average cluster length
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
            "first_request_year": first_request.year,
            "publication_date": publication_date,
            "average_cluster_length": sum(cluster_lengths) / len(cluster_lengths),
            "cluster_count": len(cluster_lengths),
        })

    if cluster_length_records:
        fig = go.Figure()
        first_request_dates = [record["first_request_date"] for record in cluster_length_records]
        average_cluster_lengths = [record["average_cluster_length"] for record in cluster_length_records]
        fig.add_trace(go.Scatter(
            x=first_request_dates,
            y=average_cluster_lengths,
            mode="markers",
            marker=dict(size=10, opacity=0.75, color="darkorange"),
            text=[
                f"Dataset ID: {record['dataset_id']}<br>First Request Date: {format_datetime(record['first_request_date'])}<br>Publication Date: {format_datetime(record.get('publication_date'))}<br>Average Curation Density: {record['average_cluster_length']:.2f}<br>Clusters: {record['cluster_count']}"
                for record in cluster_length_records
            ],
            hoverinfo="text",
            name="Datasets",
        ))

        if len(cluster_length_records) >= 2:
            x_numeric = np.array(mdates.date2num(first_request_dates), dtype=float)
            y_numeric = np.array(average_cluster_lengths, dtype=float)
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

        fig.update_xaxes(title="First Request Date")
        fig.update_yaxes(title="Average Curation Density")
        fig.update_layout(title="Datasets by First Request Date and Average Curation Density")
        fig.show()

        fig = px.box(
            pd.DataFrame(cluster_length_records),
            x="first_request_year",
            y="average_cluster_length",
            hover_data=["dataset_id", "publication_date"],
            points="all",
            title="Average Curation Density per Dataset by First Request Year",
            labels={
                "first_request_year": "First Request Year",
                "average_cluster_length": "Average Curation Density",
                "dataset_id": "Dataset ID",
                "publication_date": "Publication Date",
            },
        )
        fig.show()