"""Scrape the official ICID 2026 floorplan exhibitor directory."""

from __future__ import annotations

import csv
import html
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

EVENT_NAME = "International Congress on Infectious Diseases"
EVENT_YEAR = "2026"
SOURCE_URL = "https://apps.kenes.com/floorplan/#/congress/ICID26"
API_BASE = "https://apps.kenes.com/floorplan/ServerAPI/api/"
CONGRESS_ID = "a09Vj0000090flxIAA"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
CSV_PATH = OUTPUT / "INTERNATIONAL_CONGRESS_ON_INFECTIOUS_DISEASES_2026_exhibitors.csv"
JSON_PATH = OUTPUT / "INTERNATIONAL_CONGRESS_ON_INFECTIOUS_DISEASES_2026_exhibitors.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
BLOCKED_DOMAINS = {
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com",
    "google.com", "ncbi.nlm.nih.gov",
}
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "name", "desc", "email", "phone", "address", "city", "linkedin_url",
    "stand", "profile_url", "source_year", "source_url",
]


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def normalize_domain(value: object) -> str:
    raw = clean(value)
    if not raw:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.I):
        raw = "https://" + raw
    host = urlparse(raw).netloc.lower().removeprefix("www.")
    if "." not in host:
        return ""
    if any(host == blocked or host.endswith("." + blocked) for blocked in BLOCKED_DOMAINS):
        return ""
    return host


def extract_email(text: str) -> str:
    match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text or "")
    return match.group(0) if match else ""


def jsonld_values(soup: BeautifulSoup) -> list[dict]:
    values = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        values.extend(payload if isinstance(payload, list) else [payload])
    return [item for item in values if isinstance(item, dict)]


def structured_contact(soup: BeautifulSoup) -> tuple[str, str, str, str, str]:
    address = city = country = ""
    for item in jsonld_values(soup):
        addr = item.get("address")
        if isinstance(addr, dict):
            address = address or clean(addr.get("streetAddress"))
            city = city or clean(addr.get("addressLocality"))
            country_value = addr.get("addressCountry", "")
            country = country or clean(
                country_value.get("name") if isinstance(country_value, dict) else country_value
            )
        if not address and isinstance(addr, str):
            address = clean(addr)
        city = city or clean(item.get("addressLocality"))
        country = country or clean(item.get("addressCountry"))
    return address, city, country, "", ""


def guess_country(address: str, city: str, domain: str) -> str:
    text = f"{address} {city}".casefold()
    countries = {
        "spain": "Spain", "madrid": "Spain", "united kingdom": "United Kingdom",
        "germany": "Germany", "denmark": "Denmark", "netherlands": "Netherlands",
        "france": "France", "united states": "United States", "usa": "United States",
        "canada": "Canada", "switzerland": "Switzerland", "ireland": "Ireland",
        "belgium": "Belgium", "austria": "Austria", "italy": "Italy",
    }
    for needle, country in countries.items():
        if re.search(rf"\b{re.escape(needle)}\b", text):
            return country
    tld = domain.rsplit(".", 1)[-1] if "." in domain else ""
    return {
        "es": "Spain", "uk": "United Kingdom", "de": "Germany", "dk": "Denmark",
        "nl": "Netherlands", "fr": "France", "it": "Italy", "us": "United States",
    }.get(tld, "")


def empty_record(item: dict) -> dict[str, str]:
    name = clean(item.get("name"))
    return {
        "exhibitor_name": name,
        "domain": normalize_domain(item.get("webSite")),
        "contact_number": "",
        "mail": "",
        "location": "",
        "country": "",
        "name": name,
        "desc": clean(item.get("profile")),
        "email": "",
        "phone": "",
        "address": "",
        "city": "",
        "linkedin_url": "",
        "stand": clean(item.get("boothNo")),
        "profile_url": f"{SOURCE_URL}&exhibitor={item.get('id', '')}",
        "source_year": EVENT_YEAR,
        "source_url": SOURCE_URL,
    }


def serper_enrich(record: dict[str, str], api_key: str) -> None:
    if not api_key:
        return
    query = f'"{record["exhibitor_name"]}" official website {EVENT_YEAR}'
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": 8},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return
    knowledge = data.get("knowledgeGraph") or {}
    if not record["domain"]:
        record["domain"] = normalize_domain(knowledge.get("website"))
    if not record["domain"]:
        for result in data.get("organic", []):
            candidate = normalize_domain(result.get("link"))
            if candidate:
                record["domain"] = candidate
                break
    if not record["contact_number"]:
        record["contact_number"] = clean(knowledge.get("phone"))
    if not record["location"]:
        record["location"] = clean(knowledge.get("address"))
    if not record["desc"]:
        record["desc"] = clean(knowledge.get("description"))
    if not record["linkedin_url"]:
        record["linkedin_url"] = next(
            (clean(result.get("link")).split("?")[0] for result in data.get("organic", [])
             if "linkedin.com/" in clean(result.get("link")).lower()),
            "",
        )


def enrich_from_website(record: dict[str, str]) -> dict[str, str]:
    if not record["domain"]:
        return record
    session = requests.Session()
    session.headers.update(HEADERS)
    base = f"https://{record['domain']}/"
    for suffix in ("", "contact", "contact-us", "about", "about-us", "impressum"):
        try:
            response = session.get(urljoin(base, suffix), timeout=15)
            if response.status_code >= 400:
                continue
        except requests.RequestException:
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        body = clean(soup.get_text(" ", strip=True))
        if not record["mail"]:
            record["mail"] = extract_email(body)
        if not record["contact_number"]:
            tel = soup.select_one('a[href^="tel:"]')
            if tel:
                record["contact_number"] = clean(tel.get("href", "")[4:])
        address, city, country, _, _ = structured_contact(soup)
        record["address"] = record["address"] or address
        record["city"] = record["city"] or city
        record["country"] = record["country"] or country
        if not record["location"] and record["address"]:
            record["location"] = record["address"]
        if not record["linkedin_url"]:
            record["linkedin_url"] = next(
                (clean(a.get("href")).split("?")[0] for a in soup.find_all("a", href=True)
                 if "linkedin.com/" in clean(a.get("href")).lower()),
                "",
            )
        if record["mail"] and record["contact_number"] and record["location"]:
            break
    return record


def scrape() -> list[dict[str, str]]:
    load_dotenv(ROOT.parent / ".env")
    session = requests.Session()
    session.headers.update(HEADERS)
    response = session.get(
        f"{API_BASE}getExhibitorListByCongressId/{CONGRESS_ID}", timeout=45
    )
    response.raise_for_status()
    items = [item for item in response.json() if item.get("isVisibleInList") in (True, "true")]
    if not items:
        raise RuntimeError("No visible ICID26 exhibitors found")
    api_key = os.getenv("SERPER_API_KEY", "")
    records = [empty_record(item) for item in items]
    with ThreadPoolExecutor(max_workers=6) as executor:
        jobs = {}
        for record in records:
            if not record["domain"] or not record["location"] or not record["contact_number"]:
                serper_enrich(record, api_key)
            jobs[executor.submit(enrich_from_website, record)] = record
        for job in as_completed(jobs):
            job.result()
    for record in records:
        record["country"] = record["country"] or guess_country(
            record["address"], record["city"], record["domain"]
        )
        record["location"] = record["location"] or record["address"]
        record["address"] = record["address"] or record["location"]
        record["email"] = record["mail"]
        record["phone"] = record["contact_number"]
    return sorted(records, key=lambda row: row["exhibitor_name"].casefold())


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
