"""Scrape the official Going Global Live 2026 exhibitor directory."""

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

EVENT_NAME = "Going Global Live"
EVENT_YEAR = "2026"
SOURCE_URL = "https://www.goinggloballive.co.uk/exhibitors"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
CSV_PATH = OUTPUT / "GOING_GLOBAL_LIVE_2026_exhibitors.csv"
JSON_PATH = OUTPUT / "GOING_GLOBAL_LIVE_2026_exhibitors.json"
SITE_HOST = "goinggloballive.co.uk"
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
    "Accept-Language": "en-GB,en;q=0.9",
}
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "name", "desc", "email", "phone", "address", "city", "linkedin_url",
    "profile_url", "source_year", "category", "stand", "source_url",
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


def parse_directory(page_html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(page_html, "html.parser")
    records: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for card in soup.find_all("li", class_="js-library-item"):
        link = card.find("a", class_="js-librarylink-entry", href=True)
        if not link:
            continue
        profile_url = urljoin(
            "https://www.goinggloballive.co.uk/",
            link["href"].split("?", 1)[0],
        )
        name = clean(link.get("aria-label", "")) or clean(
            card.find("h2").get_text(" ", strip=True) if card.find("h2") else ""
        )
        stand_node = card.find(class_="m-exhibitors-list__items__item__header__meta__stand")
        category_node = card.find(class_="m-exhibitors-list__items__item__header__meta__category")
        stand = clean(stand_node.get_text(" ", strip=True) if stand_node else "")
        category = clean(category_node.get_text(" ", strip=True) if category_node else "")
        key = (name, stand)
        if not name or key in seen:
            continue
        seen.add(key)
        records.append({
            "exhibitor_name": name,
            "domain": "",
            "contact_number": "",
            "mail": "",
            "location": "London, England, United Kingdom",
            "country": "United Kingdom",
            "name": name,
            "desc": "",
            "email": "",
            "phone": "",
            "address": "",
            "city": "London",
            "linkedin_url": "",
            "profile_url": profile_url,
            "source_year": EVENT_YEAR,
            "category": category,
            "stand": stand,
            "source_url": SOURCE_URL,
        })
    if len(records) != 53:
        raise RuntimeError(f"Expected 53 unique 2026 exhibitors, found {len(records)}")
    return records


def parse_profile(record: dict[str, str], page_html: str) -> dict[str, str]:
    soup = BeautifulSoup(page_html, "html.parser")
    title = soup.find("h1", class_="m-exhibitor-entry__item__header__infos__title")
    body = soup.find("div", class_="m-exhibitor-entry__item__body")
    description = soup.find("div", class_="m-exhibitor-entry__item__body__description")
    if title:
        record["exhibitor_name"] = record["name"] = clean(title.get_text(" ", strip=True))
    if description:
        record["desc"] = clean(description.get_text(" ", strip=True))
    if body:
        category = body.find(class_="m-exhibitor-entry__item__header__infos__category")
        if category:
            record["category"] = clean(category.get_text(" ", strip=True))
    website = next(
        (
            a.get("href", "") for a in soup.find_all("a", href=True)
            if "visit website" in clean(a.get_text(" ", strip=True)).lower()
            and normalize_domain(a.get("href", ""))
        ),
        "",
    )
    record["domain"] = normalize_domain(website)
    if not record["domain"]:
        record["domain"] = next(
            (
                normalize_domain(a.get("href", ""))
                for a in soup.find_all("a", href=True)
                if normalize_domain(a.get("href", ""))
            ),
            "",
        )
    record["linkedin_url"] = next(
        (
            a.get("href", "") for a in soup.find_all("a", href=True)
            if "linkedin.com" in a.get("href", "").lower()
            and "going-global-live" not in a.get("href", "").lower()
        ),
        "",
    )
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
            and "bsmexpo.com" not in a.get("href", "").lower()
        ),
        "",
    )
    record["email"] = record["mail"]
    record["phone"] = record["contact_number"]
    return record


def crawl_website(record: dict[str, str]) -> dict[str, str]:
    if not record["domain"]:
        return record
    session = requests.Session()
    session.headers.update(HEADERS)
    base = f"https://{record['domain']}/"
    for url in [base] + [urljoin(base, path) for path in (
        "contact/", "contact-us/", "about/", "about-us/", "impressum/",
    )]:
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
            match = re.search(
                r"(?:phone|tel(?:ephone)?|mobile|call|contact)"
                r"[^0-9]{0,25}((?:\+|00)?\d[\d\s()./-]{7,}\d)",
                body,
                re.I,
            )
            record["contact_number"] = tel or (clean(match.group(1)) if match else "")
        if not record["address"] and soup.find("address"):
            record["address"] = clean(soup.find("address").get_text(" ", strip=True))
        if record["mail"] and record["contact_number"] and record["address"]:
            break
    record["email"] = record["mail"]
    record["phone"] = record["contact_number"]
    if "bsmexpo.com" in record["mail"].lower():
        record["mail"] = record["email"] = ""
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
        query = f'"{record["exhibitor_name"]}" official website {EVENT_YEAR} London'
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
    records = parse_directory(response.text)
    with ThreadPoolExecutor(max_workers=10) as executor:
        jobs = []
        for record in records:
            try:
                profile = requests.get(record["profile_url"], headers=HEADERS, timeout=30)
                profile.raise_for_status()
                jobs.append(executor.submit(parse_profile, record, profile.text))
            except requests.RequestException:
                jobs.append(executor.submit(lambda value: value, record))
        enriched = [job.result() for job in as_completed(jobs)]
        website_jobs = [executor.submit(crawl_website, record) for record in enriched]
        enriched = [job.result() for job in as_completed(website_jobs)]
    serper_fallback(enriched, os.getenv("SERPER_API_KEY", ""))
    write_outputs(enriched)
    print(f"Saved {len(enriched)} exhibitors")
    print(CSV_PATH)
    print(JSON_PATH)


if __name__ == "__main__":
    main()
