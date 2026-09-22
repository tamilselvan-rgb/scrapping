"""Scrape the official MechanEx Surrey 2026 exhibitor directory."""

from __future__ import annotations

import csv
import html
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

EVENT_NAME = "MechanEx Surrey"
EVENT_YEAR = "2026"
SOURCE_URL = "https://mechanex.info/"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
CSV_PATH = OUTPUT / "MECHANEX_SURREY_2026_exhibitors.csv"
JSON_PATH = OUTPUT / "MECHANEX_SURREY_2026_exhibitors.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
BLOCKED = {
    "mechanex.info", "linkedin.com", "facebook.com", "instagram.com",
    "twitter.com", "x.com", "youtube.com", "wikipedia.org",
    "yellowpages.com", "yelp.com", "google.com", "mapquest.com",
    "trustpilot.com", "enterpriseleague.com", "thestar.com", "crunchbase.com",
    "zoominfo.com", "dnb.com", "companieshouse.gov.uk", "indeed.com",
    "glassdoor.com", "messefrankfurt.com", "aftermarketnews.com",
    "rocketreach.co", "am-online.com", "supportlane.io",
    "datacenterdynamics.com", "educationcannotwait.org", "trustindex.io",
    "find-and-update.company-information.service.gov.uk", "redcresearch.com",
    "tracxn.com", "capterra.com", "hillhead.com", "pitchbook.com",
    "usda.gov", "tm-robot.com", "vehicleservicepros.com", "meritt.io",
    "leadiq.com",
}
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "name", "booth_no", "desc", "email", "phone", "address", "city",
    "linkedin_url", "profile_url", "source_year", "source_url",
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
    if any(host == blocked or host.endswith("." + blocked) for blocked in BLOCKED):
        return ""
    return host


def extract_email(text: str) -> str:
    match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text or "")
    return match.group(0) if match else ""


def jsonld_contact(soup: BeautifulSoup) -> tuple[str, str, str]:
    address = city = country = ""
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if not isinstance(item, dict):
                continue
            addr = item.get("address")
            if isinstance(addr, dict):
                address = address or clean(addr.get("streetAddress"))
                city = city or clean(addr.get("addressLocality"))
                country_value = addr.get("addressCountry", "")
                country = country or clean(
                    country_value.get("name") if isinstance(country_value, dict) else country_value
                )
            elif isinstance(addr, str):
                address = address or clean(addr)
    return address, city, country


def base_record(name: str, profile_url: str) -> dict[str, str]:
    return {
        "exhibitor_name": name, "domain": "", "contact_number": "",
        "mail": "", "location": "", "country": "United Kingdom",
        "name": name, "booth_no": "", "desc": "", "email": "", "phone": "",
        "address": "", "city": "", "linkedin_url": "", "profile_url": profile_url,
        "source_year": EVENT_YEAR, "source_url": SOURCE_URL,
    }


def parse_profile(record: dict[str, str], content: str) -> dict[str, str]:
    soup = BeautifulSoup(content, "html.parser")
    heading = soup.select_one("main h1, article h1, h1")
    if heading:
        name = clean(heading.get_text(" ", strip=True))
        if name and "mechanex" not in name.casefold():
            record["exhibitor_name"] = record["name"] = name

    text_blocks = soup.select(
        "main .elementor-widget-text-editor, main .elementor-widget-theme-post-content"
    )
    if text_blocks:
        record["desc"] = clean(" ".join(block.get_text(" ", strip=True) for block in text_blocks))
    if not record["desc"]:
        record["desc"] = clean((soup.find("main") or soup).get_text(" ", strip=True))

    address, city, country = jsonld_contact(soup)
    record["address"] = address
    record["city"] = city
    record["country"] = country or record["country"]
    record["location"] = address
    record["mail"] = extract_email(soup.get_text(" ", strip=True))
    tel = soup.select_one('a[href^="tel:"]')
    record["contact_number"] = clean(tel.get("href", "")[4:]) if tel else ""
    record["linkedin_url"] = next(
        (
            clean(a.get("href")).split("?")[0]
            for a in soup.find_all("a", href=True)
            if "linkedin.com/" in clean(a.get("href")).lower()
        ),
        "",
    )
    record["email"] = record["mail"]
    record["phone"] = record["contact_number"]
    return record


