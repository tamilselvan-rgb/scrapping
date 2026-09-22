"""Scrape the Finance Professional Show 2026 exhibitor directory."""

from __future__ import annotations

import csv
import html
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

BASE_URL = "https://financeprofessionalshow.co.uk/"
LIST_URL = urljoin(BASE_URL, "exhibitors/")
EVENT_NAME = "Finance Professional Show"
EVENT_YEAR = "2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
CSV_PATH = OUT / "FINANCE_PROFESSIONAL_SHOW_2026_exhibitors.csv"
JSON_PATH = OUT / "FINANCE_PROFESSIONAL_SHOW_2026_exhibitors.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
BLOCKED = (
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com",
    "financeprofessionalshow.co.uk",
)
CSV_FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "name", "desc", "email", "phone", "address", "city", "linkedin_url",
    "stand", "profile_url", "source_year",
]
COUNTRIES = {
    "uk": "United Kingdom", "united kingdom": "United Kingdom", "england": "United Kingdom",
    "india": "India", "united states": "United States", "usa": "United States",
    "germany": "Germany", "france": "France", "italy": "Italy", "spain": "Spain",
    "ireland": "Ireland", "scotland": "United Kingdom", "wales": "United Kingdom",
    "netherlands": "Netherlands", "belgium": "Belgium", "austria": "Austria",
    "switzerland": "Switzerland", "canada": "Canada", "australia": "Australia",
}
TLD_COUNTRIES = {
    "uk": "United Kingdom", "co.uk": "United Kingdom", "in": "India",
    "de": "Germany", "fr": "France", "it": "Italy", "es": "Spain",
    "ie": "Ireland", "nl": "Netherlands", "be": "Belgium", "at": "Austria",
    "ch": "Switzerland", "ca": "Canada", "au": "Australia",
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
    return host if "." in host and not any(item in host for item in BLOCKED) else ""


def extract_email(text: str) -> str:
    match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text or "")
    return match.group(0) if match else ""


