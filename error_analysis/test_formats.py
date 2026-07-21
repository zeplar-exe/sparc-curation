import argparse
import ast
import importlib
from random import shuffle
import sys
from collections import Counter
from dataclasses import dataclass 
from typing import Any, Dict, Iterable
import json
from error_info_to_json import main as regenerate_errors
import regex

IN = ["./all-the-all-the-errors", "./cassava_errors", "./dropped_errors.txt", "./path_errors.txt"][3]
INFO_JSON = "./error-info.json"
OUT_CSV = "./format-matches.csv"
OUT_RE = "./format-regexes.txt"
SAMPLE_SIZE = -1 # -1 to sample whole population

def _join_fstring(expr: str):
    node = ast.parse(expr, mode="eval").body
    if isinstance(node, ast.JoinedStr):
        return node

    raise ValueError(f"{expr!r} is not an f-string expression")

def _generate_group_name(value_node: ast.expr, fallback_index: int):
    if isinstance(value_node, ast.Name):
        base = value_node.id
    else:
        base = f"expr{fallback_index}"

    safe = regex.sub(r"\W", "_", base)
    if not safe or safe[0].isdigit():
        safe = f"_{safe}"
    return safe

def _fstring_to_regex(expr: str, include_source: bool = False) -> Any:
    value_pattern = r".*?"
    value_pattern_last = r".*"
    joined = _join_fstring(expr)
    parts = []
    
    if include_source:
        parts.append(r"(?P<source>[^:]+):\s*")

    seen_groups: Dict[str, str] = {}
    fallback_index = 1
    count = len(joined.values)

    for i, value in enumerate(joined.values):
        if isinstance(value, ast.Constant):
            text = value.value
            
            if not isinstance(text, str):
                raise ValueError(f"Unexpected constant in f-string: {value!r}")
            
            escaped = regex.escape(text)
            escaped = escaped.replace("\\\n", r"(?:(\r?\n|\\n))")
            parts.append(escaped)
        elif isinstance(value, ast.FormattedValue):
            key = ast.dump(value.value, annotate_fields=False, include_attributes=False)
            name = _generate_group_name(value.value, fallback_index)
            fallback_index += 1

            if key in seen_groups:
                parts.append(fr"(?P={seen_groups[key]})")
            else:
                seen_groups[key] = name
                parts.append(fr"(?P<{name}>{value_pattern if i < count - 1 else value_pattern_last})")
        else:
            raise ValueError(f"Unsupported f-string segment: {type(value).__name__}")

    return regex.compile("".join(parts), regex.DOTALL)

class Format():
    def __init__(self, id: int, source: str, regex: regex.Pattern, description: str):
        self.id = id
        self.source = source
        self.regex = regex
        self.description = description

formats: list[Format] = []

def _load_formats(info_json: str, include_source: bool = False, do_log: bool = False):
    if len(formats) > 0:
        return
    
    with open(info_json) as f:
        for i, item in enumerate(json.load(f)):
            try:
                f = item["format"]
                pattern = _fstring_to_regex(f, include_source=include_source)
                
                if do_log:
                    print(f"Loaded format {i}: {item['description']} -> {pattern.pattern}")
                
                formats.append(Format(item["id"], item["source"], pattern, item["description"]))
            except Exception as e:
                if do_log:
                    print(f"Error processing format {i}: {e}")

def match_error(error: str, include_source: bool = False, do_log: bool = False) -> tuple[Format | None, regex.Match | None]:
    _load_formats(INFO_JSON, include_source=include_source, do_log=do_log)

    for fmt in formats:
        search = fmt.regex.search(error, timeout=1)
        if search:
            return fmt, search
    
    return None, None

def enumerate_errors(errors: list[str], sample=-1, do_log=False, include_source: bool = False) -> Iterable[tuple[int, str, Format | None, regex.Match | None]]:
    if sample > 0:
        shuffle(errors)
    
    lines = errors[:sample] if sample > 0 else errors
    
    for l, line in enumerate(lines):
        try:
            m, s = match_error(line, include_source=include_source, do_log=do_log)
        except TimeoutError as e:
            if do_log:
                print(f"TimeoutError on line {l+1}: {line}")
            m = None
            s = None
        if m:
            yield l+1, line, m, s
        else:
            if do_log:
                print(f"No match on line {l+1}: {line}")
            yield l+1, line, None, None

def test_errors(errors: list[str], sample=-1, do_log=False, info_json=INFO_JSON, include_source: bool = False):
    print(f"Found {len(formats)} f-string formats in {info_json}")
    
    counter = Counter()
    
    if sample > 0:
        if do_log:
            print(f"Sampling {sample} lines from {len(errors)} total lines")
    for l, line, fmt, search in enumerate_errors(errors, sample=sample, do_log=do_log, include_source=include_source):
        if fmt:
            if do_log:    
                print(f"Matched [id={fmt.id}] on line {l+1}: {fmt.regex.pattern}")
            counter[fmt.description] += 1
        else:
            if do_log:
                print(f"No match on line {l+1}: {line}")
    
    return counter


def parse_args():
    parser = argparse.ArgumentParser(description="Match error lines against f-string-derived regex formats.")
    parser.add_argument("--input", default=IN, help="Path to input error lines file.")
    parser.add_argument("--info-json", default=INFO_JSON, help="Path to error format metadata JSON.")
    parser.add_argument("--out-csv", default=OUT_CSV, help="Path to output TSV summary.")
    parser.add_argument("--out-regex", default=OUT_RE, help="Path to output regex patterns file.")
    parser.add_argument("--sample-size", type=int, default=SAMPLE_SIZE, help="Number of lines to sample; -1 means all lines.")
    parser.add_argument("--no-regenerate", action="store_true", help="Skip regenerating error-info.json before matching.")
    parser.add_argument("--no-log", default=False, action="store_true", help="Disable per-line logging.")
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()

    # Wack fix for console output
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(line_buffering=True, write_through=True)

    if not args.no_regenerate:
        regenerate_errors()

    _load_formats(args.info_json, do_log=not args.no_log)

    with open(args.input) as f:
        lines = [l.strip() for l in f.readlines()]
        counter = test_errors(lines, sample=args.sample_size, do_log=not args.no_log, info_json=args.info_json)

    with open(args.out_csv, "w") as f:
        f.write("Description\tCount\n")
        for description, count in counter.items():
            f.write(f"{description}\t{count}\n")

    with open(args.out_regex, "w") as f:
        for fmt in formats:
            f.write(f"{fmt.description}\t{fmt.regex.pattern}\n")