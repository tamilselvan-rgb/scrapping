"""Scrape the Villinger Whisky- und Rummesse 2026 exhibitor directory."""

from __future__ import annotations

import csv
import html
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

BASE_URL = "https://whiskymesse-villingen.de/"
LIST_URL = urljoin(BASE_URL, "aussteller-neu-2026/")
EVENT_NAME = "Villinger Whiskymesse"
EVENT_YEAR = "2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
CSV_PATH = OUT / "VILLINGER_WHISKYMESSE_2026_exhibitors.csv"
JSON_PATH = OUT / "VILLINGER_WHISKYMESSE_2026_exhibitors.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}
BLOCKED = {
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com",
    "whiskymesse-villingen.de", "tracxn.com", "whisky.com", "suedwest-messe.de",
}
TLD_COUNTRIES = {
    "de": "Germany", "ch": "Switzerland", "at": "Austria", "dk": "Denmark",
    "gb": "United Kingdom", "uk": "United Kingdom", "co.uk": "United Kingdom",
    "ie": "Ireland", "it": "Italy", "fr": "France", "us": "United States",
}
CSV_FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "name", "desc", "email", "phone", "address", "city", "linkedin_url",
    "profile_url", "source_year",
]


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def normalize_domain(value: str) -> str:
    value = clean(value)
    if not value or value.casefold().startswith(("mailto:", "tel:", "javascript:")):
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", value, re.I):
        value = "https://" + value.lstrip("/")
    host = urlparse(value).netloc.lower().removeprefix("www.")
    return host if "." in host and not any(item in host for item in BLOCKED) else ""


def extract_email(text: str) -> str:
    match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text or "")
    return match.group(0) if match else ""


def extract_phone(soup: BeautifulSoup, text: str) -> str:
    tel = soup.select_one('a[href^="tel:"]')
    if tel:
        candidate = clean(tel.get("href", "")[4:])
        return candidate if valid_phone(candidate) else ""
    match = re.search(r"(?:\+?\d[\d\s()./-]{7,}\d)", text or "")
    candidate = clean(match.group(0)) if match else ""
    return candidate if valid_phone(candidate) else ""


def valid_phone(value: str) -> bool:
    if not value or re.search(r"[a-z]", value, re.I):
        return False
    if re.search(r"\b\d{1,2}[.:]\d{2}\s*-\s*\d{1,2}(?:[.:]\d{2})?\b", value):
        return False
    return len(re.sub(r"\D", "", value)) >= 7


def jsonld_address(soup: BeautifulSoup) -> str:
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        for item in payload if isinstance(payload, list) else [payload]:
            if not isinstance(item, dict):
                continue
            address = item.get("address")
            if isinstance(address, dict):
                parts = [
                    address.get("streetAddress", ""), address.get("postalCode", ""),
                    address.get("addressLocality", ""), address.get("addressRegion", ""),
                    address.get("addressCountry", ""),
                ]
                value = clean(", ".join(str(part) for part in parts if part))
                if value:
                    return value
            elif isinstance(address, str) and clean(address):
                return clean(address)
    return ""


def guess_country(location: str, domain_name: str) -> str:
    low = location.casefold()
    for needle, country in {
        "deutschland": "Germany", "germany": "Germany", "schweiz": "Switzerland",
        "switzerland": "Switzerland", "dänemark": "Denmark", "denmark": "Denmark",
        "schottland": "United Kingdom", "scotland": "United Kingdom",
    }.items():
        if needle in low:
            return country
    suffix = ".".join(domain_name.rsplit(".", 2)[-2:])
    return TLD_COUNTRIES.get(suffix, TLD_COUNTRIES.get(domain_name.rsplit(".", 1)[-1], "Germany"))


