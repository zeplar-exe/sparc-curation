import json
import csv

IN = "./SPARC_Pipeline_Error_Dictionary_consolidated.csv"
OUT = "./error-info.json"

def main():
    errors = []
    with open(IN) as f:
        r = csv.DictReader(f)
        for row in r:
            format = row["Match Key (verbatim)"].strip()
            if not format:
                continue
            
            if "|" in format:
                for fmt in format.split("|"):
                    errors.append({
                        "id": row["Error ID"].strip(),
                        "source": row["Source File"].strip(),
                        "description": row["Error Title"].strip(),
                        "format": f"f'{fmt.replace("'", "\\'").strip()}'",
                    })
            else:
                errors.append({
                    "id": row["Error ID"].strip(),
                    "source": row["Source File"].strip(),
                    "description": row["Error Title"].strip(),
                    "format": f"f'{row['Match Key (verbatim)'].replace("'", "\\'").strip()}'",
                })

    with open(OUT, "w") as f:
        json.dump(errors, f, indent=4)

if __name__ == "__main__":
    main()
