from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime
import json
import csv
from random import shuffle
import traceback
from test_formats import match_error
from tqdm import tqdm
import os
import asyncio
from collections import Counter, defaultdict
import aiofiles

PRECISION_ID = "organization:98d6e84c-9a27-48f8-974f-93c0cca15aae"
SPARC_ID = "organization:618e8dd9-f8d2-4dc4-9abb-c6aaab2e78a0"
REJOIN_ID = "organization:f08e188e-2316-4668-ae2c-8a20dc88502f"
SODA_CSV = "./identifiers_for_soda_processed_datasets_marked_as_published.csv"

IN = "/Volumes/Extreme SSD/sparc-cassava-raw/"
FULL_REPORT_OUT = "./temporal_report.json"
DROPPED_ERRORS_OUT = "./dropped_errors.txt"
PATH_ERROR_OUT = "./path_errors.txt"
MAX_CONCURRENCY = 512
SAMPLE = -1 # -1 to process all datasets


class Reporter:
    @abstractmethod
    def handle(self, file_data: dict):
        raise NotImplementedError
    
    @abstractmethod
    def finish(self):
        raise NotImplementedError

async def process_file(filename):
    if filename.startswith("._") or not filename.endswith(".json"):
        return None

    file_path = os.path.join(IN, filename)
    async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
        raw = await f.read()
    data = await asyncio.to_thread(json.loads, raw)
    
    return data

async def main(reporters: list[Reporter]):
    files = [file for file in os.listdir(IN) if file.endswith(".json") and not file.startswith("._")]
    if SAMPLE > 0:
        print(f"Sampling {SAMPLE}/{len(files)} files")
        shuffle(files)
        files = files[:SAMPLE]
    pending = set()
    file_iter = iter(files)
    
    for _ in range(min(MAX_CONCURRENCY, len(files))):
        pending.add(asyncio.create_task(process_file(next(file_iter))))

    with tqdm(total=len(files), desc="Processing files") as pbar:
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                id = "<unknown>"
                try:
                    for reporter in reporters:
                        reporter.handle(task.result())
                except Exception as e:
                    print(f"Error processing dataset {id}: {e}")
                    traceback.print_exc()
                pbar.update(1)

                try:
                    pending.add(asyncio.create_task(process_file(next(file_iter))))
                except StopIteration:
                    pass
        
    for reporter in reporters:
        reporter.finish()