def parse_exhibitors(session: requests.Session) -> list[dict[str, str]]:
    response = session.get(LIST_URL, timeout=45)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    stream = soup.select("h2, h3, p")
    in_2026 = False
    records = []
    for index, element in enumerate(stream):
        if element.name == "h3" and "Aussteller auf" in element.get_text(" ", strip=True):
            in_2026 = True
            continue
        if element.name == "h3" and "2017" in element.get_text(" ", strip=True):
            break
        if not in_2026 or element.name != "h2":
            continue
        name = clean(element.get_text(" ", strip=True))
        if not name or name == "Hall of Angels' Share":
            continue
        description_parts = []
        for following in stream[index + 1:]:
            if following.name == "h2" or following.name == "h3":
                break
            if following.name == "p":
                text = clean(following.get_text(" ", strip=True))
                if text:
                    description_parts.append(text)
        slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
        records.append({
            "exhibitor_name": name, "domain": "", "contact_number": "",
            "mail": "", "location": "", "country": "Germany", "name": name,
            "desc": " ".join(description_parts), "email": "", "phone": "",
            "address": "", "city": "", "linkedin_url": "",
            "profile_url": f"{LIST_URL}#{slug}", "source_year": EVENT_YEAR,
        })
    if not records:
        raise RuntimeError("No 2026 whisky exhibitors found")
    return records


def serper_enrich(record: dict[str, str], api_key: str) -> dict[str, str]:
    if not api_key:
        return record
    session = requests.Session()
    session.headers.update(HEADERS)
    query = f'"{record["exhibitor_name"]}" official website {EVENT_YEAR} Germany'
    try:
        response = session.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": 10}, timeout=30,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return record
    knowledge = data.get("knowledgeGraph") or {}
    record["domain"] = normalize_domain(knowledge.get("website", ""))
    if not record["domain"]:
        for item in data.get("organic", []):
            candidate = normalize_domain(item.get("link", ""))
            if candidate:
                record["domain"] = candidate
                break
    if not record["location"]:
        record["location"] = clean(knowledge.get("address", ""))
        record["address"] = record["location"]
    if not record["contact_number"]:
        record["contact_number"] = clean(knowledge.get("phone", ""))
    if not record["mail"]:
        record["mail"] = extract_email(clean(knowledge.get("description", "")))
    return record


def website_contacts(record: dict[str, str]) -> dict[str, str]:
    if not record["domain"]:
        return record
    session = requests.Session()
    session.headers.update(HEADERS)
    base = f"https://{record['domain']}/"
    for suffix in ("", "contact", "kontakt", "impressum", "about"):
        try:
            response = session.get(urljoin(base, suffix), timeout=12)
            if response.status_code >= 400:
                continue
        except requests.RequestException:
            continue
        soup = BeautifulSoup(response.text, "lxml")
        body = clean(soup.get_text(" ", strip=True))
        record["mail"] = record["mail"] or extract_email(body)
        record["contact_number"] = record["contact_number"] or extract_phone(soup, body)
        address = jsonld_address(soup)
        if address:
            record["location"] = record["location"] or address
            record["address"] = record["address"] or address
        if record["mail"] and record["contact_number"] and record["location"]:
            break
    return record


def finalize(record: dict[str, str]) -> dict[str, str]:
    record["email"] = record["mail"]
    record["phone"] = record["contact_number"]
    record["address"] = record["address"] or record["location"]
    record["country"] = guess_country(record["location"], record["domain"])
    return record


def scrape() -> list[dict[str, str]]:
    load_dotenv(ROOT.parent / ".env")
    session = requests.Session()
    session.headers.update(HEADERS)
    records = parse_exhibitors(session)
    api_key = os.getenv("SERPER_API_KEY", "")
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(lambda row: serper_enrich(row, api_key), records))
    with ThreadPoolExecutor(max_workers=12) as pool:
        records = [finalize(row) for row in pool.map(website_contacts, records)]
    return sorted(records, key=lambda row: row["exhibitor_name"].casefold())


def write_outputs(records: list[dict[str, str]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "event": EVENT_NAME, "year": EVENT_YEAR, "source": LIST_URL,
        "scraped_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(records), "exhibitors": records,
    }
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(records)


if __name__ == "__main__":
    started = time.time()
    rows = scrape()
    write_outputs(rows)
    print(f"Saved {len(rows)} exhibitors in {time.time() - started:.1f}s")
