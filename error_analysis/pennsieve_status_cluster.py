import json
from collections import defaultdict
from datetime import datetime, timezone

IN = "./pennsieve_status_delimited.json"
OUT = "./pennsieve_curation_clusters.json"
CLUSTER_GAP_MINUTES = 120


def parse_iso8601(value: str) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def cluster_sequence(events: list[dict]) -> list[dict]:
    if not events:
        return []

    ordered_events = sorted(
        events,
        key=lambda event: event["createdAt"],
    )

    clusters = []
    current_cluster = [ordered_events[0]]
    previous_time = parse_iso8601(ordered_events[0]["createdAt"])

    for event in ordered_events[1:]:
        current_time = parse_iso8601(event["createdAt"])
        if previous_time and current_time:
            gap_minutes = (current_time - previous_time).total_seconds() / 60
            if gap_minutes > CLUSTER_GAP_MINUTES:
                clusters.append(current_cluster)
                current_cluster = [event]
            else:
                current_cluster.append(event)
        else:
            current_cluster.append(event)

        if current_time:
            previous_time = current_time

    if current_cluster:
        clusters.append(current_cluster)

    return [
        {
            "start": cluster[0]["createdAt"],
            "end": cluster[-1]["createdAt"],
            "length": len(cluster),
            "events": cluster,
        }
        for cluster in clusters
    ]


with open(IN, "r", encoding="utf-8") as f:
    data = json.load(f)

clustered = defaultdict(list)

for dataset_id, sequences in data.items():
    for sequence in sequences:
        clusters = cluster_sequence(sequence)
        clustered[dataset_id].append(
            {
                "start_event_type": sequence[0]["event"] if sequence else None,
                "end_event_type": sequence[-1]["event"] if sequence else None,
                "sequence_start": sequence[0]["createdAt"] if sequence else None,
                "sequence_end": sequence[-1]["createdAt"] if sequence else None,
                "length": len(clusters),
                "clusters": clusters,
            }
        )

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(clustered, f, indent=2)

print(f"Wrote clustered status sequences for {len(clustered)} datasets to {OUT}")
