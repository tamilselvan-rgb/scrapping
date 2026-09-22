"""Scrape and enrich the Woking Means Business 2026 exhibitor list."""

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

EVENT_NAME = "Woking Means Business"
EVENT_YEAR = "2026"
SOURCE_URL = "https://wokingmeansbusiness.com/exhibitors/"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
CSV_PATH = OUTPUT / "WOKING_MEANS_BUSINESS_2026_exhibitors.csv"
JSON_PATH = OUTPUT / "WOKING_MEANS_BUSINESS_2026_exhibitors.json"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/151.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}
BLOCKED = {
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com",
    "wokingmeansbusiness.com", "google.com", "bing.com",
}
GENERIC_EMAIL_HOSTS = {
    "gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "icloud.com",
}
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "name", "desc", "email", "phone", "address", "city", "linkedin_url",
    "profile_url", "source_year", "source_url",
]


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "").replace("\xa0", " ")).strip()


def normalize_domain(value: str) -> str:
    value = clean(value).strip(" .;,")
    if not value:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", value, re.I):
        value = "https://" + value
    host = urlparse(value).netloc.lower().removeprefix("www.")
    if not host or "." not in host:
        return ""
    if any(host == blocked or host.endswith("." + blocked) for blocked in BLOCKED):
        return ""
    return host


def parse_names(page_html: str) -> list[str]:
    soup = BeautifulSoup(page_html, "html.parser")
    heading = soup.find(
        ["h1", "h2", "h3"],
        string=lambda value: value and "Exhibitors 2026" in clean(value),
    )
    if not heading:
        raise RuntimeError("The official Exhibitors 2026 section was not found")
    names = [
        clean(p.get_text(" ", strip=True))
        for p in heading.parent.parent.find_all("p")
        if clean(p.get_text(" ", strip=True))
    ]
    if len(names) != 32:
        raise RuntimeError(f"Expected 32 Woking 2026 exhibitors, found {len(names)}")
    return names


def blank_record(name: str) -> dict[str, str]:
    return {
        "exhibitor_name": name,
        "domain": "",
        "contact_number": "",
        "mail": "",
        "location": "Woking, Surrey, United Kingdom",
        "country": "United Kingdom",
        "name": name,
        "desc": "",
        "email": "",
        "phone": "",
        "address": "",
        "city": "Woking",
        "linkedin_url": "",
        "profile_url": SOURCE_URL,
        "source_year": EVENT_YEAR,
        "source_url": SOURCE_URL,
    }


def serper_search(record: dict[str, str], api_key: str) -> dict[str, str]:
    if not api_key:
        return record
    session = requests.Session()
    session.headers.update(HEADERS)
    query = f'"{record["exhibitor_name"]}" official website {EVENT_YEAR} Woking'
    try:
        response = session.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": 8},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return record
    knowledge = data.get("knowledgeGraph") or {}
    record["domain"] = normalize_domain(knowledge.get("website", ""))
    if not record["domain"]:
        for result in data.get("organic", []):
            candidate = normalize_domain(result.get("link", ""))
            if candidate:
                record["domain"] = candidate
                break
    record["contact_number"] = clean(knowledge.get("phone", ""))
    record["address"] = clean(knowledge.get("address", ""))
    record["desc"] = clean(knowledge.get("description", ""))
    record["linkedin_url"] = next(
        (
            result.get("link", "")
            for result in data.get("organic", [])
            if "linkedin.com" in result.get("link", "").lower()
        ),
        "",
    )
    if record["address"]:
        record["location"] = record["address"]
    record["phone"] = record["contact_number"]
    return record


def crawl_website(record: dict[str, str]) -> dict[str, str]:
    if not record["domain"]:
        return record
    session = requests.Session()
    session.headers.update(HEADERS)
    base = f"https://{record['domain']}/"
    urls = [base] + [urljoin(base, path) for path in (
        "contact/", "contact-us/", "about/", "about-us/", "get-in-touch/",
    )]
    for url in urls:
        try:
            response = session.get(url, timeout=12, allow_redirects=True)
            if response.status_code >= 400:
                continue
        except requests.RequestException:
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        if not record["desc"]:
            meta = soup.find("meta", attrs={"name": "description"})
            if meta and meta.get("content"):
                record["desc"] = clean(meta["content"])
        body = clean(soup.get_text(" ", strip=True))
        if not record["mail"]:
            mailto = next(
                (
                    clean(a.get("href", "")[7:].split("?", 1)[0])
                    for a in soup.find_all("a", href=True)
                    if a.get("href", "").lower().startswith("mailto:")
                ),
                "",
            )
            match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", body)
            record["mail"] = mailto or (match.group(0) if match else "")
        if not record["contact_number"]:
            tel = next(
                (
                    clean(a.get("href", "")[4:])
                    for a in soup.find_all("a", href=True)
                    if a.get("href", "").lower().startswith("tel:")
                ),
                "",
            )
            match = re.search(
                r"(?:phone|tel(?:ephone)?|mobile|call|contact)"
                r"[^0-9]{0,25}((?:\+|00)?\d[\d\s()./-]{7,}\d)",
                body,
                re.I,
            )
            record["contact_number"] = tel or (clean(match.group(1)) if match else "")
        if not record["address"]:
            address = soup.find("address")
            if address:
                record["address"] = clean(address.get_text(" ", strip=True))
        if not record["linkedin_url"]:
            record["linkedin_url"] = next(
                (
                    a.get("href", "") for a in soup.find_all("a", href=True)
                    if "linkedin.com" in a.get("href", "").lower()
                ),
                "",
            )
        if record["mail"] and record["contact_number"] and record["address"]:
            break
    record["email"] = record["mail"]
    record["phone"] = record["contact_number"]
    if record["address"]:
        record["location"] = record["address"]
    return record


def write_outputs(records: list[dict[str, str]]) -> None:
    records = sorted(records, key=lambda row: row["exhibitor_name"].casefold())
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


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    response = requests.get(SOURCE_URL, headers=HEADERS, timeout=45)
    response.raise_for_status()
    names = parse_names(response.text)
    api_key = os.getenv("SERPER_API_KEY", "")
    with ThreadPoolExecutor(max_workers=8) as executor:
        jobs = [
            executor.submit(crawl_website, serper_search(blank_record(name), api_key))
            for name in names
        ]
        records = [job.result() for job in as_completed(jobs)]
    write_outputs(records)
    print(f"Saved {len(records)} exhibitors")
    print(CSV_PATH)
    print(JSON_PATH)


if __name__ == "__main__":
    main()
