import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

def main():
    parser = argparse.ArgumentParser(
        description="Convert temporal_report.json to flat list format"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("temporal_report.json"),
        help="Input temporal report file (default: temporal_report.json)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("temporal_report_list.json"),
        help="Output list file (default: temporal_report_list.json)",
    )
    
    args = parser.parse_args()
    
    if not args.input.exists():
        print(f"Error: Input file not found: {args.input}")
        return 1
    
    with open(args.input, "r") as f:
        report = json.load(f)
    
    records = list(report.values())
    
    for record in records:
        error_rows = []
        for timestamp, errors in record.get("error_graph", {}).items():
            for error, count in errors.items():
                error_rows.append({
                    "timestamp": timestamp,
                    "error": error,
                    "count": count,
                })
        record["error_rows"] = error_rows
        del record["error_graph"]
    
    with open(args.output, "w") as f:
        json.dump(records, f, indent=2)
    
    return 0


if __name__ == "__main__":
    exit(main())
