import csv
import json
from collections import Counter

IN = "./temporal_report.json"
OUT = "./error_subtypes.csv"


def main():
    with open(IN, "r", encoding="utf-8") as f:
        data = json.load(f)

    dataset_counts = Counter()

    for dataset_record in data.values():
        error_graph = dataset_record.get("error_graph", {})
        if not error_graph:
            continue
        for error_set in error_graph.values():
            for subtype in error_set:
                dataset_counts[subtype] += 1

    with open(OUT, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["subtype"])
        for subtype, count in dataset_counts.most_common():
            writer.writerow([subtype])


if __name__ == "__main__":
    main()
