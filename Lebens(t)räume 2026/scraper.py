"""Scrape the Lebens(t)räume 2026 exhibitor directory."""

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

BASE_URL = "https://www.lebenstraeume-grafschaft.de/"
LIST_URL = urljoin(BASE_URL, "aussteller/")
EVENT_NAME = "Lebens(t)räume"
EVENT_YEAR = "2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
CSV_PATH = OUT / "LEBENSTRAEUME_2026_exhibitors.csv"
JSON_PATH = OUT / "LEBENSTRAEUME_2026_exhibitors.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}
BLOCKED = (
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com",
    "lebenstraeume-grafschaft.de",
)
CSV_FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "name", "desc", "email", "phone", "address", "city", "linkedin_url",
    "profile_url", "source_year",
]
COUNTRIES = {
    "deutschland": "Germany", "germany": "Germany", "österreich": "Austria",
    "austria": "Austria", "schweiz": "Switzerland", "switzerland": "Switzerland",
    "niederlande": "Netherlands", "netherlands": "Netherlands",
    "belgien": "Belgium", "belgium": "Belgium", "frankreich": "France",
    "france": "France", "uk": "United Kingdom", "united kingdom": "United Kingdom",
}
TLD_COUNTRIES = {
    "de": "Germany", "at": "Austria", "ch": "Switzerland", "nl": "Netherlands",
    "be": "Belgium", "fr": "France", "uk": "United Kingdom", "co.uk": "United Kingdom",
}


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def normalize_domain(value: str) -> str:
    value = clean(value)
    if not value:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", value, re.I):
        value = "https://" + value
    host = urlparse(value).netloc.lower().removeprefix("www.")
    return host if "." in host and not any(blocked in host for blocked in BLOCKED) else ""


def extract_email(text: str) -> str:
    match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text or "")
    return match.group(0) if match else ""


def extract_phone(soup: BeautifulSoup, text: str) -> str:
    tel = soup.select_one('a[href^="tel:"]')
    if tel:
        return clean(tel.get("href", "")[4:])
    match = re.search(r"(?:\+?\d[\d\s()/.-]{7,}\d)", text or "")
    return clean(match.group(0)) if match else ""


def jsonld_address(soup: BeautifulSoup) -> str:
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
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
            if isinstance(address, str) and clean(address):
                return clean(address)
    return ""


def guess_country(location: str, domain_name: str) -> str:
    low = location.casefold()
    for needle, country in COUNTRIES.items():
        if re.search(rf"\b{re.escape(needle)}\b", low):
            return country
    suffix = ".".join(domain_name.rsplit(".", 2)[-2:])
    return TLD_COUNTRIES.get(suffix, TLD_COUNTRIES.get(domain_name.rsplit(".", 1)[-1], ""))


def list_exhibitors(session: requests.Session) -> list[dict[str, str]]:
    response = session.get(LIST_URL, timeout=45)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    records = []
    seen = set()
    for card in soup.select(".client-card[data-permalink]"):
        profile_url = card.get("data-permalink", "").split("#")[0]
        title = card.select_one("h5")
        name = clean(title.get_text(" ", strip=True)) if title else ""
        if profile_url and name and profile_url not in seen:
            seen.add(profile_url)
            records.append({"name": name, "profile_url": profile_url})
    if not records:
        raise RuntimeError("No 2026 exhibitors found on the listing page")
    return records


def parse_profile(html_text: str, base: dict[str, str]) -> dict[str, str]:
    soup = BeautifulSoup(html_text, "lxml")
    content = soup.select_one("main.entry-content") or soup.select_one(".entry-content")
    title = soup.select_one(".single-post-headline") or soup.select_one("h1")
    name = clean(title.get_text(" ", strip=True)) if title else base["name"]
    paragraphs = []
    website = ""
    linkedin = ""
    if content:
        for anchor in content.select("a[href]"):
            href = anchor.get("href", "")
            if "linkedin.com" in href.lower():
                linkedin = href.split("?")[0]
            candidate = normalize_domain(href)
            if candidate:
                website = href
        for paragraph in content.find_all("p"):
            text = clean(paragraph.get_text(" ", strip=True))
            if text and not paragraph.find("a", href=True):
                paragraphs.append(text)
    desc = " ".join(paragraphs)
    body = clean(content.get_text(" ", strip=True) if content else "")
    email = extract_email(body)
    phone = extract_phone(content or soup, body)
    return {
        "exhibitor_name": name, "domain": normalize_domain(website),
        "contact_number": phone, "mail": email, "location": "",
        "country": "", "name": name, "desc": desc, "email": email, "phone": phone,
        "address": "", "city": "", "linkedin_url": linkedin,
        "profile_url": base["profile_url"], "source_year": EVENT_YEAR,
    }


def fetch_profile(session: requests.Session, item: dict[str, str]) -> dict[str, str]:
    response = session.get(item["profile_url"], timeout=45)
    response.raise_for_status()
    return parse_profile(response.text, item)


def serper_enrich(session: requests.Session, record: dict[str, str], api_key: str) -> None:
    if not api_key or record["domain"]:
        return
    query = f'"{record["exhibitor_name"]}" official website {EVENT_YEAR} {record["location"]}'
    try:
        response = session.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": 10}, timeout=30,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return
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
    if not record["contact_number"]:
        record["contact_number"] = clean(knowledge.get("phone", ""))
    if not record["mail"]:
        record["mail"] = extract_email(clean(knowledge.get("description", "")))
    if not record["linkedin_url"]:
        record["linkedin_url"] = next(
            (item.get("link", "").split("?")[0] for item in data.get("organic", [])
             if "linkedin.com/" in item.get("link", "").lower()), ""
        )


def website_contacts(session: requests.Session, record: dict[str, str]) -> None:
    if not record["domain"]:
        return
    base = f"https://{record['domain']}/"
    for suffix in ("", "kontakt", "impressum"):
        try:
            response = session.get(urljoin(base, suffix), timeout=15)
            if response.status_code >= 400:
                continue
        except requests.RequestException:
            continue
        soup = BeautifulSoup(response.text, "lxml")
        body = clean(soup.get_text(" ", strip=True))
        if not record["mail"]:
            record["mail"] = extract_email(body)
        if not record["contact_number"]:
            record["contact_number"] = extract_phone(soup, body)
            address = jsonld_address(soup)
            if address and (not record["location"] or re.search(r"\d", address)):
                record["location"] = address
        if record["mail"] and record["contact_number"] and record["location"]:
            break


def scrape() -> list[dict[str, str]]:
    load_dotenv(ROOT.parent / ".env")
    session = requests.Session()
    session.headers.update(HEADERS)
    items = list_exhibitors(session)
    print(f"Found {len(items)} Lebens(t)räume 2026 exhibitors", flush=True)
    records = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch_profile, session, item) for item in items]
        for index, future in enumerate(as_completed(futures), 1):
            try:
                records.append(future.result())
            except requests.RequestException as exc:
                print(f"Profile failed: {exc}", flush=True)
            print(f"Profiles scraped: {index}/{len(futures)}", flush=True)
    api_key = os.getenv("SERPER_API_KEY", "")
    for index, record in enumerate(records, 1):
        serper_enrich(session, record, api_key)
        website_contacts(session, record)
        record["email"] = record["mail"]
        record["phone"] = record["contact_number"]
        record["address"] = record["location"]
        record["country"] = guess_country(record["location"], record["domain"]) or "Germany"
        print(f"Enriched: {index}/{len(records)} {record['exhibitor_name']}", flush=True)
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
