import json
import os
import ssl
import io
import tarfile
import aiohttp
import asyncio
import importlib
from tqdm import tqdm
from test_formats import test_errors
from collections import Counter, defaultdict
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

regex = importlib.import_module("regex")

IN = ["./cassava_crawl_041525.json", "./missings.json"][1]
OUT_DATA = "./cassava_data.json"
OUT_ERR = "./cassava_run_errors.txt"
FOLDER = "/Volumes/Extreme SSD/sparc-cassava-raw/"

file_regex = regex.compile(r"^https://cassava.ucsd.edu/sparc/datasets/([^/]+)/([^/]+)\.tar\.xz$")

async def process_dataset_file(sem, session, url, mat):
    async with sem:
        try:
            async with session.get(url, ssl=ssl.SSLContext()) as response:
                data = await response.read()
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as tar:
                    file = tar.extractfile("./curation-export.json")
                    if file is None:
                        raise FileNotFoundError("./curation-export.json missing from tarball")
                    export = json.load(file)

                    return url, mat, export, None
        except Exception as e:
            return url, mat, None, e

async def main():
    missing = 0
    d = set()
    missings = []
    with open(IN) as f:
        data = json.load(f)
        for line in data:
            url = line.strip()
            mat = file_regex.match(url)
            if mat:
                d.add(url.replace("/", "+") + ".json")
    if True:
        s = os.listdir(FOLDER)
        for url in tqdm(d):        
            if not url in s:
                missing += 1
                missings.append(url)
        print(f"Missing {missing} files")
        with open("missings.json", "w") as f:
            json.dump([m.replace("+", "/").rstrip(".json") for m in missings], f, indent=4)
        return
    with open(OUT_ERR, "w") as fe:
        with open(OUT_DATA, "w") as fc:
            with open(IN) as f:
                data = json.load(f)
                count = len(data)
                batch_size = count
                sem = asyncio.Semaphore(50)
                
                i = 0
                batch = []
                
                pbar = tqdm(total=count-i, desc="Processing datasets")
                while i < count:
                    for j in range(i, min(i + batch_size, count)):
                        url = data[j].strip()
                        mat = file_regex.match(url)
                        if mat:
                            batch.append((url, mat))
                    async with aiohttp.ClientSession(timeout=None) as session:
                        tasks = [
                            asyncio.create_task(process_dataset_file(sem, session, url, mat))
                            for (url, mat) in batch
                        ]

                        for future in asyncio.as_completed(tasks):
                            url, mat, result, error = await future
                            try:
                                if error is not None:
                                    raise error
                                dataset = mat.group(1)
                                with open(f"{FOLDER}{url.replace("/", "+")}.json", "w") as e:
                                    json.dump(result, e, indent=4)
                                fe.write(f"Processed {url}\n")
                                fe.flush()
                                # datasets[dataset].append(result)
                            except Exception as e:
                                fe.write(f"Error processing {url}: {type(e).__name__} {e}\n")
                                fe.flush()
                            pbar.update(1)
                    batch = []
                    i += batch_size
                pbar.close()
            # json.dump(datasets, fc, indent=4)

if __name__ == "__main__":
    asyncio.run(main())