"""Scrape the SITV Colmar 2026 exhibitor halls."""

from __future__ import annotations

import csv
import html
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

BASE_URL = "https://www.sitvcolmar.com/"
LIST_URL = urljoin(BASE_URL, "les-exposants")
EVENT_NAME = "Sitv Colmar"
EVENT_YEAR = "2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
CSV_PATH = OUT / "SITV_COLMAR_2026_exhibitors.csv"
JSON_PATH = OUT / "SITV_COLMAR_2026_exhibitors.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}
BLOCKED = {
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com",
    "sitvcolmar.com", "tripadvisor", "booking.com",
}
TLD_COUNTRIES = {
    "fr": "France", "de": "Germany", "at": "Austria", "ch": "Switzerland",
    "it": "Italy", "be": "Belgium", "es": "Spain", "ca": "Canada",
    "uk": "United Kingdom", "co.uk": "United Kingdom", "mg": "Madagascar",
    "cm": "Cameroon", "ml": "Mali", "tg": "Togo", "ne": "Niger",
}
CSV_FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "name", "desc", "email", "phone", "address", "city", "linkedin_url",
    "hall", "stand", "profile_url", "source_year",
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
    return host if "." in host and not any(blocked in host for blocked in BLOCKED) else ""


def extract_email(text: str) -> str:
    match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text or "")
    return match.group(0) if match else ""


def extract_phone(soup: BeautifulSoup, text: str) -> str:
    tel = soup.select_one('a[href^="tel:"]')
    if tel:
        candidate = clean(tel.get("href", "")[4:])
        if len(re.sub(r"\D", "", candidate)) != 14:
            return candidate
        return ""
    match = re.search(r"(?:\+?\d[\d\s()./-]{7,}\d)", text or "")
    if not match:
        return ""
    candidate = clean(match.group(0))
    digits = re.sub(r"\D", "", candidate)
    if len(digits) == 14 or re.fullmatch(r"(?:19|20)\d{2}(?:[-/](?:19|20)\d{2})?", candidate):
        return ""
    return candidate


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
    countries = {
        "france": "France", "français": "France", "germany": "Germany",
        "deutschland": "Germany", "italy": "Italy", "italie": "Italy",
        "switzerland": "Switzerland", "suisse": "Switzerland",
        "austria": "Austria", "österreich": "Austria",
    }
    for needle, country in countries.items():
        if needle in low:
            return country
    suffix = ".".join(domain_name.rsplit(".", 2)[-2:])
    return TLD_COUNTRIES.get(suffix, TLD_COUNTRIES.get(domain_name.rsplit(".", 1)[-1], "France"))


def parse_cards() -> list[dict[str, str]]:
    session = requests.Session()
    session.headers.update(HEADERS)
    response = session.get(LIST_URL, timeout=45)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    merged: dict[str, dict[str, str]] = {}
    for pane in soup.select("#expoContent > .tab-pane"):
        hall = clean(pane.get("id", "").removeprefix("expo")) or "Unknown"
        cards = pane.select(".row.card-body > .col-md-4")
        rows = pane.select(".row.card-body > .col-md-8")
        for index, card in enumerate(cards):
            name_el = card.select_one('p[class*="h4"]')
            stand_el = card.select_one('p[class*="h6"]')
            name = clean(name_el.get_text(" ", strip=True)) if name_el else ""
            if not name:
                continue
            website = ""
            if index < len(rows):
                link = rows[index].select_one("a[href]")
                website = link.get("href", "") if link else ""
            key = name.casefold()
            row = merged.setdefault(key, {
                "exhibitor_name": name, "domain": normalize_domain(website),
                "contact_number": "", "mail": "", "location": "", "country": "",
                "name": name, "desc": "", "email": "", "phone": "", "address": "",
                "city": "", "linkedin_url": "", "hall": "", "stand": "",
                "profile_url": f"{LIST_URL}#expo{hall}", "source_year": EVENT_YEAR,
            })
            row["hall"] = ", ".join(dict.fromkeys(filter(None, [row["hall"], hall])))
            stand = clean(stand_el.get_text(" ", strip=True)) if stand_el else ""
            row["stand"] = ", ".join(dict.fromkeys(filter(None, [row["stand"], stand])))
            row["domain"] = row["domain"] or normalize_domain(website)
    if not merged:
        raise RuntimeError("No 2026 SITV exhibitors found")
    print(f"Found {len(merged)} unique exhibitors across 4 halls", flush=True)
    return list(merged.values())


def website_contacts(record: dict[str, str]) -> dict[str, str]:
    if not record["domain"]:
        return record
    session = requests.Session()
    session.headers.update(HEADERS)
    base = f"https://{record['domain']}/"
    for suffix in ("", "contact", "contactez-nous", "mentions-legales", "impressum"):
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


def serper_enrich(record: dict[str, str], api_key: str) -> dict[str, str]:
    if not api_key or record["domain"]:
        return record
    session = requests.Session()
    session.headers.update(HEADERS)
    query = f'"{record["exhibitor_name"]}" official website {EVENT_YEAR} France'
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
    return record


def finalize(record: dict[str, str]) -> dict[str, str]:
    record["email"] = record["mail"]
    record["phone"] = record["contact_number"]
    record["address"] = record["address"] or record["location"]
    record["country"] = guess_country(record["location"], record["domain"])
    return record


def scrape() -> list[dict[str, str]]:
    load_dotenv(ROOT.parent / ".env")
    records = parse_cards()
    api_key = os.getenv("SERPER_API_KEY", "")
    with ThreadPoolExecutor(max_workers=10) as pool:
        records = list(pool.map(lambda row: serper_enrich(row, api_key), records))
    with ThreadPoolExecutor(max_workers=16) as pool:
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
