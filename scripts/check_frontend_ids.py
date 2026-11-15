#!/usr/bin/env python3
"""Check that literal dashboard JavaScript ID selectors exist exactly once in HTML."""
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "frontend" / "index.html"
JS_PATH = ROOT / "frontend" / "app.js"


class IdCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name == "id" and value:
                self.ids.append(value)


def main():
    html = HTML_PATH.read_text(encoding="utf-8")
    js = JS_PATH.read_text(encoding="utf-8")
    collector = IdCollector()
    collector.feed(html)
    counts = Counter(collector.ids)
    duplicates = sorted(key for key, count in counts.items() if count > 1)
    selectors = set(re.findall(r'\\$\\(["\\']([^"\\']+)["\\']\\)', js))
    missing = sorted(selectors - set(counts))
    if duplicates or missing:
        if duplicates:
            print("Duplicate HTML IDs: " + ", ".join(duplicates), file=sys.stderr)
        if missing:
            print("JavaScript selectors without HTML IDs: " + ", ".join(missing),
                  file=sys.stderr)
        return 1
    print(f"Frontend ID validation passed: {len(counts)} unique IDs, "
          f"{len(selectors)} literal selectors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
