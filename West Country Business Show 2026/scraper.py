"""Scrape the West Country Business Show 2026 LiveBuzz exhibitor directory."""

from __future__ import annotations

import csv
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from bs4 import BeautifulSoup

CAMPAIGN = "the-west-country-business-show-2026"
ORGANISATION = "rpmevents"
MODULE = "exhibitors-2026"
SITE_URL = "https://www.westcountrybusinessshow.co.uk/exhibitors"
SETTINGS_URL = f"https://{ORGANISATION}.control.buzz/campaign/{CAMPAIGN}/web-module/{MODULE}/settings"
EVENT_NAME = "West Country Business Show"
YEAR = "2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
CSV_PATH = OUT / "WEST_COUNTRY_BUSINESS_SHOW_2026_exhibitors.csv"
JSON_PATH = OUT / "WEST_COUNTRY_BUSINESS_SHOW_2026_exhibitors.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
BLOCKED = (
    "westcountrybusinessshow.co.uk", "rpmevents.co.uk", "control.buzz",
    "livebuzz.co.uk", "linkedin.com", "facebook.com", "instagram.com",
    "twitter.com", "x.com", "youtube.com", "wikipedia.org", "yellowpages.com",
    "yelp.com", "rocketreach.co", "volza.com", "dnb.com",
    "find-and-update.company-information.service.gov.uk", "leadiq.com",
    "tracxn.com", "jooble.org", "issuu.com", "bbc.com", "poundbury.co.uk",
    "sr.maptons.com", "trustpilot.com", "nace.lursoft.lv",
)
TLD_COUNTRIES = {
    "uk": "United Kingdom", "co.uk": "United Kingdom", "ie": "Ireland",
    "de": "Germany", "fr": "France", "nl": "Netherlands", "be": "Belgium",
    "es": "Spain", "it": "Italy", "us": "United States", "ca": "Canada",
    "au": "Australia",
}
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "booth_no", "name", "desc", "email", "phone", "address", "city",
    "linkedin_url", "profile_url", "source_year",
]


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\ufffd", "")).strip()


def normalize_domain(value: str) -> str:
    value = clean(value)
    if not value or value.casefold().startswith(("mailto:", "tel:")):
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", value, re.I):
        value = "https://" + value.lstrip("/")
    host = urlparse(value).netloc.lower().removeprefix("www.")
    return host if "." in host and not any(item in host for item in BLOCKED) else ""


def extract_email(text: str) -> str:
    match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text or "")
    return match.group(0) if match else ""


def valid_phone(value: str) -> bool:
    return len(re.sub(r"\D", "", value or "")) >= 7


def extract_phone(soup: BeautifulSoup, text: str) -> str:
    link = soup.select_one('a[href^="tel:"]')
    value = clean(link.get("href", "")[4:]) if link else ""
    if not value:
        match = re.search(r"(?:\+?\d[\d\s()./-]{7,}\d)", text or "")
        value = clean(match.group(0)) if match else ""
    return value if valid_phone(value) else ""


def guess_country(domain: str) -> str:
    suffix = ".".join(domain.rsplit(".", 2)[-2:]) if "." in domain else ""
    return TLD_COUNTRIES.get(suffix, TLD_COUNTRIES.get(domain.rsplit(".", 1)[-1], "United Kingdom"))


def get_settings(session: requests.Session) -> dict:
    response = session.get(SETTINGS_URL, timeout=60)
    response.raise_for_status()
    return response.json()


def list_exhibitors(session: requests.Session) -> tuple[list[dict[str, str]], dict]:
    settings = get_settings(session)
    algolia = settings["algolia"]
    index = algolia["indexes"]["exhibitors"]
    host = f"https://{algolia['application_id'].lower()}-dsn.algolia.net"
    headers = {
        "X-Algolia-Application-Id": algolia["application_id"],
        "X-Algolia-API-Key": algolia["search_only_api_key"],
        "Content-Type": "application/json",
    }
    response = session.post(
        f"{host}/1/indexes/*/queries",
        headers=headers,
        json={"requests": [{"indexName": index, "params": "query=&hitsPerPage=1000&page=0"}]},
        timeout=60,
    )
    response.raise_for_status()
    result = response.json()["results"][0]
    records = []
    for hit in result["hits"]:
        records.append({
            "exhibitor_name": clean(hit.get("name", "")),
            "booth_no": ", ".join(clean(value) for value in (hit.get("stands") or []) if clean(value)),
            "object_id": hit.get("objectID", ""),
            "identifier": hit.get("identifier", ""),
            "desc": clean(hit.get("biography", "")),
            "profile_url": f"{SITE_URL}#/exhibitors/{hit.get('identifier', '')}",
        })
    print(f"Found {len(records)} exhibitors in the 2026 directory", flush=True)
    return records, {"host": host, "index": index, "headers": headers}


