"""Scrape exhibitors for The Sociology Days (Socionomdagarna) 2026."""

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
from bs4 import BeautifulSoup
from dotenv import load_dotenv

LIST_URL = "https://www.socionomdagarna.se/utstallare/"
EVENT_NAME = "The Sociology Days"
YEAR = "2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
CSV_PATH = OUT / "THE_SOCIOLOGY_DAYS_2026_exhibitors.csv"
JSON_PATH = OUT / "THE_SOCIOLOGY_DAYS_2026_exhibitors.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
BLOCKED = (
    "socionomdagarna.se", "insightevents.se", "linkedin.com", "facebook.com",
    "instagram.com", "twitter.com", "x.com", "youtube.com", "wikipedia.org",
    "yellowpages.com", "yelp.com",
)
TLD_COUNTRIES = {
    "se": "Sweden", "dk": "Denmark", "no": "Norway", "fi": "Finland",
    "de": "Germany", "at": "Austria", "ch": "Switzerland", "nl": "Netherlands",
    "fr": "France", "uk": "United Kingdom", "co.uk": "United Kingdom",
    "us": "United States", "ca": "Canada", "au": "Australia",
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
    return host if "." in host and not any(part in host for part in BLOCKED) else ""


def extract_email(text: str) -> str:
    match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text or "")
    return match.group(0) if match else ""


def valid_phone(value: str) -> bool:
    return len(re.sub(r"\D", "", value or "")) >= 7 and not re.search(
        r"\b\d{1,2}[.-]\d{1,2}[.-]\d{4}\b", value or ""
    )


def extract_phone(soup: BeautifulSoup, text: str) -> str:
    link = soup.select_one('a[href^="tel:"]')
    value = clean(link.get("href", "")[4:]) if link else ""
    if not value:
        match = re.search(r"(?:\+?\d[\d\s()./-]{7,}\d)", text or "")
        value = clean(match.group(0)) if match else ""
    return value if valid_phone(value) else ""


def guess_country(domain: str, fallback: str = "Sweden") -> str:
    suffix = ".".join(domain.rsplit(".", 2)[-2:]) if "." in domain else ""
    return TLD_COUNTRIES.get(suffix, TLD_COUNTRIES.get(domain.rsplit(".", 1)[-1], fallback))


def jsonld_address(soup: BeautifulSoup) -> str:
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        values = payload if isinstance(payload, list) else [payload]
        for item in values:
            if not isinstance(item, dict):
                continue
            address = item.get("address")
            if isinstance(address, dict):
                parts = [address.get(key, "") for key in (
                    "streetAddress", "postalCode", "addressLocality", "addressRegion", "addressCountry"
                )]
                value = clean(", ".join(str(part) for part in parts if part))
                if value:
                    return value
    return ""


def list_exhibitors(session: requests.Session) -> list[dict[str, str]]:
    response = session.get(LIST_URL, timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "lxml")
    found: dict[str, dict[str, str]] = {}
    for heading in soup.select("h4.pt-cv-title"):
        anchor = heading.find("a", href=True)
        name = clean(heading.get_text(" ", strip=True))
        domain = normalize_domain(anchor.get("href", "")) if anchor else ""
        if name:
            found[name.casefold()] = {
                "exhibitor_name": name,
                "domain": domain,
                "profile_url": anchor.get("href", "") if anchor else "",
                "booth_no": "",
            }
    print(f"Found {len(found)} exhibitors in the 2026 directory", flush=True)
    return list(found.values())


def website_contacts(record: dict[str, str]) -> dict[str, str]:
    if not record.get("domain"):
        return record
    for suffix in ("", "contact", "contact-us", "kontakt", "om-oss", "about"):
        try:
            response = requests.get(
                f"https://{record['domain']}/{suffix}", headers=HEADERS, timeout=15
            )
            if response.status_code >= 400:
                continue
        except requests.RequestException:
            continue
        soup = BeautifulSoup(response.content, "lxml")
        text = clean(soup.get_text(" ", strip=True))
        record["mail"] = record.get("mail") or extract_email(text)
        record["contact_number"] = record.get("contact_number") or extract_phone(soup, text)
        address = jsonld_address(soup)
        if address:
            record["location"] = record.get("location") or address
            record["address"] = record.get("address") or address
        record["linkedin_url"] = record.get("linkedin_url") or next(
            (a.get("href", "") for a in soup.select('a[href*="linkedin.com/"]')), ""
        )
        if record["mail"] and record["contact_number"] and record.get("location"):
            break
    return record


def serper_enrich(record: dict[str, str], api_key: str) -> dict[str, str]:
    if record.get("domain") or not api_key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website {YEAR} Sweden', "num": 10},
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
        record["location"] = clean(knowledge.get("address", ""))
        record["address"] = record["location"]
    if not record.get("contact_number"):
        record["contact_number"] = clean(knowledge.get("phone", ""))
    return record


def finalize(record: dict[str, str]) -> dict[str, str]:
    for key in ("domain", "desc", "mail", "contact_number", "location", "address", "city", "linkedin_url", "booth_no"):
        record.setdefault(key, "")
    record["name"] = record["exhibitor_name"]
    record["email"] = record["mail"]
    record["phone"] = record["contact_number"]
    record["country"] = guess_country(record["domain"])
    record["source_year"] = YEAR
    return record


def scrape() -> list[dict[str, str]]:
    load_dotenv(ROOT.parent / ".env")
    session = requests.Session()
    session.headers.update(HEADERS)
    records = list_exhibitors(session)
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
        "event": EVENT_NAME, "year": YEAR, "source": LIST_URL, "total": len(records),
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
