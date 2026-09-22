"""Scrape the tcworld conference 2026 exhibitor directory."""

from __future__ import annotations

import csv
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

LIST_URL = "https://tcworldconference.tekom.de/fair/exhibitor-directory"
BASE_URL = "https://tcworldconference.tekom.de/"
EVENT_NAME = "Tcworld Conference & Exhibition"
YEAR = "2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
CSV_PATH = OUT / "TCWORLD_CONFERENCE_EXHIBITION_2026_exhibitors.csv"
JSON_PATH = OUT / "TCWORLD_CONFERENCE_EXHIBITION_2026_exhibitors.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
BLOCKED = (
    "tcworldconference.tekom.de", "tekom.de", "tekom.eu", "linkedin.com",
    "facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com",
    "wikipedia.org", "yellowpages.com", "yelp.com",
)
COUNTRIES = {
    "deutschland": "Germany", "germany": "Germany", "österreich": "Austria",
    "austria": "Austria", "frankreich": "France", "france": "France",
    "schweiz": "Switzerland", "switzerland": "Switzerland", "vereinigte staaten": "United States",
    "united states": "United States", "great britain": "United Kingdom",
}
TLD_COUNTRIES = {
    "de": "Germany", "at": "Austria", "fr": "France", "ch": "Switzerland",
    "nl": "Netherlands", "uk": "United Kingdom", "co.uk": "United Kingdom",
    "us": "United States", "ca": "Canada", "jp": "Japan", "dk": "Denmark",
    "fi": "Finland", "be": "Belgium", "hu": "Hungary", "my": "Malaysia",
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


def extract_email(value: str) -> str:
    match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", value or "")
    return match.group(0) if match else ""


def valid_phone(value: str) -> bool:
    return len(re.sub(r"\D", "", value or "")) >= 7


def guess_country(location: str, domain: str, fallback: str = "Germany") -> str:
    low = location.casefold()
    for key, country in COUNTRIES.items():
        if key in low:
            return country
    suffix = ".".join(domain.rsplit(".", 2)[-2:]) if "." in domain else ""
    return TLD_COUNTRIES.get(suffix, TLD_COUNTRIES.get(domain.rsplit(".", 1)[-1], fallback))


def list_exhibitors(session: requests.Session) -> list[dict[str, str]]:
    response = session.get(LIST_URL, timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    found: dict[str, dict[str, str]] = {}
    for anchor in soup.select('a[href*="/fair/exhibitor-directory/"]'):
        url = urljoin(BASE_URL, anchor.get("href", ""))
        if url.rstrip("/") == LIST_URL.rstrip("/"):
            continue
        name = clean(anchor.get_text(" ", strip=True))
        if name and url:
            found[url] = {"exhibitor_name": name, "profile_url": url}
    print(f"Found {len(found)} exhibitors in the 2026 directory", flush=True)
    return list(found.values())


def parse_profile(record: dict[str, str]) -> dict[str, str]:
    try:
        response = requests.get(record["profile_url"], headers=HEADERS, timeout=60)
        response.raise_for_status()
    except requests.RequestException:
        return record
    soup = BeautifulSoup(response.text, "lxml")
    heading = soup.find("h1")
    record["exhibitor_name"] = clean(heading.get_text(" ", strip=True)) if heading else record["exhibitor_name"]
    intro = soup.select_one(".intro")
    address = ""
    city = ""
    if intro:
        address_items = intro.select("ul.ul-border-style li")
        address_parts = [clean(item.get_text(" ", strip=True)) for item in address_items]
        address = ", ".join(address_parts)
        if len(address_parts) > 1:
            city = address_parts[1].split("(")[0].strip()
        booth_item = intro.select_one("li.icon-t-location")
        if booth_item:
            booth_text = clean(booth_item.get_text(" ", strip=True))
            record["booth_no"] = clean(re.sub(r"^Booth\s*", "", booth_text, flags=re.I))
    content = soup.select_one(".content-element")
    containers = content.select(":scope > .container") if content else []
    if len(containers) > 1:
        description_block = containers[1].select_one(".content-element")
        record["desc"] = clean(
            description_block.get_text(" ", strip=True)
            if description_block else containers[1].get_text(" ", strip=True)
        )
    record["address"] = address
    record["city"] = city
    record["location"] = address
    record["country"] = guess_country(address, "")
    contact = next(
        (
            item for item in soup.select("ul.ul-white")
            if "Telefon:" in item.get_text() or item.select_one("a[data-mailto-token]")
        ),
        None,
    )
    if contact:
        phone_text = next(
            (clean(item.get_text(" ", strip=True).split(":", 1)[1])
             for item in contact.select("li") if "Telefon:" in item.get_text()),
            "",
        )
        record["contact_number"] = phone_text if valid_phone(phone_text) else ""
        email_anchor = contact.select_one("a[data-mailto-token]")
        if email_anchor:
            for hidden in email_anchor.select('[style*="display:none"]'):
                hidden.decompose()
            record["mail"] = extract_email(email_anchor.get_text("", strip=True))
        else:
            record["mail"] = extract_email(contact.get_text(" ", strip=True))
    website = next(
        (normalize_domain(a.get("href", "")) for a in contact.select("a[href]")
         if normalize_domain(a.get("href", "")))
        if contact else iter(()),
        "",
    )
    record["domain"] = website
    record["linkedin_url"] = next(
        (a.get("href", "") for a in soup.select('a[href*="linkedin.com/"]')
         if "tekom" not in a.get("href", "").casefold()
         and "groups/1789584" not in a.get("href", "")),
        "",
    )
    return record


def serper_enrich(record: dict[str, str], api_key: str) -> dict[str, str]:
    if record.get("domain") or not api_key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website {YEAR} {record.get("city", "")}', "num": 10},
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
    record["country"] = guess_country(record.get("location", ""), domain)
    return record


def finalize(record: dict[str, str]) -> dict[str, str]:
    for key in ("domain", "desc", "mail", "contact_number", "location", "address", "city", "linkedin_url", "booth_no"):
        record.setdefault(key, "")
    record["name"] = record["exhibitor_name"]
    record["email"] = record["mail"]
    record["phone"] = record["contact_number"]
    record["country"] = record.get("country") or guess_country(record["location"], record["domain"])
    record["source_year"] = YEAR
    return record


def scrape() -> list[dict[str, str]]:
    load_dotenv(ROOT.parent / ".env")
    session = requests.Session()
    session.headers.update(HEADERS)
    records = list_exhibitors(session)
    with ThreadPoolExecutor(max_workers=16) as pool:
        records = list(pool.map(parse_profile, records))
    missing = [row for row in records if not row.get("domain")]
    with ThreadPoolExecutor(max_workers=8) as pool:
        enriched = list(pool.map(lambda row: serper_enrich(row, os.getenv("SERPER_API_KEY", "")), missing))
    by_url = {row["profile_url"]: row for row in enriched}
    records = [by_url.get(row["profile_url"], row) for row in records]
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