def fetch_profile(record: dict[str, str], algolia: dict) -> dict[str, str]:
    try:
        response = requests.get(
            f"{algolia['host']}/1/indexes/{algolia['index']}/{record['object_id']}",
            headers=algolia["headers"], timeout=30,
        )
        response.raise_for_status()
        item = response.json()
    except (requests.RequestException, ValueError):
        item = {}
    record["desc"] = record["desc"] or clean(item.get("biography", ""))
    record["domain"] = normalize_domain(item.get("website", ""))
    record["mail"] = clean(item.get("email", ""))
    record["contact_number"] = clean(item.get("phone", ""))
    record["linkedin_url"] = clean(item.get("linkedin", ""))
    record["country"] = clean(item.get("country", ""))
    record["location"] = clean(item.get("address", ""))
    record["address"] = record["location"]
    record["city"] = clean(item.get("city", ""))
    return record


def website_contacts(record: dict[str, str]) -> dict[str, str]:
    if not record.get("domain"):
        return record
    try:
        response = requests.get(f"https://{record['domain']}/", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.content, "lxml")
        text = clean(soup.get_text(" ", strip=True))
        record["mail"] = record.get("mail") or extract_email(text)
        record["contact_number"] = record.get("contact_number") or extract_phone(soup, text)
        record["linkedin_url"] = record.get("linkedin_url") or next(
            (a.get("href", "") for a in soup.select('a[href*="linkedin.com/"]')), ""
        )
    except requests.RequestException:
        pass
    return record


def serper_enrich(record: dict[str, str], api_key: str) -> dict[str, str]:
    if record.get("domain") or not api_key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website {YEAR} United Kingdom', "num": 10},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return record
    knowledge = data.get("knowledgeGraph") or {}
    domain = normalize_domain(knowledge.get("website", ""))
    if not domain:
        for result in data.get("organic", []):
            domain = normalize_domain(result.get("link", ""))
            if domain:
                break
    record["domain"] = domain
    if not record.get("location"):
        record["location"] = record["address"] = clean(knowledge.get("address", ""))
    if not record.get("contact_number"):
        record["contact_number"] = clean(knowledge.get("phone", ""))
    return record


def finalize(record: dict[str, str]) -> dict[str, str]:
    for key in ("domain", "contact_number", "mail", "location", "country", "booth_no",
                "desc", "address", "city", "linkedin_url", "profile_url"):
        record.setdefault(key, "")
    record["name"] = record["exhibitor_name"]
    record["email"] = record["mail"]
    record["phone"] = record["contact_number"]
    record["country"] = record["country"] or guess_country(record["domain"])
    record["source_year"] = YEAR
    record.pop("object_id", None)
    record.pop("identifier", None)
    return record


def scrape() -> list[dict[str, str]]:
    load_dotenv(ROOT.parent / ".env")
    session = requests.Session()
    session.headers.update(HEADERS)
    records, algolia = list_exhibitors(session)
    with ThreadPoolExecutor(max_workers=16) as pool:
        records = list(pool.map(lambda row: fetch_profile(row, algolia), records))
    with ThreadPoolExecutor(max_workers=16) as pool:
        records = list(pool.map(website_contacts, records))
    missing = [row for row in records if not row.get("domain")]
    with ThreadPoolExecutor(max_workers=8) as pool:
        enriched = list(pool.map(lambda row: serper_enrich(row, os.getenv("SERPER_API_KEY", "")), missing))
    by_name = {row["exhibitor_name"].casefold(): row for row in enriched}
    records = [by_name.get(row["exhibitor_name"].casefold(), row) for row in records]
    return [finalize(row) for row in sorted(records, key=lambda row: row["exhibitor_name"].casefold())]


def write_outputs(records: list[dict[str, str]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "event": EVENT_NAME, "year": YEAR, "source": SITE_URL, "total": len(records),
        "scraped_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
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
