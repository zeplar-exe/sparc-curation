import json

IN = "./error-info.txt"
OUT = "./error-info.json"

def main():
    errors = []
    with open(IN) as f:
        lines = f.readlines()
        i = 0
        for raw in lines[::3]:
            source = raw.strip()
            description = lines[i+1].strip()
            fmt = lines[i+2].strip()
            errors.append({
                "source": source,
                "description": description,
                "format": fmt,
            })
            i += 3

    with open(OUT, "w") as f:
        json.dump(errors, f, indent=4)


if __name__ == "__main__":
    main()