from abc import abstractmethod
from dataclasses import dataclass, field
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
MAX_CONCURRENCY = 512
SAMPLE = -1 # -1 to process all datasets


def parse_export_timestamp(timestamp: str) -> int:
        # Normalize millisecond separator and ensure explicit UTC when 'Z' present
        if not timestamp:
            raise ValueError("Missing timestamp")
        normalized = timestamp.replace(",", ".")
        if normalized.endswith("Z"):
            normalized = normalized.replace("Z", "+00:00")
        return int(datetime.fromisoformat(normalized).timestamp())

class Reporter:
    def filter(self, filename: str) -> bool:
        return True
    
    @abstractmethod
    def handle(self, file_data: dict):
        raise NotImplementedError
    
    @abstractmethod
    def finish(self):
        raise NotImplementedError

async def process_file(filename, reporters: list[Reporter]) -> tuple[str, list[Reporter]] | None:
    if filename.startswith("._") or not filename.endswith(".json"):
        return None
    
    target_reporters = [reporter for reporter in reporters if reporter.filter(filename)]
    
    if not target_reporters:
        return None

    file_path = os.path.join(IN, filename)
    async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
        raw = await f.read()
    data = await asyncio.to_thread(json.loads, raw)
    
    return (data, target_reporters)

async def main(reporters: list[Reporter]):
    if not reporters:
        print("No reporters to process")
        return
    
    files = [file for file in os.listdir(IN) if file.endswith(".json") and not file.startswith("._")]
    files = [file for file in files if any([reporter.filter(file) for reporter in reporters])]
    if SAMPLE > 0:
        print(f"Sampling {SAMPLE}/{len(files)} files")
        shuffle(files)
        files = files[:SAMPLE]
    pending = set()
    file_iter = iter(files)
    
    for _ in range(min(MAX_CONCURRENCY, len(files))):
        pending.add(asyncio.create_task(process_file(next(file_iter), reporters)))

    with tqdm(total=len(files), desc="Processing files") as pbar:
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                id = "<unknown>"
                try:
                    result = task.result()
                    if result is not None:
                        for reporter in result[1]:
                            reporter.handle(result[0])
                except Exception as e:
                    print(f"Error processing dataset {id}: {e}")
                    traceback.print_exc()
                pbar.update(1)

                try:
                    pending.add(asyncio.create_task(process_file(next(file_iter), reporters)))
                except StopIteration:
                    pass
        
    for reporter in reporters:
        reporter.finish()

