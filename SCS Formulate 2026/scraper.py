"""Scrape the SCS Formulate 2026 exhibitor directory."""

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

LIST_URL = "https://www.scsformulate.co.uk/exhibitor-list/"
BASE_URL = "https://www.scsformulate.co.uk/"
EVENT_NAME = "SCS Formulate"
YEAR = "2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
CSV_PATH = OUT / "SCS_FORMULATE_2026_exhibitors.csv"
JSON_PATH = OUT / "SCS_FORMULATE_2026_exhibitors.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
BLOCKED = (
    "scsformulate.co.uk", "scs.org.uk", "step-exhibitions.com", "linkedin.com",
    "facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com",
    "wikipedia.org", "yellowpages.com", "yelp.com", "miramedia.co.uk",
)
TLD_COUNTRIES = {
    "uk": "United Kingdom", "co.uk": "United Kingdom", "de": "Germany",
    "fr": "France", "it": "Italy", "es": "Spain", "nl": "Netherlands",
    "be": "Belgium", "ch": "Switzerland", "at": "Austria", "us": "United States",
    "ca": "Canada", "au": "Australia", "ie": "Ireland", "in": "India",
    "cn": "China", "jp": "Japan", "sg": "Singapore",
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
    digits = re.sub(r"\D", "", value or "")
    return len(digits) >= 7 and not re.search(r"\b\d{1,2}[.-]\d{1,2}[.-]\d{4}\b", value or "")


def extract_phone(soup: BeautifulSoup, text: str) -> str:
    link = soup.select_one('a[href^="tel:"]')
    candidate = clean(link.get("href", "")[4:]) if link else ""
    if not candidate:
        match = re.search(r"(?:\+?\d[\d\s()./-]{7,}\d)", text or "")
        candidate = clean(match.group(0)) if match else ""
    return candidate if valid_phone(candidate) else ""


def guess_country(domain: str, fallback: str = "United Kingdom") -> str:
    parts = domain.rsplit(".", 2)
    suffix = ".".join(parts[-2:]) if len(parts) > 1 else ""
    return TLD_COUNTRIES.get(suffix, TLD_COUNTRIES.get(domain.rsplit(".", 1)[-1], fallback))


def list_exhibitors(session: requests.Session) -> list[dict[str, str]]:
    response = session.get(LIST_URL, timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    found: dict[str, dict[str, str]] = {}
    for row in soup.select("tr"):
        anchor = row.select_one('a[href*="/exhibitor/"]')
        if not anchor:
            continue
        url = urljoin(BASE_URL, anchor.get("href", ""))
        name = clean(anchor.get_text(" ", strip=True))
        cells = [clean(cell.get_text(" ", strip=True)) for cell in row.select("td")]
        booth = cells[1] if len(cells) > 1 else ""
        if name and url:
            found[url] = {
                "exhibitor_name": name, "booth_no": booth, "profile_url": url,
            }
    print(f"Found {len(found)} exhibitors in the 2026 directory", flush=True)
    return list(found.values())


def parse_profile(record: dict[str, str]) -> dict[str, str]:
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        response = session.get(record["profile_url"], timeout=60)
        response.raise_for_status()
    except requests.RequestException:
        return record
    soup = BeautifulSoup(response.text, "lxml")
    heading = soup.select_one("h1")
    record["exhibitor_name"] = clean(heading.get_text(" ", strip=True)) if heading else record["exhibitor_name"]
    website = next(
        (normalize_domain(a.get("href", "")) for a in soup.select("a[href]")
         if normalize_domain(a.get("href", ""))),
        "",
    )
    record["domain"] = website
    profile = soup.select_one("#company-profile")
    if profile:
        record["desc"] = clean(profile.find("p").get_text(" ", strip=True)) if profile.find("p") else ""
        stand = profile.select_one("strong:-soup-contains('Stand:')")
        if stand and stand.parent:
            record["booth_no"] = clean(stand.parent.get_text(" ", strip=True).replace("Stand:", ""))
    record["mail"] = ""
    # The page footer contains Society for Cosmetic Science organizer contacts;
    # do not attribute those shared contacts to every exhibitor.
    record["contact_number"] = extract_phone(profile, profile.get_text(" ", strip=True)) if profile else ""
    record["linkedin_url"] = next(
        (
            a.get("href", "") for a in soup.select('a[href*="linkedin.com/"]')
            if "10729585" not in a.get("href", "")
        ),
        "",
    )
    record["country"] = guess_country(record["domain"])
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
    record["country"] = guess_country(domain)
    return record


def website_contacts(record: dict[str, str]) -> dict[str, str]:
    if not record.get("domain"):
        return record
    try:
        response = requests.get(f"https://{record['domain']}/", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, "lxml")
        text = soup.get_text(" ", strip=True)
        record["mail"] = extract_email(text)
        record["contact_number"] = record["contact_number"] or extract_phone(soup, text)
    except requests.RequestException:
        pass
    return record


def finalize(record: dict[str, str]) -> dict[str, str]:
    record.setdefault("domain", "")
    record.setdefault("desc", "")
    record.setdefault("mail", "")
    record.setdefault("contact_number", "")
    record.setdefault("linkedin_url", "")
    record["name"] = record["exhibitor_name"]
    record["email"] = record["mail"]
    record["phone"] = record["contact_number"]
    record["address"] = record.get("address", "")
    record["city"] = record.get("city", "")
    record["location"] = record.get("location", "")
    record["country"] = record.get("country") or guess_country(record["domain"])
    record["source_year"] = YEAR
    return record


def scrape() -> list[dict[str, str]]:
    load_dotenv(ROOT.parent / ".env")
    session = requests.Session()
    session.headers.update(HEADERS)
    records = list_exhibitors(session)
    with ThreadPoolExecutor(max_workers=20) as pool:
        records = list(pool.map(parse_profile, records))
    missing = [row for row in records if not row.get("domain")]
    with ThreadPoolExecutor(max_workers=8) as pool:
        enriched = list(pool.map(lambda row: serper_enrich(row, os.getenv("SERPER_API_KEY", "")), missing))
    by_url = {row["profile_url"]: row for row in enriched}
    records = [by_url.get(row["profile_url"], row) for row in records]
    with ThreadPoolExecutor(max_workers=20) as pool:
        records = list(pool.map(website_contacts, records))
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
