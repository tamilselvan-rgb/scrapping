"""Scrape the RENT Paris 2026 exhibitor directory."""

from __future__ import annotations

import csv
import html
import json
import os
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

BASE_URL = "https://www.rent.immo/e/rent-paris-2026/fr/"
LIST_URL = urljoin(BASE_URL, "content/exposants")
EVENT_NAME = "RENT"
EVENT_YEAR = "2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
CSV_PATH = OUT / "RENT_2026_exhibitors.csv"
JSON_PATH = OUT / "RENT_2026_exhibitors.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}
BLOCKED = (
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com", "rent.immo",
    "planexpo.fr", "inwink.com", "proptechexpo.es", "realnewtech.com",
    "gplanner.com", "immotech.ma", "rem-events.ch",
)
CSV_FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "name", "desc", "email", "phone", "address", "city", "linkedin_url",
    "stand", "profile_url", "source_year",
]
TLD_COUNTRIES = {
    "fr": "France", "be": "Belgium", "ch": "Switzerland", "lu": "Luxembourg",
    "de": "Germany", "es": "Spain", "it": "Italy", "uk": "United Kingdom",
    "co.uk": "United Kingdom", "nl": "Netherlands", "ca": "Canada",
}


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def normalize_domain(value: str) -> str:
    value = clean(value)
    if not value:
        return ""
    if value.casefold().startswith(("mailto:", "tel:", "javascript:")):
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", value, re.I):
        value = "https://" + value
    host = urlparse(value).netloc.lower().removeprefix("www.")
    return host if "." in host and not any(item in host for item in BLOCKED) else ""


def extract_email(text: str) -> str:
    match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text or "")
    return match.group(0) if match else ""


def extract_phone(soup: BeautifulSoup, text: str) -> str:
    tel = soup.select_one('a[href^="tel:"]')
    if tel:
        return clean(tel.get("href", "")[4:])
    match = re.search(r"(?:\+?\d[\d\s()./-]{7,}\d)", text or "")
    if not match:
        return ""
    candidate = clean(match.group(0))
    if len(re.sub(r"\D", "", candidate)) == 14:
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


def parse_state(text: str) -> dict:
    prefix = 'window.INITIAL_STATE = JSON.parse(decodeURIComponent("'
    start = text.index(prefix) + len(prefix)
    end = text.index('"))', start)
    return json.loads(urllib.parse.unquote(text[start:end]))


def profile_url_from_anchor(href: str) -> str:
    return urljoin("https://www.rent.immo", href.split("?")[0])


def list_exhibitors(session: requests.Session) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for page in range(10):
        # Inwink uses zero-based pages: the first page is also returned for
        # ?page=1, so request pages 0, 2 ... 10 for the remaining batches.
        url = LIST_URL if page == 0 else f"{LIST_URL}?page={page + 1}"
        response = session.get(url, timeout=60)
        response.raise_for_status()
        state = parse_state(response.text)
        search = state["pages"]["companion.contentpage.exposants"]["data"]["exhibitorsearch"]
        items = search.get("items", [])
        links = [
            profile_url_from_anchor(anchor.get("href", ""))
            for anchor in BeautifulSoup(response.text, "lxml").select('a[href*="/partner/"]')
            if "/partner/" in anchor.get("href", "")
        ]
        for index, item in enumerate(items):
            exhibitor_id = item.get("id", "")
            profile_url = links[index] if index < len(links) else ""
            if not exhibitor_id or not profile_url or exhibitor_id in seen:
                continue
            seen.add(exhibitor_id)
            description = item.get("description", "")
            if isinstance(description, dict):
                description = description.get("fr") or description.get("en") or ""
            records.append({
                "id": exhibitor_id,
                "name": clean(item.get("name") or item.get("planexpo_companyname", "")),
                "domain": normalize_domain(item.get("website", "")),
                "desc": clean(description),
                "stand": clean(item.get("standnumber", "")),
                "profile_url": profile_url,
            })
    if len(records) != 287:
        raise RuntimeError(f"Expected 287 RENT 2026 exhibitors, found {len(records)}")
    return records


def parse_profile(text: str, record: dict[str, str]) -> dict[str, str]:
    soup = BeautifulSoup(text, "lxml")
    try:
        state = parse_state(text)
        entity = state["pages"]["companion.page.exhibitordetail"]["context"]["entity"]
        record["name"] = clean(entity.get("name", "")) or record["name"]
        record["stand"] = clean(entity.get("standnumber", "")) or record["stand"]
        website = normalize_domain(entity.get("website", ""))
        record["domain"] = record["domain"] or website
        description = entity.get("description", "")
        if isinstance(description, dict):
            record["desc"] = record["desc"] or clean(description.get("fr") or description.get("en", ""))
    except (KeyError, TypeError, ValueError):
        pass
    body = soup.select_one("main") or soup.body
    body_text = clean(body.get_text(" ", strip=True) if body else "")
    links = [anchor.get("href", "") for anchor in (body.select("a[href]") if body else [])]
    for link in links:
        candidate = normalize_domain(link)
        if candidate:
            record["domain"] = record["domain"] or candidate
    record["mail"] = extract_email(body_text)
    record["contact_number"] = extract_phone(body or soup, body_text)
    record["address"] = jsonld_address(soup)
    record["location"] = record["address"]
    record["country"] = guess_country(record["location"], record["domain"])
    record["name"] = record["name"] or clean(soup.title.get_text() if soup.title else "")
    return record


def fetch_profile(item: dict[str, str]) -> dict[str, str]:
    session = requests.Session()
    session.headers.update(HEADERS)
    response = session.get(item["profile_url"], timeout=60)
    response.raise_for_status()
    record = {
        "exhibitor_name": item["name"], "domain": item["domain"],
        "contact_number": "", "mail": "", "location": "", "country": "",
        "name": item["name"], "desc": item["desc"], "email": "", "phone": "",
        "address": "", "city": "", "linkedin_url": "", "stand": item["stand"],
        "profile_url": item["profile_url"], "source_year": EVENT_YEAR,
    }
    return parse_profile(response.text, record)


def guess_country(location: str, domain_name: str) -> str:
    low = location.casefold()
    if "france" in low or "français" in low:
        return "France"
    suffix = ".".join(domain_name.rsplit(".", 2)[-2:])
    return TLD_COUNTRIES.get(suffix, TLD_COUNTRIES.get(domain_name.rsplit(".", 1)[-1], "France"))


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
    if not record["mail"]:
        record["mail"] = extract_email(clean(knowledge.get("description", "")))
    return record


def website_contacts(record: dict[str, str]) -> dict[str, str]:
    if not record["domain"]:
        return record
    session = requests.Session()
    session.headers.update(HEADERS)
    base = f"https://{record['domain']}/"
    for suffix in ("", "contact", "contact-us", "mentions-legales", "about"):
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
    items = list_exhibitors(session)
    print(f"Found {len(items)} RENT Paris 2026 exhibitors", flush=True)
    records: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(fetch_profile, item) for item in items]
        for count, future in enumerate(as_completed(futures), 1):
            try:
                records.append(future.result())
            except requests.RequestException as exc:
                print(f"Profile failed: {exc}", flush=True)
            print(f"Profiles scraped: {count}/{len(futures)}", flush=True)
    api_key = os.getenv("SERPER_API_KEY", "")
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(serper_enrich, record, api_key) for record in records]
        records = [future.result() for future in as_completed(futures)]
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(website_contacts, record) for record in records]
        records = [finalize(future.result()) for future in as_completed(futures)]
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
