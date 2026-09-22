"""Scrape the RISK Expo Europe 2026 exhibitor directory."""

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
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from tldextract import extract as extract_domain

EVENT_NAME = "RISK Expo Europe"
EVENT_YEAR = "2026"
LIST_URL = (
    "https://www.grcworldforums.com/risk/risk-expo-europe/"
    "exhibit/risk-europe-exhibitors"
)
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
CSV_PATH = OUT / "RISK_EXPO_EUROPE_2026_exhibitors.csv"
JSON_PATH = OUT / "RISK_EXPO_EUROPE_2026_exhibitors.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
BLOCKED_DOMAINS = (
    "grcworldforums.com", "linkedin.com", "facebook.com", "instagram.com",
    "twitter.com", "x.com", "youtube.com", "wikipedia.org", "yellowpages.com",
    "yelp.com", "10times.com", "dnb.com", "kompass.com", "zoominfo.com",
    "crunchbase.com", "leadiq.com", "builtin.com", "outlook.com", "site.com",
)
CSV_FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "description", "profile_url", "published_at", "source_year",
]


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def valid_email(value: str) -> str:
    value = clean(value).lower().removeprefix("mailto:")
    if not value or "example." in value or "yourdomain" in value:
        return ""
    return value


def valid_phone(value: str) -> str:
    value = clean(value)
    digits = re.sub(r"\D", "", value)
    if not 8 <= len(digits) <= 15:
        return ""
    if re.search(r"\b(?:19|20)\d{2}\b", value):
        return ""
    if re.search(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", value):
        return ""
    return value


def get_domain(value: str) -> str:
    value = clean(value)
    if not value:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", value, re.I):
        value = "https://" + value
    host = urlparse(value).netloc.lower().removeprefix("www.").split(":")[0]
    if "." not in host or any(blocked in host for blocked in BLOCKED_DOMAINS):
        return ""
    extracted = extract_domain(host)
    return extracted.top_domain_under_public_suffix or extracted.registered_domain or host


def normalize_url(value: str) -> str:
    value = clean(value)
    if not value:
        return ""
    return value if re.match(r"^[a-z][a-z0-9+.-]*://", value, re.I) else f"https://{value}"


def country_from(location: str, domain_name: str) -> str:
    text = location.casefold()
    countries = {
        "united kingdom": "United Kingdom", "england": "United Kingdom",
        "germany": "Germany", "deutschland": "Germany",
        "united states": "United States", "usa": "United States",
        "canada": "Canada", "australia": "Australia", "france": "France",
        "netherlands": "Netherlands", "nederland": "Netherlands",
        "ireland": "Ireland", "switzerland": "Switzerland", "austria": "Austria",
        "belgium": "Belgium", "spain": "Spain", "italy": "Italy",
        "denmark": "Denmark", "norway": "Norway", "sweden": "Sweden",
        "finland": "Finland", "poland": "Poland", "india": "India",
        " us": "United States", " usa": "United States", " gb": "United Kingdom",
        " uk": "United Kingdom", " de": "Germany", " es": "Spain",
        " au": "Australia", " je": "Jersey",
    }
    for needle, country in countries.items():
        if re.search(rf"\b{re.escape(needle)}\b", text):
            return country
    tld = domain_name.rsplit(".", 1)[-1] if "." in domain_name else ""
    return {
        "uk": "United Kingdom", "de": "Germany", "us": "United States",
        "ca": "Canada", "au": "Australia", "fr": "France", "nl": "Netherlands",
        "ie": "Ireland", "ch": "Switzerland", "at": "Austria", "be": "Belgium",
        "es": "Spain", "it": "Italy", "dk": "Denmark", "no": "Norway",
        "se": "Sweden", "fi": "Finland", "pl": "Poland", "in": "India",
    }.get(tld, "")


def extract_jsonld_address(soup: BeautifulSoup) -> str:
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if not isinstance(item, dict):
                continue
            address = item.get("address")
            if not isinstance(address, dict):
                continue
            result = ", ".join(
                clean(address.get(key))
                for key in (
                    "streetAddress", "postalCode", "addressLocality",
                    "addressRegion", "addressCountry",
                )
                if clean(address.get(key))
            )
            if result:
                return result
    return ""


def website_contacts(session: requests.Session, record: dict[str, str]) -> None:
    if not record["domain"]:
        return
    base = normalize_url(record["homepage"]) or f"https://{record['domain']}/"
    for path in ("", "contact", "contact-us", "about", "about-us", "imprint", "privacy"):
        try:
            response = session.get(
                base.rstrip("/") + (f"/{path}" if path else ""),
                timeout=20,
                allow_redirects=True,
            )
            if response.status_code >= 400:
                continue
        except requests.RequestException:
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        visible = clean(soup.get_text(" ", strip=True))
        if not record["mail"]:
            for anchor in soup.select('a[href^="mailto:"]'):
                record["mail"] = valid_email(
                    anchor.get("href", "")[7:].split("?", 1)[0]
                )
                if record["mail"]:
                    break
        if not record["mail"]:
            for email in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", visible):
                record["mail"] = valid_email(email)
                if record["mail"]:
                    break
        if not record["contact_number"]:
            tel = soup.select_one('a[href^="tel:"]')
            if tel:
                record["contact_number"] = valid_phone(tel.get("href", "")[5:])
            if not record["contact_number"]:
                match = re.search(r"(?:\+?\d[\d\s()./+ -]{7,}\d)", visible)
                if match:
                    record["contact_number"] = valid_phone(match.group(0))
        if not record["location"]:
            address = soup.find("address")
            record["location"] = clean(address.get_text(" ", strip=True)) if address else ""
        if not record["location"]:
            record["location"] = extract_jsonld_address(soup)
        if record["mail"] and record["contact_number"] and record["location"]:
            break


def serper_enrich(session: requests.Session, record: dict[str, str], api_key: str) -> None:
    if not api_key:
        return
    query = f'"{record["exhibitor_name"]}" official website {record["location"]}'
    try:
        response = session.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": 10},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return
    knowledge = data.get("knowledgeGraph") or {}
    if not record["domain"]:
        record["domain"] = get_domain(knowledge.get("website", ""))
        if not record["domain"]:
            for item in data.get("organic", []):
                candidate = get_domain(item.get("link", ""))
                if candidate:
                    record["domain"] = candidate
                    break
    if not record["location"]:
        record["location"] = clean(knowledge.get("address", ""))
    if not record["contact_number"]:
        record["contact_number"] = valid_phone(knowledge.get("phone", ""))
    if not record["mail"]:
        text = clean(json.dumps(data.get("organic", []), ensure_ascii=False))
        match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text)
        if match:
            record["mail"] = valid_email(match.group(0))


