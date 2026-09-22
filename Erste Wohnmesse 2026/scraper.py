"""Scrape the official Erste Wohnmesse 2026 exhibitor directory and profiles."""

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

EVENT_NAME = "Erste Wohnmesse"
EVENT_YEAR = "2026"
SOURCE_URL = "https://erstewohnmesse.at/aussteller/"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
CSV_PATH = OUTPUT / "ERSTE_WOHNMESSE_2026_exhibitors.csv"
JSON_PATH = OUTPUT / "ERSTE_WOHNMESSE_2026_exhibitors.json"
SITE_HOST = "erstewohnmesse.at"
BLOCKED = {
    SITE_HOST, "facebook.com", "instagram.com", "linkedin.com", "twitter.com",
    "x.com", "youtube.com", "tiktok.com", "wikipedia.org", "yellowpages.com",
    "yelp.com", "google.com",
}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/151.0 Safari/537.36"
    ),
    "Accept-Language": "de-AT,de;q=0.9,en;q=0.8",
}
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "name", "desc", "email", "phone", "address", "city", "linkedin_url",
    "profile_url", "source_year", "category", "stand", "source_url",
]
CATEGORIES = ("Bauträger", "Dienstleister", "Immobilienmakler", "Medium")


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


def parse_listing(page_html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(page_html, "html.parser")
    records = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].split("?", 1)[0].rstrip("/")
        if not re.match(r"^https://erstewohnmesse\.at/aussteller/[^/]+$", href):
            continue
        if href in seen:
            continue
        seen.add(href)
        label = clean(anchor.get_text(" ", strip=True))
        parts = [clean(part) for part in label.split("|", 1)]
        left = parts[0] if parts else ""
        stand = parts[1] if len(parts) > 1 else ""
        category = next(
            (category for category in CATEGORIES if left.endswith(category)),
            "",
        )
        name = clean(left[:-len(category)] if category else left)
        records.append({
            "exhibitor_name": name,
            "domain": "",
            "contact_number": "",
            "mail": "",
            "location": "Vienna, Austria",
            "country": "Austria",
            "name": name,
            "desc": "",
            "email": "",
            "phone": "",
            "address": "",
            "city": "Vienna",
            "linkedin_url": "",
            "profile_url": href + "/",
            "source_year": EVENT_YEAR,
            "category": category,
            "stand": stand,
            "source_url": SOURCE_URL,
        })
    if len(records) != 46:
        raise RuntimeError(f"Expected 46 2026 exhibitors, found {len(records)}")
    return records


def parse_profile(record: dict[str, str], profile_html: str) -> dict[str, str]:
    soup = BeautifulSoup(profile_html, "html.parser")
    title = soup.find("h1", class_="brxe-post-title") or soup.find("h1")
    if title:
        record["exhibitor_name"] = record["name"] = clean(title.get_text(" ", strip=True))
    content = title.parent if title else soup.find("main") or soup
    record["desc"] = clean(content.get_text(" ", strip=True))
    website = next(
        (
            a.get("href", "") for a in soup.find_all("a", href=True)
            if "website" in clean(a.get_text(" ", strip=True)).lower()
            and normalize_domain(a.get("href", ""))
        ),
        "",
    )
    if not website:
        website = next(
            (
                a.get("href", "") for a in soup.find_all("a", href=True)
                if normalize_domain(a.get("href", ""))
            ),
            "",
        )
    record["domain"] = normalize_domain(website)
    record["contact_number"] = next(
        (
            clean(a.get("href", "")[4:])
            for a in soup.find_all("a", href=True)
            if a.get("href", "").lower().startswith("tel:")
        ),
        "",
    )
    record["mail"] = next(
        (
            clean(a.get("href", "")[7:].split("?", 1)[0])
            for a in soup.find_all("a", href=True)
            if a.get("href", "").lower().startswith("mailto:")
        ),
        "",
    )
    body = clean(content.get_text(" ", strip=True))
    if not record["mail"]:
        match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", body)
        if match:
            record["mail"] = match.group(0)
    if not record["contact_number"]:
        match = re.search(
            r"(?:phone|telefon|tel\.?|anrufen|call)"
            r"[^0-9]{0,25}((?:\+|00)?\d[\d\s()./-]{7,}\d)",
            body,
            re.I,
        )
        if match:
            record["contact_number"] = clean(match.group(1))
    address = soup.find("address")
    if address:
        record["address"] = clean(address.get_text(" ", strip=True))
    record["linkedin_url"] = next(
        (
            a.get("href", "") for a in soup.find_all("a", href=True)
            if "linkedin.com" in a.get("href", "").lower()
        ),
        "",
    )
    record["email"] = record["mail"]
    record["phone"] = record["contact_number"]
    if record["address"]:
        record["location"] = record["address"]
    return record


def crawl_profile(record: dict[str, str]) -> dict[str, str]:
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        response = session.get(record["profile_url"], timeout=30)
        response.raise_for_status()
        record = parse_profile(record, response.text)
    except requests.RequestException:
        return record
    if not record["domain"]:
        return record
    base = f"https://{record['domain']}/"
    urls = [base] + [urljoin(base, path) for path in (
        "contact/", "contact-us/", "kontakt/", "impressum/", "about/",
    )]
    for url in urls:
        try:
            response = session.get(url, timeout=12)
            if response.status_code >= 400:
                continue
        except requests.RequestException:
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        body = clean(soup.get_text(" ", strip=True))
        if not record["mail"]:
            match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", body)
            if match:
                record["mail"] = match.group(0)
        if not record["contact_number"]:
            tel = next(
                (
                    clean(a.get("href", "")[4:])
                    for a in soup.find_all("a", href=True)
                    if a.get("href", "").lower().startswith("tel:")
                ),
                "",
            )
            record["contact_number"] = tel
        if not record["address"] and soup.find("address"):
            record["address"] = clean(soup.find("address").get_text(" ", strip=True))
        if record["mail"] and record["contact_number"] and record["address"]:
            break
    record["email"] = record["mail"]
    record["phone"] = record["contact_number"]
    if record["address"]:
        record["location"] = record["address"]
    return record


def serper_fallback(records: list[dict[str, str]], api_key: str) -> None:
    if not api_key:
        return
    session = requests.Session()
    session.headers.update(HEADERS)
    for record in records:
        if record["domain"]:
            continue
        query = f'"{record["exhibitor_name"]}" official website {EVENT_YEAR} Vienna'
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
            continue
        knowledge = data.get("knowledgeGraph") or {}
        record["domain"] = normalize_domain(knowledge.get("website", ""))
        if not record["domain"]:
            for item in data.get("organic", []):
                candidate = normalize_domain(item.get("link", ""))
                if candidate:
                    record["domain"] = candidate
                    break
        if not record["contact_number"]:
            record["contact_number"] = clean(knowledge.get("phone", ""))
        if not record["address"]:
            record["address"] = clean(knowledge.get("address", ""))
        record["phone"] = record["contact_number"]
        record["email"] = record["mail"]
        if record["address"]:
            record["location"] = record["address"]


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
    records = parse_listing(response.text)
    with ThreadPoolExecutor(max_workers=8) as executor:
        jobs = [executor.submit(crawl_profile, record) for record in records]
        enriched = [job.result() for job in as_completed(jobs)]
    serper_fallback(enriched, os.getenv("SERPER_API_KEY", ""))
    write_outputs(enriched)
    print(f"Saved {len(enriched)} exhibitors")
    print(CSV_PATH)
    print(JSON_PATH)


if __name__ == "__main__":
    main()
