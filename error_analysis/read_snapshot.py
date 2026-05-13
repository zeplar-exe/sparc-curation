import json
import ijson
from collections import Counter
from dataclasses import dataclass

IN = "./cassava-curation-export.json"

@dataclass
class Dataset:
    id: str
    publication_stati: Counter
    
    def ever_completed(self):
        return self.publication_stati.get("completed", 0) > 0

with open(IN, "rb") as f:
    ds = {}
    for dataset in ijson.items(f, "datasets.item"):
        i = dataset["id"]
        if i not in ds:
            ds[i] = Dataset(id=i, publication_stati=Counter())
        
        ds[i].publication_stati[dataset["rmeta"].get("publication_status", "unknown")] += 1
    print(len(ds))
    print(len([x for x in ds.values() if x.ever_completed()]))
    print(sum([x.publication_stati.total() for x in ds.values() if x.ever_completed()]))
    c = Counter()
    for x in ds.values():
        c += x.publication_stati
    for x in ds.values():
        if x.publication_stati.get("unknown", 0) > 0:
            print(x.id)
    print(c)