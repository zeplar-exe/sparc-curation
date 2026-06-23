import argparse
from test_formats import enumerate_errors
from collections import Counter, defaultdict
from tqdm import tqdm

IN = "path_errors.txt" # "all-the-all-the-errors"
OUT = "all_jsonschema_errors.txt"


def get_path_errors(file, sample_size=-1):
    c = defaultdict(Counter)
    with open(file) as f:
        lines = f.readlines()
        
        total = min(sample_size, len(lines)) if sample_size > 0 else len(lines)
        for l, line, fmt, match in tqdm(enumerate_errors(lines, sample=sample_size, include_source=True), total=total):
            if not fmt or not match:
                c["<unmatched>"][line.strip()] += 1
                continue
            d = fmt.description
            try:           
                d += " regex(" + match.group("regex") + ")"
            except IndexError:
                pass
            try:
                d += " expected_type(" + match.group("type") + ")"
            except IndexError:
                pass
            try:
                d += " required(" + match.group("required") + ")"
            except IndexError:
                pass
            try:
                d += " allowed(" + match.group("allowed") + ")"
            except IndexError:
                pass
            c[d][match.group("source")] += 1
        
    return c


def parse_args():
    parser = argparse.ArgumentParser(description="Extract and group errors by path..")
    parser.add_argument("--input", default=IN, help="Path to input error log file.")
    parser.add_argument("--output", default=OUT, help="Path to write grouped errors.")
    parser.add_argument("--sample-size", type=int, default=-1, help="Number of lines to sample; -1 means all lines.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    c = get_path_errors(args.input, sample_size=args.sample_size)
    with open(args.output, "w") as f:
        for desc, counter in c.items():
            f.write(f"{desc}\n")
            for error, count in counter.items():
                f.write(f"\t{error}\t{count}\n")