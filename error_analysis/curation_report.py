# This file was created in large part with GitHub Copilot

import csv
import datetime
import json
from collections import defaultdict
from datetime import timezone

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
    if not isinstance(events, list) or not events:
        return None
    return parse_iso8601(events[0].get("accept_created"))


def cluster_total(dataset_sequences):
    total = 0
    for sequence in dataset_sequences:
        clusters_value = sequence.get("clusters", 0)
        if isinstance(clusters_value, int):
            total += clusters_value
        elif isinstance(clusters_value, list):
            total += len(clusters_value)
    return total


def cluster_lengths(dataset_sequences):
    lengths = []
    for sequence in dataset_sequences:
        clusters_value = sequence.get("clusters", [])
        if not isinstance(clusters_value, list):
            continue
        for cluster in clusters_value:
            cluster_length = cluster.get("length")
            if isinstance(cluster_length, int):
                lengths.append(cluster_length)
    return lengths


def last_error_count_at_or_before(target_ts, error_graph):
    """Return the sum of errors at the last timestamp <= target_ts, or None."""
    last_count = None
    for ts_str, errors in sorted(error_graph.items(), key=lambda item: int(item[0])):
        ts_int = int(ts_str)
        if ts_int <= target_ts:
            last_count = sum(errors.values())
        else:
            break
    return last_count


with open(TEMPORAL_REPORT) as f, open(EVENT_SEQUENCES) as g, open(STATUS_DELIMITED_SEQUENCES) as h, open(SPARCUR_UPDATES) as i, open(CURATION_CLUSTERS) as j:
    temporal_report = json.load(f)
    event_sequences = json.load(g)
    status_delimited_sequences = json.load(h)
    sparcur_updates = list(csv.DictReader(i))
    curation_clusters = json.load(j)

    # METRIC 1: Standards adherence: error diff over time
    error_diff_records = []

    for dataset_id, dataset_record in temporal_report.items():
        events = event_sequences.get(dataset_id)
        if not isinstance(events, list) or not events:
            continue

        error_graph = dataset_record.get("error_graph", {})
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

            req_error_count = last_error_count_at_or_before(req_ts, error_graph)
            pub_error_count = last_error_count_at_or_before(pub_ts, error_graph)

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

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=x_vals,
                y=y_vals,
                mode="markers",
                marker=dict(color=colors.get(org, "gray"), size=10, opacity=0.7),
                name=f"{soda_label} {org}",
                text=hover_text,
                hoverinfo="text",
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
            fig.update_yaxes(range=[-y_absmax - y_buffer, y_absmax + y_buffer], title="Error Count Difference (Publication - Request)")
            fig.update_xaxes(title="First Request Date")
            fig.update_layout(title=f"Standards Adherence: Error Difference (Publication - Request)<br>{soda_label} {org}")
            fig.show()

    # METRIC 2: Time from first request to publication (box plot per year)
    durations_by_year = defaultdict(list)
    for dsid, events in event_sequences.items():
        if not isinstance(events, list) or not events:
            continue

        ev = events[0]
        req = parse_iso8601(ev.get("request_created"))
        pub = parse_iso8601(ev.get("accept_created"))
        if req and pub and pub > req:
            durations_by_year[req.year].append({
                "year": req.year,
                "duration": (pub - req).days,
                "id": dsid,
                "publication_date": pub,
            })

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
    for dataset_sequences in status_delimited_sequences.values():
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
    for dataset_id, dataset_sequences in status_delimited_sequences.items():
        report = temporal_report.get(dataset_id)
        if not report:
            continue

        first_requested_timestamp = report.get("first_requested_timestamp")
        if not first_requested_timestamp:
            continue

        first_request_date = datetime.datetime.fromtimestamp(first_requested_timestamp, tz=timezone.utc)
        publication_date = first_publication_date(dataset_id, event_sequences)
        total_curation_events = sum(len(sequence) for sequence in dataset_sequences)

        curation_event_records.append({
            "dataset_id": dataset_id,
            "first_request_year": first_request_date.year,
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
            title="Total Curation Events per Dataset by First Request Year",
            labels={
                "first_request_year": "First Request Year",
                "total_curation_events": "Total Curation Events",
                "dataset_id": "Dataset ID",
                "publication_date": "Publication Date",
            },
        )
        fig.show()

    # METRIC 5: Datasets by first request date vs summed curations
    cluster_records = []
    for dataset_id, dataset_sequences in curation_clusters.items():
        report = temporal_report.get(dataset_id)
        if not report:
            continue

        first_requested_timestamp = report.get("first_requested_timestamp")
        if not first_requested_timestamp:
            continue

        first_request_date = datetime.datetime.fromtimestamp(first_requested_timestamp, tz=timezone.utc)
        publication_date = first_publication_date(dataset_id, event_sequences)

        cluster_records.append({
            "dataset_id": dataset_id,
            "first_request_date": first_request_date,
            "first_request_year": first_request_date.year,
            "publication_date": publication_date,
            "total_clusters": cluster_total(dataset_sequences),
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
        report = temporal_report.get(dataset_id)
        if not report:
            continue

        first_requested_timestamp = report.get("first_requested_timestamp")
        if not first_requested_timestamp:
            continue

        first_request_date = datetime.datetime.fromtimestamp(first_requested_timestamp, tz=timezone.utc)
        publication_date = first_publication_date(dataset_id, event_sequences)
        lengths = cluster_lengths(dataset_sequences)
        
        if not lengths:
            continue

        cluster_length_records.append({
            "dataset_id": dataset_id,
            "first_request_date": first_request_date,
            "first_request_year": first_request_date.year,
            "publication_date": publication_date,
            "average_cluster_length": sum(lengths) / len(lengths),
            "cluster_count": len(lengths),
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