class TemporalReporter(Reporter):
    @dataclass
    class DatasetReport:
        id: str
        status_counts: Counter = field(default_factory=Counter)
        first_requested_url: str | None = None
        first_requested_timestamp: int | None = None
        error_graph: dict[int, Counter] = field(default_factory=lambda: defaultdict(Counter))
        error_index_graph: dict[int, int] = field(default_factory=lambda: defaultdict(int))
        curation_index_graph: dict[int, int] = field(default_factory=lambda: defaultdict(int))
        submission_index_graph: dict[int, int] = field(default_factory=lambda: defaultdict(int))
        dropped_errors: int = 0
        is_precision: bool = False
        is_sparc: bool = False
        is_rejoin: bool = False
        uses_soda: bool = False
        
        def to_json_dict(self) -> dict:
            return {
                "id": self.id,
                "status_counts": dict(self.status_counts),
                "first_requested_url": self.first_requested_url,
                "first_requested_timestamp": self.first_requested_timestamp,
                "error_graph": {str(ts): dict(counter) for ts, counter in self.error_graph.items()},
                "error_index_graph": {str(ts): index for ts, index in self.error_index_graph.items()},
                "curation_index_graph": {str(ts): index for ts, index in self.curation_index_graph.items()},
                "submission_index_graph": {str(ts): index for ts, index in self.submission_index_graph.items()},
                "dropped_errors": self.dropped_errors,
                "is_precision": self.is_precision,
                "is_sparc": self.is_sparc,
                "is_rejoin": self.is_rejoin,
                "uses_soda": self.uses_soda,
            }
    
    def __init__(self, out_path: str, dropped_out_path: str):
        self.reports: dict[str, TemporalReporter.DatasetReport] = {}
        self.dropped_error_file = open(dropped_out_path, "w")
        self.soda_ids: set[str] = set()
        self.out_path = out_path
        self.dropped_out_path = dropped_out_path
        
        with open(SODA_CSV, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                dataset_id = row.get("N:dataset")
                if dataset_id:
                    self.soda_ids.add(dataset_id)
    
    def handle(self, file_data: dict):
        result = file_data
        id = result["id"]
        report = self.reports.get(id, None)
        if not report:
            report = TemporalReporter.DatasetReport(id=id)
            self.reports[id] = report

        inputs = result.get("inputs", {})
        status = inputs.get("remote_dataset_metadata", {}).get("publication", {}).get("status")
        report.status_counts[status] += 1
        
        # format: 2023-05-10T20:49:41,892885Z
        timestamp = result["prov"]["timestamp_export_start"]
        unix_timestamp = parse_export_timestamp(timestamp)
        
        report.error_index_graph[unix_timestamp] = file_data.get("status", {}).get("error_index", -1)
        report.curation_index_graph[unix_timestamp] = file_data.get("status", {}).get("curation_index", -1)
        report.submission_index_graph[unix_timestamp] = file_data.get("status", {}).get("submission_index", -1)
        
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
                    json_errors.add(err)
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
                if fmt and match:
                    d = fmt.description
                    try:           
                        d += " regex(" + match.group("regex") + ")"
                    except IndexError:
                        pass
                    try:
                        d += " required(" + match.group("required") + ")"
                    except IndexError:
                        pass
                    try:
                        d += " expected_type(" + match.group("type") + ")"
                    except IndexError:
                        pass
                    try:
                        d += " allowed(" + match.group("allowed") + ")"
                    except IndexError:
                        pass
                    report.error_graph[unix_timestamp][d] += 1
                else:
                    report.dropped_errors += 1
                    self.dropped_error_file.write(f"{id}\t No format matching '{err.replace("\n", "\\n")}'\n")
            except TimeoutError:
                report.dropped_errors += 1
                self.dropped_error_file.write(f"{id}\t Timed out matching '{err.replace("\n", "\\n")}'\n")
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

class UrlIdentifierReporter(Reporter):
    def __init__(self, out_path: str):
        self.latest_reports = {}
        self.target_ids = []
        self.out_path = out_path
        
        with open("./protocol_target_ids.csv", "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                self.target_ids.append(row[0].split(":")[2])
    
    def filter(self, filename: str) -> bool:
        return any([i in filename for i in self.target_ids])
    
    def handle(self, file_data: dict):
        id = file_data["id"]
        
        if id in self.latest_reports:
            existing_timestamp = self.latest_reports[id]["prov"]["timestamp_export_start"]
            new_timestamp = file_data["prov"]["timestamp_export_start"]
            if parse_export_timestamp(new_timestamp) > parse_export_timestamp(existing_timestamp):
                self.latest_reports[id] = file_data
        else:
            self.latest_reports[id] = file_data
    
    def finish(self):
        with open(self.out_path, "w") as f:
            f.write("Type, Protocol Name, Dataset ID, URL/Path\n")
            for id, report in self.latest_reports.items():
                for relation in report.get("meta", {}).get("related_identifiers", []):
                    identifier_type = relation.get("related_identifier_type")
                    if relation.get("relation_type") == "HasProtocol":
                        if identifier_type == "local-path":
                            name = ""
                            url = relation.get("related_identifier", "<missing local path>")
                            typ = "local-path"
                        elif identifier_type == "DOI":
                            ri = relation.get("related_identifier", {})
                            if isinstance(ri, str):
                                name = ""
                                url = ri
                            else:
                                name = ri.get("label", "<missing label>")
                                url = ri.get("uri_human", "<missing DOI>")
                            typ = "DOI"
                        else:
                            name = ""
                            url = ""
                            typ = "<unknown relation>"
                        f.write(f"{typ}, {name}, {id}, {url}\n")

class PrincipalInvestigatorReporter(Reporter):
    def __init__(self, out_path: str):
        self.checked = set()
        self.contributors = Counter()
        self.out_path = out_path
    
    def handle(self, file_data: dict):
        id = file_data["id"]
        
        if id in self.checked:
            return
        self.checked.add(id)
        
        contributors = file_data.get("contributors", file_data.get("meta", {}).get("contributors", []))
        
        if contributors:
            for contributor in contributors:
                if "PrincipalInvestigator" not in contributor.get("contributor_role", []):
                    continue
                self.contributors[contributor.get("contributor_name", "<unknown contributor>")] += 1
        else:
            self.contributors["<datasets missing contributors>"] += 1
    
    def finish(self):
        with open(self.out_path, "w") as f:
            json.dump(self.contributors, f, indent=4)

if __name__ == "__main__":
    reporters: list[Reporter] = [
        TemporalReporter("./temporal_report.json", "./dropped_errors.txt"),
        # PathErrorReporter("./path_errors.txt"),
        # UrlIdentifierReporter("dataset_relations.csv")
        # PrincipalInvestigatorReporter("principal_investigator_frequency.json"),
    ]
    asyncio.run(main(reporters))