def jsonld_address(soup: BeautifulSoup) -> str:
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            address = item.get("address")
            if isinstance(address, dict):
                parts = [
                    address.get("streetAddress", ""),
                    address.get("addressLocality", ""),
                    address.get("addressRegion", ""),
                    address.get("postalCode", ""),
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
    for needle, country in COUNTRIES.items():
        if re.search(rf"\b{re.escape(needle)}\b", low):
            return country
    parts = domain_name.rsplit(".", 2)
    suffix = ".".join(parts[-2:]) if len(parts) >= 2 else ""
    return TLD_COUNTRIES.get(suffix, TLD_COUNTRIES.get(parts[-1], ""))


def parse_ajax_config(page_html: str) -> dict[str, str]:
    match = re.search(r"var exhibitorDirectoryAjax\s*=\s*(\{.*?\});", page_html)
    if not match:
        raise RuntimeError("Could not find the exhibitor AJAX configuration")
    return json.loads(match.group(1))


def list_exhibitors(session: requests.Session) -> tuple[list[dict[str, str]], dict[str, str]]:
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    ajax_config: dict[str, str] = {}
    for page in range(1, 11):
        url = LIST_URL if page == 1 else urljoin(BASE_URL, f"exhibitors/page/{page}/")
        response = session.get(url, timeout=45)
        if response.status_code == 404:
            break
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        if not ajax_config:
            ajax_config = parse_ajax_config(response.text)
        cards = soup.select(".exhibitor-card[data-post-id]")
        if not cards:
            break
        for card in cards:
            post_id = clean(card.get("data-post-id", ""))
            title = card.select_one(".exhibitor-card__title")
            name = clean(title.get_text(" ", strip=True)) if title else ""
            if post_id and name and post_id not in seen:
                seen.add(post_id)
                records.append({
                    "name": name,
                    "post_id": post_id,
                    "list_url": url,
                })
    if not records:
        raise RuntimeError("No exhibitors found on the 2026 exhibitor list")
    return records, ajax_config


def fetch_profile(session: requests.Session, ajax: dict[str, str], item: dict[str, str]) -> dict[str, str]:
    response = session.post(
        ajax["ajaxUrl"],
        data={
            "action": "get_exhibitor_data",
            "post_id": item["post_id"],
            "_ajax_nonce": ajax["nonce"],
        },
        timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if payload.get("success") else {}
    data = data if isinstance(data, dict) else {}
    website = clean(data.get("website", ""))
    return {
        "exhibitor_name": clean(data.get("title", "")) or item["name"],
        "domain": normalize_domain(website),
        "contact_number": clean(data.get("phone", "")).removeprefix("tel:").strip(),
        "mail": clean(data.get("email", "")),
        "location": "",
        "country": "",
        "name": clean(data.get("title", "")) or item["name"],
        "desc": "",
        "email": clean(data.get("email", "")),
        "phone": clean(data.get("phone", "")).removeprefix("tel:").strip(),
        "address": "",
        "city": "",
        "linkedin_url": "",
        "stand": clean(data.get("stand", "")),
        "profile_url": f"{item['list_url']}#exhibitor-{item['post_id']}",
        "source_year": EVENT_YEAR,
    }


def serper_enrich(session: requests.Session, record: dict[str, str], api_key: str) -> None:
    if not api_key:
        return
    query = f'"{record["exhibitor_name"]}" official website {EVENT_YEAR} {record.get("location", "")}'
    try:
        response = session.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": 10},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return
    knowledge = data.get("knowledgeGraph") or {}
    if not record["domain"]:
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
    if not record["desc"]:
        record["desc"] = clean(knowledge.get("description", ""))
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
    for suffix in ("", "contact", "contact-us"):
        try:
            response = session.get(urljoin(base, suffix), timeout=10)
            if response.status_code >= 400:
                continue
        except requests.RequestException:
            continue
        soup = BeautifulSoup(response.text, "lxml")
        body = clean(soup.get_text(" ", strip=True))
        if not record["mail"]:
            record["mail"] = extract_email(body)
        if not record["contact_number"]:
            tel = soup.select_one('a[href^="tel:"]')
            record["contact_number"] = clean(tel.get("href", "")[4:]) if tel else ""
        if not record["location"]:
            address = soup.find("address")
            if address:
                record["location"] = clean(address.get_text(" ", strip=True))
            if not record["location"]:
                record["location"] = jsonld_address(soup)
        if record["mail"] and record["contact_number"] and record["location"]:
            break


def scrape() -> list[dict[str, str]]:
    load_dotenv(ROOT.parent / ".env")
    session = requests.Session()
    session.headers.update(HEADERS)
    items, ajax = list_exhibitors(session)
    records: list[dict[str, str]] = []
    api_key = os.getenv("SERPER_API_KEY", "")
    print(f"Found {len(items)} Finance Professional Show 2026 exhibitors", flush=True)
    for index, item in enumerate(items, 1):
        try:
            record = fetch_profile(session, ajax, item)
        except (requests.RequestException, ValueError, RuntimeError):
            record = {
                "exhibitor_name": item["name"], "domain": "", "contact_number": "",
                "mail": "", "location": "", "country": "", "name": item["name"],
                "desc": "", "email": "", "phone": "", "address": "", "city": "",
                "linkedin_url": "", "stand": "", "profile_url": item["list_url"],
                "source_year": EVENT_YEAR,
            }
        if not record["domain"] or not record["location"]:
            serper_enrich(session, record, api_key)
            # Serper can discover a domain; inspect that official site for
            # structured address/contact data before writing the row.
            website_contacts(session, record)
        record["email"] = record["mail"]
        record["phone"] = record["contact_number"]
        record["address"] = record["location"]
        record["country"] = guess_country(record["location"], record["domain"]) or "United Kingdom"
        records.append(record)
        print(f"{index}/{len(items)} {record['exhibitor_name']}", flush=True)
    return sorted(records, key=lambda row: row["exhibitor_name"].casefold())


def write_outputs(records: list[dict[str, str]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "event": EVENT_NAME,
        "year": EVENT_YEAR,
        "source": LIST_URL,
        "scraped_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(records),
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
