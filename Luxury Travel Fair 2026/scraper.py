"""Scrape the Luxury Travel Fair 2026 exhibitor directory."""

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

BASE_URL = "https://www.luxurytravelfair.com/"
LIST_URL = urljoin(BASE_URL, "exhibitors")
EVENT_NAME = "Luxury Travel Fair"
EVENT_YEAR = "2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
CSV_PATH = OUT / "LUXURY_TRAVEL_FAIR_2026_exhibitors.csv"
JSON_PATH = OUT / "LUXURY_TRAVEL_FAIR_2026_exhibitors.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
BLOCKED = ("linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
           "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com",
           "luxurytravelfair.com")
CSV_FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "name", "desc", "email", "phone", "address", "city", "linkedin_url",
    "profile_url", "source_year",
]
COUNTRY_NAMES = {
    "uk": "United Kingdom", "united kingdom": "United Kingdom", "england": "United Kingdom",
    "india": "India", "brazil": "Brazil", "canada": "Canada", "australia": "Australia",
    "new zealand": "New Zealand", "usa": "United States", "united states": "United States",
    "germany": "Germany", "france": "France", "italy": "Italy", "spain": "Spain",
    "portugal": "Portugal", "croatia": "Croatia", "greece": "Greece", "maldives": "Maldives",
    "nepal": "Nepal", "bhutan": "Bhutan", "sri lanka": "Sri Lanka", "south africa": "South Africa",
    "tanzania": "Tanzania", "kenya": "Kenya", "botswana": "Botswana", "namibia": "Namibia",
    "iceland": "Iceland", "norway": "Norway", "sweden": "Sweden", "finland": "Finland",
    "switzerland": "Switzerland", "austria": "Austria", "netherlands": "Netherlands",
    "belgium": "Belgium", "ireland": "Ireland", "mexico": "Mexico",
}


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def valid_email(value: str) -> str:
    value = clean(value)
    return "" if value.lower() in {"youremail@yourdomain.com", "email@example.com"} else value


def domain(value: str) -> str:
    if not value:
        return ""
    value = value.strip()
    if not re.match(r"^[a-z][a-z0-9+.-]*://", value, re.I):
        value = "https://" + value
    host = urlparse(value).netloc.lower().removeprefix("www.")
    return host if "." in host and not any(x in host for x in BLOCKED) else ""


def text_from_html(fragment: str) -> str:
    return clean(BeautifulSoup(fragment or "", "lxml").get_text(" ", strip=True))


def profile_data(soup: BeautifulSoup) -> dict[str, str]:
    scripts = soup.select('script[type="application/ld+json"]')
    for script in scripts:
        try:
            obj = json.loads(script.string or script.get_text())
            entity = obj.get("mainEntity", {}) if isinstance(obj, dict) else {}
            if entity.get("@type") == "Organization":
                same_as = entity.get("sameAs", [])
                linkedin = next((x for x in same_as if "linkedin.com" in x.lower()), "")
                return {
                    "name": clean(entity.get("name", "")),
                    "desc": text_from_html(entity.get("description", "")),
                    "domain": domain(entity.get("url", "")),
                    "linkedin_url": linkedin,
                }
        except (json.JSONDecodeError, TypeError):
            continue
    return {}


def list_profiles(session: requests.Session) -> list[dict[str, str]]:
    records, seen = [], set()
    for page in range(1, 6):
        url = f"{LIST_URL}?page={page}"
        response = session.get(url, timeout=45)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        for anchor in soup.select('a[href*="exhibitors/"]'):
            href = anchor.get("href", "").split("?")[0]
            name = clean(anchor.get_text(" ", strip=True))
            if not name or not href or href.rstrip("/") == "exhibitors":
                continue
            profile_url = urljoin(BASE_URL, href)
            if profile_url in seen:
                continue
            seen.add(profile_url)
            records.append({"name": name, "profile_url": profile_url})
    if len(records) != 45:
        raise RuntimeError(f"Expected 45 2026 exhibitors, found {len(records)}")
    return records


