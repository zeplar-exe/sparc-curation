import csv
import os
import shutil

from generate_error_matrix_table import FIXED_FIELDS

MATRIX = "./SPARC_error_results_matrix_table.generated.csv"
OUT_DIR = "./error_xor_per_dataset"

SUMMARY_LABELS = {"how_many_datasets_have_this_error", "error_path", "error_id", "error_title"}


def main():
    with open(MATRIX, newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    n_fixed = len(FIXED_FIELDS)
    message_cols = header[n_fixed:]

    by_dataset = {}
    for row in rows:
        if row[0] in SUMMARY_LABELS:
            continue
        record = dict(zip(header, row))
        by_dataset.setdefault(record["dataset_id"], {})[record["invent"]] = record

    if os.path.exists(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    for template_layer in ("template_change", "no_template_change"):
        for folder in ("pub_greater_sub", "sub_greater_pub"):
            os.makedirs(os.path.join(OUT_DIR, template_layer, folder))

    def present(record, col):
        return record.get(col, "") == "1"

    def included(record):
        try:
            return int(record.get("included_errors_present") or 0)
        except ValueError:
            return 0

    written = 0
    for dataset_id, phases in by_dataset.items():
        sub = phases.get("submission")
        pub = phases.get("publication")

        if not sub or not pub:
            continue

        # XOR: errors present in exactly one phase, submission-only first then publication-only
        sub_only = [col for col in message_cols if present(sub, col) and not present(pub, col)]
        pub_only = [col for col in message_cols if present(pub, col) and not present(sub, col)]

        folder = "pub_greater_sub" if included(pub) > included(sub) else "sub_greater_pub"
        template_layer = "template_change" if sub.get("template_version", "") != pub.get("template_version", "") else "no_template_change"

        safe_id = dataset_id.replace(":", "_")
        with open(os.path.join(OUT_DIR, template_layer, folder, f"{safe_id}.csv"), "w", newline="") as f:
            writer = csv.writer(f)
            for field in FIXED_FIELDS:
                writer.writerow([field, sub.get(field, ""), pub.get(field, "")])
            for col in sub_only:
                writer.writerow([col, 1, 0])
            for col in pub_only:
                writer.writerow([col, 0, 1])
        written += 1

    print(f"Wrote {written} to {OUT_DIR}/")


if __name__ == "__main__":
    main()