def serper_fallback(record: dict[str, str], api_key: str) -> None:
    if record["domain"] or not api_key:
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
    record["domain"] = normalize_domain(knowledge.get("website"))
    if not record["domain"]:
        name_tokens = {
            token.casefold()
            for token in re.findall(r"[a-z0-9]+", record["exhibitor_name"])
            if len(token) > 2
        }
        candidates = []
        for result in data.get("organic", []):
            candidate = normalize_domain(result.get("link"))
            if not candidate:
                continue
            title = clean(result.get("title")).casefold()
            snippet = clean(result.get("snippet")).casefold()
            host_tokens = set(re.findall(r"[a-z0-9]+", candidate.casefold()))
            score = len(name_tokens & host_tokens) * 5
            score += 5 if any(token in candidate.casefold() for token in name_tokens) else 0
            score += sum(token in title for token in name_tokens) * 3
            score += sum(token in snippet for token in name_tokens)
            candidates.append((score, candidate))
        candidates = [item for item in candidates if item[0] >= 5]
        if candidates:
            record["domain"] = max(candidates, key=lambda item: item[0])[1]
    if not record["desc"]:
        record["desc"] = clean(knowledge.get("description"))
    if not record["linkedin_url"]:
        record["linkedin_url"] = next(
            (
                clean(item.get("link")).split("?")[0]
                for item in data.get("organic", [])
                if "linkedin.com/" in clean(item.get("link")).lower()
            ),
            "",
        )


def enrich_from_website(record: dict[str, str]) -> None:
    if not record["domain"]:
        return
    session = requests.Session()
    session.headers.update(HEADERS)
    for suffix in ("", "contact", "contact-us", "about", "about-us"):
        try:
            response = session.get(
                f"https://{record['domain']}/{suffix}", timeout=15
            )
            if response.status_code >= 400:
                continue
        except requests.RequestException:
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        body = clean(soup.get_text(" ", strip=True))
        record["mail"] = record["mail"] or extract_email(body)
        tel = soup.select_one('a[href^="tel:"]')
        if not record["contact_number"] and tel:
            record["contact_number"] = clean(tel.get("href", "")[4:])
        address, city, country = jsonld_contact(soup)
        record["address"] = record["address"] or address
        record["city"] = record["city"] or city
        record["country"] = record["country"] or country or "United Kingdom"
        record["location"] = record["location"] or record["address"]
        record["linkedin_url"] = record["linkedin_url"] or next(
            (
                clean(a.get("href")).split("?")[0]
                for a in soup.find_all("a", href=True)
                if "linkedin.com/" in clean(a.get("href")).lower()
            ),
            "",
        )
        if record["mail"] and record["contact_number"] and record["location"]:
            break


def list_exhibitors(session: requests.Session) -> list[dict[str, str]]:
    response = session.get(SOURCE_URL, timeout=45)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    records = []
    seen = set()
    for article in soup.select("article.category-exhibitor"):
        anchor = article.select_one("a[href]")
        if not anchor:
            continue
        profile_url = anchor.get("href", "").split("?", 1)[0].rstrip("/") + "/"
        if profile_url in seen:
            continue
        seen.add(profile_url)
        records.append(base_record("", profile_url))
    if not records:
        raise RuntimeError("No 2026 exhibitors found on the official MechanEx directory")
    return records


def scrape() -> list[dict[str, str]]:
    load_dotenv(ROOT.parent / ".env")
    api_key = os.getenv("SERPER_API_KEY", "")
    session = requests.Session()
    session.headers.update(HEADERS)
    records = list_exhibitors(session)

    def fetch(record: dict[str, str]) -> dict[str, str]:
        response = session.get(record["profile_url"], timeout=45)
        response.raise_for_status()
        return parse_profile(record, response.text)

    with ThreadPoolExecutor(max_workers=10) as executor:
        jobs = {executor.submit(fetch, record): record for record in records}
        parsed = []
        for job in as_completed(jobs):
            try:
                parsed.append(job.result())
            except requests.RequestException:
                parsed.append(jobs[job])

    def enrich(record: dict[str, str]) -> dict[str, str]:
        if not record["exhibitor_name"]:
            record["exhibitor_name"] = record["name"] = (
                record["profile_url"].rstrip("/").rsplit("/", 1)[-1]
            )
        serper_fallback(record, api_key)
        enrich_from_website(record)
        record["email"] = record["mail"]
        record["phone"] = record["contact_number"]
        return record

    with ThreadPoolExecutor(max_workers=8) as executor:
        jobs = [executor.submit(enrich, record) for record in parsed]
        parsed = [job.result() for job in as_completed(jobs)]
    return sorted(parsed, key=lambda row: row["exhibitor_name"].casefold())


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
