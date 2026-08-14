"""Python mirror of cassava_crawler.js — recursively crawls the nginx directory
listing under the Cassava datasets root and writes every file URL to a JSON list
(the "crawled Cassava List" consumed by unzip_cassava.py)."""

import json
import sys
from html.parser import HTMLParser
from urllib.parse import urljoin

import requests

BASE = "https://cassava.ucsd.edu/sparc/datasets/"
OUT = "./cassava_crawl.json"
TIMEOUT = 60


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.hrefs.append(value)


def crawl(base):
    session = requests.Session()
    files = set()
    visited = set()
    pending = [base]

    while pending:
        url = pending.pop()
        if url in visited:
            continue
        visited.add(url)

        try:
            response = session.get(url, timeout=TIMEOUT)
        except requests.RequestException as exc:
            print(f"  request failed: {url} ({exc})", file=sys.stderr)
            continue
        if response.status_code != 200:
            print(f"  {response.status_code}: {url}", file=sys.stderr)
            continue

        parser = LinkParser()
        parser.feed(response.text)
        for href in parser.hrefs:
            if href in ("../", "/"):
                continue
            absolute = urljoin(url, href)
            # stay within the datasets tree
            if not absolute.startswith(base):
                continue
            if absolute.endswith("/"):
                pending.append(absolute)
            else:
                files.add(absolute)

        if len(visited) % 100 == 0:
            print(f"  crawled {len(visited)} directories, {len(files)} files so far...", file=sys.stderr)

    return sorted(files)


def main():
    files = crawl(BASE)
    with open(OUT, "w") as f:
        json.dump(files, f, indent=4)
    print(f"Crawl complete. Found {len(files)} files -> {OUT}")


if __name__ == "__main__":
    main()
