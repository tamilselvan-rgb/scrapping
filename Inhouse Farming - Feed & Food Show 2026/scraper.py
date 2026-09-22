"""Scrape the Inhouse Farming - Feed & Food Show 2026 exhibitor marketplace."""

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

BASE_URL = "https://digital.eurotier.com/"
LIST_URL = urljoin(BASE_URL, "marketplace/exhibitors")
API_URL = urljoin(BASE_URL, "api/v1/search/exhibitors")
EVENT_NAME = "Inhouse Farming - Feed & Food Show"
EVENT_YEAR = "2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
CSV_PATH = OUT / "INHOUSE_FARMING_FEED_FOOD_SHOW_2026_exhibitors.csv"
JSON_PATH = OUT / "INHOUSE_FARMING_FEED_FOOD_SHOW_2026_exhibitors.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
}
BLOCKED = (
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com",
    "digital.eurotier.com", "eurotier.com", "dlg.org", "expoplatform.com",
    "google.com", "bing.com", "cloudfront.net", "api-dlgservice",
    "tracxn.com", "volza.com", "ingredientsnetwork.com", "agriexpo.online",
    "rocketreach.co", "northdata.com", "eximpedia.app", "expolista.com",
    "dlg-markets.com", "digital.agritechnica.com",
    "northdata.de", "dnb.com", "scribd.com", "made-in-china.com",
    "emis.com", "compabase.com", "sciencedirect.com", "cphi-online.com",
    "trademagellan.com", "creditsafe.com", "pmc.ncbi.nlm.nih.gov",
    "jobv.eu", "gowork.pl", "leadiq.com", "bouncewatch.com",
    "dictionary.cambridge.org",
)
TLD_COUNTRIES = {
    "de": "Germany", "at": "Austria", "ch": "Switzerland", "nl": "Netherlands",
    "fr": "France", "it": "Italy", "es": "Spain", "be": "Belgium",
    "dk": "Denmark", "se": "Sweden", "no": "Norway", "fi": "Finland",
    "uk": "United Kingdom", "co.uk": "United Kingdom", "ie": "Ireland",
    "hu": "Hungary",
    "us": "United States", "ca": "Canada", "au": "Australia",
}
CSV_FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "name", "desc", "email", "phone", "address", "city", "linkedin_url",
    "stand", "profile_url", "source_year",
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
        return candidate if valid_phone(candidate) else ""
    match = re.search(r"(?:\+?\d[\d\s()./-]{7,}\d)", text or "")
    candidate = clean(match.group(0)) if match else ""
    return candidate if valid_phone(candidate) else ""


def valid_phone(value: str) -> bool:
    if not value or re.search(r"[a-z]", value, re.I):
        return False
    if re.search(r"\b\d{1,2}[.-]\d{1,2}[.-]\d{4}\b", value):
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


def guess_country(location: str, domain_name: str, fallback: str = "") -> str:
    low = location.casefold()
    for needle, country in {
        "germany": "Germany", "deutschland": "Germany", "france": "France",
        "frankreich": "France", "netherlands": "Netherlands", "niederlande": "Netherlands",
        "austria": "Austria", "österreich": "Austria", "switzerland": "Switzerland",
        "schweiz": "Switzerland",
    }.items():
        if needle in low:
            return country
    suffix = ".".join(domain_name.rsplit(".", 2)[-2:])
    return TLD_COUNTRIES.get(suffix, TLD_COUNTRIES.get(domain_name.rsplit(".", 1)[-1], fallback))


def stand_text(item: dict) -> str:
    values = []
    for group in item.get("stands") or []:
        hall = clean(group.get("hall", ""))
        for stand in group.get("stands") or []:
            value = clean(stand.get("name", ""))
            if hall and value:
                value = f"{hall}/{value}"
            values.append(value)
    return ", ".join(dict.fromkeys(filter(None, values)))


