"""Scrape the official Sthlm Food & Wine 2026 exhibitor directory."""

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

EVENT_NAME = "STHML FOOD AND WINE"
EVENT_YEAR = "2026"
SOURCE_URL = "https://sthlmfoodandwine.se/utstallarforteckning/"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
CSV_PATH = OUTPUT / "STHML_FOOD_AND_WINE_2026_exhibitors.csv"
JSON_PATH = OUTPUT / "STHML_FOOD_AND_WINE_2026_exhibitors.json"
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "tiktok.com", "pinterest.com", "wikipedia.org",
    "yellowpages.com", "yelp.com", "sthlmfoodandwine.se",
}
GENERIC_EMAIL_HOSTS = {
    "gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "icloud.com",
}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/151.0 Safari/537.36"
    ),
    "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
}
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "name", "desc", "email", "phone", "address", "city", "linkedin_url",
    "profile_url", "source_year", "category", "stand", "source_url",
]


def clean(value: str) -> str:
    value = html.unescape(value or "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


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
    seen: set[str] = set()
    for card in soup.find_all("div", attrs={"data-elementor-type": "loop-item"}):
        title = card.find(class_="elementor-divider__text")
        anchor = card.find("a", href=True)
        name = clean(title.get_text(" ", strip=True) if title else "")
        profile_url = clean(anchor.get("href", "") if anchor else "")
        if not name or name in seen:
            continue
        seen.add(name)
        buttons = [
            clean(node.get_text(" ", strip=True))
            for node in card.find_all(class_="elementor-button-text")
        ]
        records.append({
            "exhibitor_name": name,
            "domain": normalize_domain(profile_url),
            "contact_number": "",
            "mail": "",
            "location": "Stockholm, Stockholm County, Sweden",
            "country": "Sweden",
            "name": name,
            "desc": "",
            "email": "",
            "phone": "",
            "address": "",
            "city": "Stockholm",
            "linkedin_url": "",
            "profile_url": profile_url,
            "source_year": EVENT_YEAR,
            "category": buttons[0] if buttons else "",
            "stand": buttons[1] if len(buttons) > 1 else "",
            "source_url": SOURCE_URL,
        })
    if len(records) != 141:
        raise RuntimeError(f"Expected 141 2026 exhibitors, found {len(records)}")
    return records


def extract_website_data(record: dict[str, str]) -> dict[str, str]:
    """Visit the listed exhibitor URL and collect public contact information."""
    result = dict(record)
    if not result["domain"]:
        return result
    session = requests.Session()
    session.headers.update(HEADERS)
    base_url = result["profile_url"]
    urls = [base_url]
    root_url = f"https://{result['domain']}/"
    if urlparse(base_url).netloc.lower().removeprefix("www.") != result["domain"]:
        urls.insert(0, root_url)
    for suffix in ("contact", "contact-us", "kontakt", "about", "impressum"):
        urls.append(urljoin(root_url, suffix + "/"))
    visited: set[str] = set()
    for url in urls:
        if url in visited:
            continue
        visited.add(url)
        try:
            response = session.get(url, timeout=12, allow_redirects=True)
            if response.status_code >= 400:
                continue
        except requests.RequestException:
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        description = soup.find("meta", attrs={"name": "description"})
        if not result["desc"] and description and description.get("content"):
            result["desc"] = clean(description["content"])
        body = clean(soup.get_text(" ", strip=True))
        if not result["mail"]:
            mailto = next(
                (
                    clean(a.get("href", "")[7:].split("?", 1)[0])
                    for a in soup.find_all("a", href=True)
                    if a.get("href", "").lower().startswith("mailto:")
                ),
                "",
            )
            match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", body)
            result["mail"] = mailto or (match.group(0) if match else "")
        if not result["contact_number"]:
            tel = next(
                (
                    clean(a.get("href", "")[4:])
                    for a in soup.find_all("a", href=True)
                    if a.get("href", "").lower().startswith("tel:")
                ),
                "",
            )
            match = re.search(
                r"(?:tel(?:ephone)?|telefon|phone|mobile|mob\.?|call|ring|kontakt)"
                r"[^0-9]{0,25}((?:\+|00)?\d[\d\s()./-]{7,}\d)",
                body,
                re.I,
            )
            result["contact_number"] = tel or (clean(match.group(1)) if match else "")
        if not result["address"]:
            address = soup.find("address")
            if address:
                result["address"] = clean(address.get_text(" ", strip=True))
        if not result["linkedin_url"]:
            result["linkedin_url"] = next(
                (
                    a.get("href", "") for a in soup.find_all("a", href=True)
                    if "linkedin.com" in a.get("href", "").lower()
                ),
                "",
            )
        if result["mail"] and result["contact_number"] and result["address"]:
            break
    result["email"] = result["mail"]
    result["phone"] = result["contact_number"]
    if result["address"]:
        result["location"] = result["address"]
    return result


def serper_enrich(records: list[dict[str, str]], api_key: str) -> None:
    if not api_key:
        return
    session = requests.Session()
    session.headers.update(HEADERS)
    for record in records:
        if record["domain"]:
            continue
        query = f'"{record["exhibitor_name"]}" official website {EVENT_YEAR} Stockholm'
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
        record["email"] = record["mail"]
        record["phone"] = record["contact_number"]


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
    JSON_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    response = requests.get(SOURCE_URL, headers=HEADERS, timeout=45)
    response.raise_for_status()
    records = parse_directory(response.text)
    with ThreadPoolExecutor(max_workers=12) as executor:
        jobs = [executor.submit(extract_website_data, record) for record in records]
        enriched = []
        for index, job in enumerate(as_completed(jobs), 1):
            enriched.append(job.result())
            if index % 25 == 0 or index == len(records):
                print(f"Visited {index}/{len(records)} exhibitor links", flush=True)
    serper_enrich(enriched, os.getenv("SERPER_API_KEY", ""))
    write_outputs(enriched)
    print(f"Saved {len(enriched)} exhibitors")
    print(CSV_PATH)
    print(JSON_PATH)


if __name__ == "__main__":
    main()