def guess_country(location: str, domain_name: str = "") -> str:
    low = location.lower()
    for needle, country in COUNTRY_NAMES.items():
        if re.search(rf"\b{re.escape(needle)}\b", low):
            return country
    tld = domain_name.rsplit(".", 1)[-1] if "." in domain_name else ""
    return {"uk": "United Kingdom", "in": "India", "br": "Brazil", "hr": "Croatia",
            "au": "Australia", "nz": "New Zealand", "za": "South Africa"}.get(tld, "")


def serper_enrich(session: requests.Session, record: dict[str, str], api_key: str) -> None:
    if not api_key:
        return
    query = f'"{record["name"]}" official website {EVENT_YEAR}'
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
        record["domain"] = domain(knowledge.get("website", ""))
        if not record["domain"]:
            for item in data.get("organic", []):
                candidate = domain(item.get("link", ""))
                if candidate:
                    record["domain"] = candidate
                    break
    if not record["location"]:
        record["location"] = clean(knowledge.get("address", ""))
    if not record["contact_number"]:
        record["contact_number"] = clean(knowledge.get("phone", ""))
    if not record["desc"]:
        record["desc"] = clean(knowledge.get("description", ""))
    if not record["linkedin_url"]:
        record["linkedin_url"] = next(
            (i.get("link", "") for i in data.get("organic", [])
             if "linkedin.com/company" in i.get("link", "").lower()), "")


def website_contacts(session: requests.Session, record: dict[str, str]) -> None:
    if not record["domain"]:
        return
    base = "https://" + record["domain"] + "/"
    urls = [base, urljoin(base, "contact"), urljoin(base, "contact-us"),
            urljoin(base, "about"), urljoin(base, "about-us")]
    for url in urls:
        try:
            response = session.get(url, timeout=20)
            if response.status_code >= 400:
                continue
        except requests.RequestException:
            continue
        soup = BeautifulSoup(response.text, "lxml")
        body = clean(soup.get_text(" ", strip=True))
        if not record["mail"]:
            m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]{2,}", body)
            if m and "example." not in m.group(0).lower():
                record["mail"] = valid_email(m.group(0))
        if not record["contact_number"]:
            tel = soup.select_one('a[href^="tel:"]')
            if tel:
                record["contact_number"] = clean(tel.get("href", "")[4:])
            else:
                m = re.search(r"(?:\+?\d[\d\s().-]{7,}\d)", body)
                if m:
                    record["contact_number"] = clean(m.group(0))
        if record["contact_number"]:
            parts = record["contact_number"].split()
            half = len(parts) // 2
            if half and len(parts) % 2 == 0 and parts[:half] == parts[half:]:
                record["contact_number"] = " ".join(parts[:half])
        if not record["location"]:
            address = soup.find("address")
            if address:
                record["location"] = clean(address.get_text(" ", strip=True))
        if record["mail"] and record["contact_number"] and record["location"]:
            break


def scrape() -> list[dict[str, str]]:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    session = requests.Session()
    session.headers.update(HEADERS)
    records = list_profiles(session)
    for index, base in enumerate(records, 1):
        try:
            response = session.get(base["profile_url"], timeout=45)
            response.raise_for_status()
            data = profile_data(BeautifulSoup(response.text, "lxml"))
        except requests.RequestException:
            data = {}
        record = {
            "exhibitor_name": data.get("name") or base["name"],
            "domain": data.get("domain", ""),
            "contact_number": "", "mail": "", "location": "", "country": "",
            "name": data.get("name") or base["name"], "desc": data.get("desc", ""),
            "email": "", "phone": "", "address": "", "city": "",
            "linkedin_url": data.get("linkedin_url", ""),
            "profile_url": base["profile_url"], "source_year": EVENT_YEAR,
        }
        serper_enrich(session, record, os.getenv("SERPER_API_KEY", ""))
        website_contacts(session, record)
        record["email"] = record["mail"]
        record["phone"] = record["contact_number"]
        record["address"] = record["location"]
        record["country"] = guess_country(record["location"], record["domain"])
        if record["location"] and not record["country"]:
            record["country"] = clean(record["location"].split(",")[-1])
        records[index - 1] = record
        print(f"{index}/{len(records)} {record['exhibitor_name']}", flush=True)
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