def list_exhibitors(session: requests.Session) -> list[dict[str, str]]:
    first = session.post(API_URL, json={"page": 1, "limit": 60, "full": True}, timeout=60)
    first.raise_for_status()
    first_data = first.json()["data"]
    total = int(first_data["total"])
    pages = (total + 59) // 60
    records: list[dict] = []

    def load_page(page: int) -> list[dict]:
        response = session.post(
            API_URL, json={"page": page, "limit": 60, "full": True}, timeout=60,
        )
        response.raise_for_status()
        return response.json()["data"]["list"]

    pages_data = [first_data["list"]]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(load_page, page) for page in range(2, pages + 1)]
        pages_data.extend(future.result() for future in as_completed(futures))
    for items in pages_data:
        for item in items:
            name = clean(item.get("name", ""))
            slug = clean(item.get("url", ""))
            if not name or not slug:
                continue
            records.append({
                "exhibitor_name": name,
                "domain": normalize_domain(item.get("website", "")),
                "contact_number": "", "mail": "",
                "location": ", ".join(filter(None, [
                    clean(item.get("city", "")), clean(item.get("region", "")),
                    clean(item.get("country", "")),
                ])),
                "country": clean(item.get("country", "")),
                "name": name,
                "desc": clean(item.get("about", "")),
                "email": "", "phone": "", "address": "", "city": clean(item.get("city", "")),
                "linkedin_url": "", "stand": stand_text(item),
                "profile_url": urljoin(BASE_URL, f"exhibitor/{slug}"),
                "source_year": EVENT_YEAR,
            })
    unique = {row["profile_url"]: row for row in records}
    if len(unique) != total:
        raise RuntimeError(f"Expected {total} exhibitors, found {len(unique)}")
    print(f"Found {len(unique)} exhibitors across {pages} pages", flush=True)
    return list(unique.values())


def fetch_profile(record: dict[str, str]) -> dict[str, str]:
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        response = session.get(record["profile_url"], timeout=60)
        response.raise_for_status()
    except requests.RequestException:
        return record
    soup = BeautifulSoup(response.text, "lxml")
    website = next(
        (normalize_domain(anchor.get("href", "")) for anchor in soup.select("a[href]")
         if normalize_domain(anchor.get("href", ""))),
        "",
    )
    record["domain"] = record["domain"] or website
    email = soup.select_one('a[href^="mailto:"]')
    record["mail"] = record["mail"] or (
        clean(email.get("href", "")[7:]) if email else extract_email(response.text)
    )
    record["contact_number"] = record["contact_number"] or extract_phone(
        soup, clean(soup.get_text(" ", strip=True))
    )
    address_parts = [
        clean(soup.select_one('[data-styleid="product-subtitle1"]').get_text(" ", strip=True))
        if soup.select_one('[data-styleid="product-subtitle1"]') else "",
        clean(soup.select_one('[data-styleid="product-subtitle2"]').get_text(" ", strip=True))
        if soup.select_one('[data-styleid="product-subtitle2"]') else "",
        clean(soup.select_one('[data-styleid="product-subtitle3"]').get_text(" ", strip=True))
        if soup.select_one('[data-styleid="product-subtitle3"]') else "",
    ]
    if any(address_parts):
        record["location"] = ", ".join(filter(None, address_parts))
        record["address"] = record["location"]
    record["desc"] = record["desc"] or clean(
        soup.select_one('[data-styleid="exhibitor-description"]').get_text(" ", strip=True)
        if soup.select_one('[data-styleid="exhibitor-description"]') else ""
    )
    return record


def serper_enrich(record: dict[str, str], api_key: str) -> dict[str, str]:
    if not api_key or record["domain"]:
        return record
    session = requests.Session()
    session.headers.update(HEADERS)
    query = f'"{record["exhibitor_name"]}" official website {EVENT_YEAR} {record["country"]}'
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


def website_contacts(record: dict[str, str]) -> dict[str, str]:
    if not record["domain"]:
        return record
    session = requests.Session()
    session.headers.update(HEADERS)
    base = f"https://{record['domain']}/"
    for suffix in ("", "contact", "contact-us", "impressum", "about"):
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
    record["country"] = guess_country(record["location"], record["domain"], record["country"])
    return record


def scrape() -> list[dict[str, str]]:
    load_dotenv(ROOT.parent / ".env")
    session = requests.Session()
    session.headers.update(HEADERS)
    records = list_exhibitors(session)
    with ThreadPoolExecutor(max_workers=20) as pool:
        records = list(pool.map(fetch_profile, records))
    api_key = os.getenv("SERPER_API_KEY", "")
    missing = [record for record in records if not record["domain"]]
    print(f"Profiles visited: {len(records)}; domains requiring fallback: {len(missing)}", flush=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        enriched = list(pool.map(lambda row: serper_enrich(row, api_key), missing))
    by_url = {row["profile_url"]: row for row in enriched}
    records = [by_url.get(row["profile_url"], row) for row in records]
    with ThreadPoolExecutor(max_workers=20) as pool:
        records = [finalize(row) for row in pool.map(website_contacts, records)]
    return sorted(records, key=lambda row: row["exhibitor_name"].casefold())


def write_outputs(records: list[dict[str, str]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "event": EVENT_NAME, "year": EVENT_YEAR, "source": LIST_URL,
        "total": len(records),
        "scraped_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "exhibitors": records,
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