def list_profiles(session: requests.Session) -> list[str]:
    response = session.get(LIST_URL, timeout=45)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    urls: list[str] = []
    for anchor in soup.select('a[href*="/risk-europe-exhibitors/"][href$=".article"]'):
        url = anchor.get("href", "")
        if url and url not in urls:
            urls.append(url)
    if not urls:
        raise RuntimeError("No RISK Europe exhibitor profile links found.")
    return urls


def scrape_profile(session: requests.Session, url: str, api_key: str) -> dict[str, str] | None:
    try:
        response = session.get(url, timeout=45)
        response.raise_for_status()
    except requests.RequestException:
        return None
    soup = BeautifulSoup(response.text, "html.parser")
    date_node = soup.select_one(".story_title .date, .story_title time, .date")
    published = clean(date_node.get_text(" ", strip=True)) if date_node else ""
    if "2026" not in published:
        return None
    title = soup.select_one(".story_title h1, h1")
    name = clean(title.get_text(" ", strip=True)) if title else ""
    story = soup.select_one(".storyContentWrapper, .storyContent, .storytext")
    description = clean(story.get_text(" ", strip=True)) if story else ""
    homepage = ""
    for anchor in (story or soup).find_all("a", href=True):
        domain = get_domain(anchor["href"])
        if domain:
            homepage = anchor["href"]
            break
    record = {
        "exhibitor_name": name,
        "domain": get_domain(homepage),
        "contact_number": "",
        "mail": "",
        "location": "",
        "country": "",
        "description": description,
        "profile_url": url,
        "published_at": published,
        "source_year": EVENT_YEAR,
        "homepage": normalize_url(homepage),
    }
    with requests.Session() as company_session:
        company_session.headers.update(HEADERS)
        if not record["domain"]:
            serper_enrich(company_session, record, api_key)
        website_contacts(company_session, record)
        if not record["domain"] or not record["contact_number"] or not record["mail"]:
            serper_enrich(company_session, record, api_key)
    record["country"] = country_from(record["location"], record["domain"])
    record.pop("homepage")
    return record


def scrape() -> list[dict[str, str]]:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    api_key = os.getenv("SERPER_API_KEY", "")
    session = requests.Session()
    session.headers.update(HEADERS)
    profiles = list_profiles(session)
    records: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = {pool.submit(scrape_profile, session, url, api_key): url for url in profiles}
        for index, job in enumerate(as_completed(jobs), 1):
            record = job.result()
            if record:
                records.append(record)
            print(f"Profiles {index}/{len(profiles)}", flush=True)
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