class TemporalReporter(Reporter):
    @dataclass
    class DatasetReport:
        id: str
        status_counts: Counter
        first_requested_url: str | None
        first_requested_timestamp: int | None
        error_graph: dict[int, Counter]
        dropped_errors: int
        is_precision: bool
        is_sparc: bool
        is_rejoin: bool
        uses_soda: bool
        
        def to_json_dict(self) -> dict:
            return {
                "id": self.id,
                "status_counts": dict(self.status_counts),
                "first_requested_url": self.first_requested_url,
                "first_requested_timestamp": self.first_requested_timestamp,
                "error_graph": {str(ts): dict(counter) for ts, counter in self.error_graph.items()},
                "dropped_errors": self.dropped_errors,
                "is_precision": self.is_precision,
                "is_sparc": self.is_sparc,
                "is_rejoin": self.is_rejoin,
                "uses_soda": self.uses_soda,
            }
    
    def _load_soda_ids(self, csv_path: str) -> set[str]:
        soda_ids: set[str] = set()
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                dataset_id = row.get("N:dataset")
                if dataset_id:
                    soda_ids.add(dataset_id)
        return soda_ids

    def _parse_export_timestamp(self, timestamp: str) -> int:
        normalized = timestamp.rstrip("Z").replace(",", ".")
        return int(datetime.fromisoformat(normalized).timestamp())
    
    def __init__(self, out_path: str, dropped_out_path: str):
        self.reports: dict[str, TemporalReporter.DatasetReport] = {}
        self.soda_ids = self._load_soda_ids(SODA_CSV)
        self.dropped_error_file = open(dropped_out_path, "w")
        self.out_path = out_path
        self.dropped_out_path = dropped_out_path
    
    def handle(self, file_data: dict):
        result = file_data
        id = result["id"]
        report = self.reports.get(id, None)
        if not report:
            report = TemporalReporter.DatasetReport(
                id=id,
                status_counts=Counter(),
                first_requested_url=None,
                first_requested_timestamp=None,
                error_graph=defaultdict(Counter),
                dropped_errors=0,
                is_precision=False,
                is_sparc=False,
                is_rejoin=False,
                uses_soda=False
            )
            self.reports[id] = report

        inputs = result.get("inputs", {})
        status = inputs.get("remote_dataset_metadata", {}).get("publication", {}).get("status")
        report.status_counts[status] += 1
        
        # format: 2023-05-10T20:49:41,892885Z
        timestamp = result["prov"]["timestamp_export_start"]
        unix_timestamp = self._parse_export_timestamp(timestamp)
        
        if status == "requested":
            dataset_uuid = id.split(":")[2]
            safe_timestamp = timestamp.replace(":", "")
            url = f"https://cassava.ucsd.edu/sparc/datasets/{dataset_uuid}/{safe_timestamp}.tar.xz"
            if report.first_requested_timestamp is None or unix_timestamp < report.first_requested_timestamp:
                report.first_requested_timestamp = unix_timestamp
                report.first_requested_url = url

        if org := result.get("meta", {}).get("id_organization"):
            if org == PRECISION_ID:
                report.is_precision = True
            elif org == SPARC_ID:
                report.is_sparc = True
            elif org == REJOIN_ID:
                report.is_rejoin = True
        if id in self.soda_ids:
            report.uses_soda = True
            
        json_errors = set()
        
        def collect(errors):
            for err in errors:
                if isinstance(err, list):
                    collect(err)
                elif isinstance(err, str):
                    err = {"message": err}
                elif isinstance(err, dict):
                    if message := err.get("message"):
                        json_errors.add(message)
        
        collect(result.get("errors", []))
        collect(result.get("status", {}).get("submission_errors", []))
        collect(result.get("status", {}).get("curation_errors", []))
        for item in result.get("status", {}).get("path_error_report", {}).values():
            collect(item.get("messages", []))
        if inputs:
            for key, item in inputs.items():
                if key == "manifest_file":
                    for nested in item:
                        collect(nested.get("contents", {}).get("errors", []))
                else:
                    collect(item.get("errors", []))
        
        for err in json_errors:
            try:
                fmt, match = match_error(err)
                if fmt:
                    report.error_graph[unix_timestamp][fmt.description] += 1
                else:
                    report.dropped_errors += 1
                    self.dropped_error_file.write(f"{id}\t No format matching '{err.replace("\n", " ")}'\n")
            except TimeoutError:
                report.dropped_errors += 1
                self.dropped_error_file.write(f"{id}\t Timed out matching '{err.replace("\n", " ")}'\n")
        self.dropped_error_file.flush()
    
    def finish(self):
        with open(self.out_path, "w") as f:
            json.dump({id: report.to_json_dict() for id, report in self.reports.items()}, f, indent=4)
        
        print(f"Dropped {sum(report.dropped_errors for report in self.reports.values())} errors that did not match any format")
        
        self.dropped_error_file.close()

class PathErrorReporter(Reporter):
    def __init__(self, out_path: str):
        self.errors = []
        self.dropped_files = 0
        self.out_path = out_path
    
    def handle(self, file_data: dict):
        errors = file_data.get("status", {}).get("curation_errors", {})
        
        if not errors:
            self.dropped_files += 1
            return
        
        messages = []
        for error in errors:
            path = \
                "\"#/" + \
                "/".join(["-1" if isinstance(e, int) else e for e in error.get("path", [])]) + \
                ": " + \
                error.get("message", "<empty message>") + \
                "\""
            messages.append(path)
        self.errors.extend(messages)
    
    def finish(self):
        with open(self.out_path, "w") as f:
            for error in self.errors:
                f.write(error + "\n")
        
        print(f"Dropped {self.dropped_files} files with no curation errors")

if __name__ == "__main__":
    reporters: list[Reporter] = [
        TemporalReporter(FULL_REPORT_OUT, DROPPED_ERRORS_OUT),
        PathErrorReporter(PATH_ERROR_OUT),
    ]
    asyncio.run(main(reporters))