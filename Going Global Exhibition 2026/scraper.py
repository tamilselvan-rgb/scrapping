"""Scrape Going Global Exhibition 2026 from the official exhibitor directory."""

from __future__ import annotations

import csv
import importlib.util
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
SOURCE_SCRIPT = PROJECT_ROOT / "Going Global Live 2026" / "scraper.py"
OUTPUT = ROOT / "output"
CSV_PATH = OUTPUT / "GOING_GLOBAL_EXHIBITION_2026_exhibitors.csv"
JSON_PATH = OUTPUT / "GOING_GLOBAL_EXHIBITION_2026_exhibitors.json"
SOURCE_URL = "https://www.goinggloballive.co.uk/exhibitors"
EVENT_NAME = "Going Global Exhibition"
EVENT_YEAR = "2026"
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "booth_no", "name", "desc", "email", "phone", "address", "city",
    "linkedin_url", "profile_url", "source_year", "category", "source_url",
]


def load_source_module():
    spec = importlib.util.spec_from_file_location("going_global_source", SOURCE_SCRIPT)
    if not spec or not spec.loader:
        raise RuntimeError(f"Could not load source scraper: {SOURCE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fetch_profile(source, record):
    try:
        response = requests.get(record["profile_url"], headers=source.HEADERS, timeout=30)
        response.raise_for_status()
        return source.parse_profile(record, response.text)
    except requests.RequestException:
        return record


def scrape() -> list[dict[str, str]]:
    source = load_source_module()
    load_dotenv(PROJECT_ROOT / ".env")
    session = requests.Session()
    session.headers.update(source.HEADERS)
    response = session.get(SOURCE_URL, timeout=45)
    response.raise_for_status()
    records = source.parse_directory(response.text)
    print(f"Found {len(records)} unique 2026 exhibitors", flush=True)

    with ThreadPoolExecutor(max_workers=10) as executor:
        jobs = [executor.submit(fetch_profile, source, record) for record in records]
        profiles = [job.result() for job in as_completed(jobs)]
        website_jobs = [executor.submit(source.crawl_website, record) for record in profiles]
        profiles = [job.result() for job in as_completed(website_jobs)]

    source.serper_fallback(profiles, os.getenv("SERPER_API_KEY", ""))
    exported = []
    for record in profiles:
        record["booth_no"] = record.pop("stand", "")
        record["source_year"] = EVENT_YEAR
        record["source_url"] = SOURCE_URL
        record["email"] = record.get("mail", "")
        record["phone"] = record.get("contact_number", "")
        record["address"] = record.get("address", "")
        record["city"] = record.get("city", "")
        exported.append({field: record.get(field, "") for field in FIELDS})
    return sorted(exported, key=lambda row: row["exhibitor_name"].casefold())


def write_outputs(records: list[dict[str, str]]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "event": EVENT_NAME,
        "year": EVENT_YEAR,
        "source": SOURCE_URL,
        "scraped_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(records),
        "exhibitors": records,
    }
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)


if __name__ == "__main__":
    rows = scrape()
    write_outputs(rows)
    print(f"Saved {len(rows)} exhibitors")
    print(CSV_PATH)
    print(JSON_PATH)
