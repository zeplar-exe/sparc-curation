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
        title: str = "<unknown>"
        dataset_type_graph: dict[int, str] = field(default_factory=lambda: defaultdict(str))
        template_version_graph: dict[int, str] = field(default_factory=lambda: defaultdict(str))
        award_number_graph: dict[int, str] = field(default_factory=lambda: defaultdict(str))
        status_counts: Counter = field(default_factory=Counter)
        export_urls: list[dict] = field(default_factory=list)
        error_graph: dict[int, Counter] = field(default_factory=lambda: defaultdict(Counter))
        error_index_graph: dict[int, int] = field(default_factory=lambda: defaultdict(int))
        curation_index_graph: dict[int, int] = field(default_factory=lambda: defaultdict(int))
        submission_index_graph: dict[int, int] = field(default_factory=lambda: defaultdict(int))
        dropped_errors: int = 0
        is_precision: bool = False
        is_sparc: bool = False
        is_rejoin: bool = False
        uses_soda: bool = False
        export_ts_to_updated_ts_graph: dict[int, dict] = field(default_factory=lambda: defaultdict(dict))
        def to_json_dict(self) -> dict:
            return {
                "id": self.id,
                "title": self.title,
                "status_counts": dict(self.status_counts),
                "dataset_type_graph": dict(sorted({str(ts): typ for ts, typ in self.dataset_type_graph.items()}.items())),
                "template_version_graph": dict(sorted({str(ts): version for ts, version in self.template_version_graph.items()}.items())),
                "award_number_graph": dict(sorted({str(ts): award_number for ts, award_number in self.award_number_graph.items()}.items())),
                "export_urls": sorted(self.export_urls, key=lambda x: x["unix_timestamp"]),
                "error_graph": dict(sorted({str(ts): dict(counter) for ts, counter in self.error_graph.items()}.items())),
                "error_index_graph": dict(sorted({str(ts): index for ts, index in self.error_index_graph.items()}.items())),
                "curation_index_graph": dict(sorted({str(ts): index for ts, index in self.curation_index_graph.items()}.items())),
                "submission_index_graph": dict(sorted({str(ts): index for ts, index in self.submission_index_graph.items()}.items())),
                "export_ts_to_updated_ts_graph": dict(sorted({str(ts): updated_ts for ts, updated_ts in self.export_ts_to_updated_ts_graph.items()}.items())),
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
    
    def _version(self, file_data: dict):
        version = file_data.get("meta", {}).get("template_schema_version")
        if isinstance(version, list) and version:
            return version[0]
        if version and isinstance(version, str):
            return version
        ddf = file_data.get("inputs", {}).get("dataset_description_file", {})
        if isinstance(ddf, list) and ddf:
            return ddf[0]
        if isinstance(ddf, dict):
            return ddf.get("template_schema_version")
        return None
    
    def handle(self, file_data: dict):
        result = file_data
        id = result["id"]
        report = self.reports.get(id, None)
        if not report:
            report = TemporalReporter.DatasetReport(id=id)
            self.reports[id] = report
        
        report.title = result.get("meta", {}).get("title", report.title)

        inputs = result.get("inputs", {})
        status = inputs.get("remote_dataset_metadata", {}).get("publication", {}).get("status")
        report.status_counts[status] += 1
        
        # format: 2023-05-10T20:49:41,892885Z
        timestamp = result["prov"]["timestamp_export_start"]
        unix_timestamp = parse_export_timestamp(timestamp)
        report.template_version_graph[unix_timestamp] = self._version(result) or "<unknown>"
        report.award_number_graph[unix_timestamp] = result.get("meta", {}).get("award_number") or "<unknown>"
        
        ts_updated_contents = result["meta"]["timestamp_updated_contents"]
        ts_updated = result["meta"]["timestamp_updated"]
        uc_unix = parse_export_timestamp(ts_updated_contents) if ts_updated_contents else None
        u_unix = parse_export_timestamp(ts_updated) if ts_updated else None
        report.export_ts_to_updated_ts_graph[unix_timestamp] = {
            "timestamp_updated_contents": uc_unix,
            "timestamp_updated": u_unix
        }

        report.error_index_graph[unix_timestamp] = file_data.get("status", {}).get("error_index", -1)
        report.curation_index_graph[unix_timestamp] = file_data.get("status", {}).get("curation_index", -1)
        report.submission_index_graph[unix_timestamp] = file_data.get("status", {}).get("submission_index", -1)
        
        dataset_type = file_data.get("meta", {}).get("dataset_type", "<unknown>")
        dataset_type = dataset_type or file_data.get("inputs", {}).get("dataset_description_file", {}).get("dataset_type", "<unknown>")
        report.dataset_type_graph[unix_timestamp] = dataset_type

        dataset_uuid = id.split(":")[2]
        safe_timestamp = timestamp.replace(":", "")
        url = f"https://cassava.ucsd.edu/sparc/datasets/{dataset_uuid}/{safe_timestamp}.tar.xz"
        
        report.export_urls.append({
            "url": url,
            "timestamp": timestamp,
            "unix_timestamp": unix_timestamp,
            "status": status,
        })

        if org := result.get("meta", {}).get("id_organization"):
            if org == PRECISION_ID:
                report.is_precision = True
            elif org == SPARC_ID:
                report.is_sparc = True
            elif org == REJOIN_ID:
                report.is_rejoin = True
        if id in self.soda_ids:
            report.uses_soda = True
            
        json_errors = {}
        
        def collect(errors):
            for err in errors:
                if isinstance(err, list):
                    collect(err)
                elif isinstance(err, str):
                    json_errors[f":{err}"] = (("", err))
                elif isinstance(err, dict):
                    if message := err.get("message"):
                        path = \
                            "#/" + \
                            "/".join(["-1" if isinstance(e, int) else e for e in err.get("path", [])])
                        if isinstance(message, list):
                            if len(message) > 1:
                                message = f"{message[0]} (and {len(message)-1} more messages)"
                            message = message[0] if message else "<empty message>"
                        key = f"{path}:{message}"
                        json_errors[key] = (path, message)
        
        # collect(result.get("errors", []))
        # collect(result.get("status", {}).get("submission_errors", []))
        # collect(result.get("status", {}).get("curation_errors", []))

        for path, item in result.get("status", {}).get("path_error_report", {}).items():
            messages = item.get("messages", [])
            collect([{"path": path.replace("#/", "").split("/"), "message": msg} for msg in messages])
        
        if inputs:
            for key, item in inputs.items():
                if key == "manifest_file":
                    for nested in item:
                        collect(nested.get("contents", {}).get("errors", []))
                else:
                    collect(item.get("errors", []))
        
        report.error_graph[unix_timestamp] = Counter()
        
        for key, (path, err) in json_errors.items():
            if isinstance(err, list):
                print(err)
            try:
                fmt, match = match_error(key)
                if fmt and match:
                    d = path + ":" + fmt.description
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

class SchemaVersionExampleReporter(Reporter):
    EXAMPLES_PER_VERSION = 3

    def __init__(self, out_path: str):
        self.examples: dict[str, list[dict]] = defaultdict(list)
        self.seen: dict[str, set[str]] = defaultdict(set)
        self.out_path = out_path

    def _version(self, file_data: dict):
        version = file_data.get("meta", {}).get("template_schema_version")
        if isinstance(version, list) and version:
            return version[0]
        if version:
            return version
        ddf = file_data.get("inputs", {}).get("dataset_description_file", {})
        if isinstance(ddf, list) and ddf:
            return ddf[0]
        if isinstance(ddf, dict):
            return ddf.get("template_schema_version")
        return None

    def handle(self, file_data: dict):
        version = self._version(file_data)
        if not version:
            return
        if len(self.examples[version]) >= self.EXAMPLES_PER_VERSION:
            return

        id = file_data["id"]
        if id in self.seen[version]:
            return
        self.seen[version].add(id)

        timestamp = file_data["prov"]["timestamp_export_start"]
        dataset_uuid = id.split(":")[2]
        safe_timestamp = timestamp.replace(":", "")
        url = f"https://cassava.ucsd.edu/sparc/datasets/{dataset_uuid}/{safe_timestamp}.tar.xz"

        self.examples[version].append({
            "id": id,
            "timestamp_export_start": timestamp,
            "url": url,
        })

    def finish(self):
        with open(self.out_path, "w") as f:
            json.dump(self.examples, f, indent=4)
        total = sum(len(v) for v in self.examples.values())
        
        print(f"Collected {total} examples across {len(self.examples)} schema versions")

if __name__ == "__main__":
    reporters: list[Reporter] = [
        TemporalReporter("./temporal_report.json", "./dropped_errors.txt"),
        # SchemaVersionExampleReporter("./schema_version_examples.json"),
        PathErrorReporter("./path_errors.txt"),
        # UrlIdentifierReporter("dataset_relations.csv")
        # PrincipalInvestigatorReporter("principal_investigator_frequency.json"),
    ]
    asyncio.run(main(reporters))


# A7 spreadsheet as ground truth to find sub-pub cycles that come before the "first cycle" we see in cassava/pennsieve
    # need to integrate fixed publication dates from A7 as well
# use dataset_type from SPARC_pipeline_published_reconciliation
    # also DOI v1
# use publication year from SPARC_pipeline_published_reconciliation as well for first cycle check
    # also, from this file, dataset_type=computational + scaffold=yes is to exclude for sure
# ensure whether cases where EITHER req or pub date is before april 2022, the dataset is excluded entirely (even if pub only)
# why do the two error at submission graphs disagree? (yearly/monthly/quarterly vs yearly)

