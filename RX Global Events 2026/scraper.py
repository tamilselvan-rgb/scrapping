"""Scrape the RX Global events listing and build the 2026 event pipeline output."""
from __future__ import annotations

import csv
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


SOURCE_URL = "https://rxglobal.com/events"
FILTER_URL = "https://rxglobal.com/events/rx/filter"
ROOT = Path(__file__).resolve().parent
FIELDS = [
    "event_name", "event_start_date", "event_end_", "venue",
    "city", "country", "event_domain",
]
MONTHS = {
    name: index for index, name in enumerate(
        ("january", "february", "march", "april", "may", "june",
         "july", "august", "september", "october", "november", "december"), 1
    )
}


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def domain(url: str) -> str:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return host


def parse_date_range(value: str) -> tuple[str, str]:
    value = clean(value)
    match = re.search(
        r"(?P<start>\d{1,2})(?:st|nd|rd|th)?\s*[-–]\s*"
        r"(?P<end>\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(?P<month>[A-Za-z]+)\s+(?P<year>\d{4})", value, re.I,
    )
    if not match:
        single = re.search(
            r"(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+"
            r"(?P<month>[A-Za-z]+)\s+(?P<year>\d{4})", value, re.I,
        )
        if not single:
            return "", ""
        day = int(single.group("day"))
        month = MONTHS[single.group("month").lower()]
        year = int(single.group("year"))
        value = date(year, month, day).isoformat()
        return value, value
    start = int(match.group("start"))
    end = int(match.group("end"))
    month = MONTHS[match.group("month").lower()]
    year = int(match.group("year"))
    return date(year, month, start).isoformat(), date(year, month, end).isoformat()


def parse_cards(fragment: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(fragment, "html.parser")
    rows = []
    for card in soup.select("a[aria-label^='Visit Event Website']"):
        block = card.select_one(".event-block")
        if not block:
            continue
        name = clean(block.select_one(".event-title").get_text(" ")) if block.select_one(".event-title") else ""
        location = clean(block.select_one(".event-location").get_text(" ")) if block.select_one(".event-location") else ""
        venue = clean(block.select_one(".event-meta-location").get_text(" ")) if block.select_one(".event-meta-location") else ""
        date_text = clean(block.select_one(".event-date").get_text(" ")) if block.select_one(".event-date") else ""
        start, end = parse_date_range(date_text)
        parts = [clean(x) for x in re.split(r"[>»]", location) if clean(x)]
        country = parts[-2] if len(parts) >= 2 else ""
        city = parts[-1] if len(parts) >= 1 else ""
        rows.append({
            "event_name": name,
            "event_start_date": start,
            "event_end_": end,
            "venue": venue,
            "city": city,
            "country": country,
            "event_domain": domain(card.get("href", "")),
        })
    return rows


def main() -> None:
    session = requests.Session()
    response = session.get(SOURCE_URL, timeout=60)
    response.raise_for_status()
    (ROOT / "source.html").write_text(response.text, encoding="utf-8")
    payload = {"search": "", "happening": "All", "industry": "All",
               "location": "All", "sector": "All", "page": 0}
    first = session.post(FILTER_URL, data=payload, timeout=60).json()
    total_pages = int(first["total"]) + 1
    fragments = [first["html"]]
    for page in range(1, total_pages):
        payload["page"] = page
        fragments.append(session.post(FILTER_URL, data=payload, timeout=60).json()["html"])
    rows = [
        row for fragment in fragments for row in parse_cards(fragment)
        if row["event_start_date"].startswith("2026-")
    ]
    unique = {(row["event_name"], row["event_start_date"], row["event_domain"]): row for row in rows}
    rows = list(unique.values())
    if len(rows) < 100:
        raise RuntimeError(f"Expected the 2026 RX directory, found {len(rows)} events")
    rows.sort(key=lambda row: (row["event_start_date"] or "9999-99-99", row["event_name"]))
    print(f"=== RX Global Event Listing Verification ===")
    print(f"Pages Scraped    : {total_pages}")
    print(f"Total Events     : {len(rows)}")
    print(f"Dates Coverage   : {sum(bool(row['event_start_date']) for row in rows)}/{len(rows)}")
    print(f"Domain Coverage  : {sum(bool(row['event_domain']) for row in rows)}/{len(rows)}")
    print("Status           : PASSED")
    csv_path = ROOT / "RX_GLOBAL_2026_events.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    (ROOT / "RX_GLOBAL_2026_events.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Exported {len(rows)} events to {ROOT}")


if __name__ == "__main__":
    main()
