"""Scrape The Business Show London 2026 exhibitor directory."""

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

EVENT_NAME = "The Business Show"
EVENT_YEAR = "2026"
SOURCE_URL = "https://www.greatbritishbusinessshow.co.uk/exhibitor-listings"
BASE_URL = "https://www.greatbritishbusinessshow.co.uk/"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
CSV_PATH = OUTPUT / "THE_BUSINESS_SHOW_2026_exhibitors.csv"
JSON_PATH = OUTPUT / "THE_BUSINESS_SHOW_2026_exhibitors.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
BLOCKED = {
    "greatbritishbusinessshow.co.uk", "linkedin.com", "facebook.com",
    "instagram.com", "twitter.com", "x.com", "youtube.com", "wikipedia.org",
    "yellowpages.com", "yelp.com", "google.com",
}
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "booth_no", "name", "desc", "email", "phone", "address", "city",
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
    if any(host == item or host.endswith("." + item) for item in BLOCKED):
        return ""
    return host


def extract_email(text: str) -> str:
    match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text or "")
    return match.group(0) if match else ""


def jsonld_items(soup: BeautifulSoup) -> list[dict]:
    items = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            payload = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        items.extend(payload if isinstance(payload, list) else [payload])
    return [item for item in items if isinstance(item, dict)]


def country_from_text(text: str) -> str:
    countries = {
        "united kingdom": "United Kingdom", "england": "United Kingdom",
        "uk": "United Kingdom", "ireland": "Ireland", "united states": "United States",
        "usa": "United States", "canada": "Canada", "australia": "Australia",
        "germany": "Germany", "france": "France", "spain": "Spain",
        "netherlands": "Netherlands", "india": "India", "singapore": "Singapore",
    }
    lower = text.casefold()
    for key, country in countries.items():
        if re.search(rf"\b{re.escape(key)}\b", lower):
            return country
    return ""


def base_record(name: str, stand: str, profile_url: str) -> dict[str, str]:
    return {
        "exhibitor_name": name, "domain": "", "contact_number": "", "mail": "",
        "location": "", "country": "United Kingdom", "booth_no": stand,
        "name": name, "desc": "", "email": "", "phone": "", "address": "",
        "city": "", "linkedin_url": "", "profile_url": profile_url,
        "source_year": EVENT_YEAR, "source_url": SOURCE_URL,
    }


def list_exhibitors(session: requests.Session) -> list[dict[str, str]]:
    records = []
    seen = set()
    for page in (1, 2):
        url = SOURCE_URL if page == 1 else f"{SOURCE_URL}?page={page}"
        response = session.get(url, timeout=45)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for article in soup.select("article.m-exhibitors-list__list__items__item"):
            title = article.select_one("h2")
            anchor = article.select_one("h2 a[href]")
            if not title or not anchor:
                continue
            profile_url = urljoin(BASE_URL, anchor["href"])
            if profile_url in seen:
                continue
            seen.add(profile_url)
            text = clean(article.get_text(" ", strip=True))
            stand_match = re.search(r"\bStand:\s*(.+?)(?:\s+Exhibitor profile|\s*$)", text, re.I)
            stand = clean(stand_match.group(1)) if stand_match else ""
            record = base_record(clean(title.get_text(" ", strip=True)), stand, profile_url)
            for item in jsonld_items(article):
                entity = item.get("mainEntity") if isinstance(item.get("mainEntity"), dict) else item
                record["domain"] = normalize_domain(entity.get("url"))
                record["desc"] = clean(BeautifulSoup(str(entity.get("description", "")), "html.parser").get_text(" ", strip=True))
                record["linkedin_url"] = next(
                    (clean(link) for link in entity.get("sameAs", []) if "linkedin.com/" in clean(link).lower()),
                    "",
                )
                if record["domain"] or record["desc"]:
                    break
            records.append(record)
    if not records:
        raise RuntimeError("No 2026 Business Show exhibitors found")
    return records


def parse_profile(record: dict[str, str], content: str) -> dict[str, str]:
    soup = BeautifulSoup(content, "html.parser")
    heading = soup.select_one("main h1, article h1, h1")
    if heading:
        record["exhibitor_name"] = record["name"] = clean(heading.get_text(" ", strip=True))

    entities = jsonld_items(soup)
    for item in entities:
        entity = item.get("mainEntity") if isinstance(item.get("mainEntity"), dict) else item
        if not isinstance(entity, dict):
            continue
        record["domain"] = record["domain"] or normalize_domain(entity.get("url"))
        if not record["desc"]:
            record["desc"] = clean(
                BeautifulSoup(str(entity.get("description", "")), "html.parser").get_text(" ", strip=True)
            )
        if not record["linkedin_url"]:
            record["linkedin_url"] = next(
                (clean(link) for link in entity.get("sameAs", []) if "linkedin.com/" in clean(link).lower()),
                "",
            )

    if not record["desc"]:
        blocks = soup.select("main .m-exhibitor-detail, main .elementor-widget-text-editor")
        record["desc"] = clean(" ".join(block.get_text(" ", strip=True) for block in blocks))
    body = clean(soup.get_text(" ", strip=True))
    record["mail"] = extract_email(body)
    tel = soup.select_one('a[href^="tel:"]')
    record["contact_number"] = clean(tel.get("href", "")[4:]) if tel else ""
    if not record["domain"]:
        record["domain"] = next(
            (
                normalize_domain(a.get("href"))
                for a in soup.find_all("a", href=True)
                if "visit website" in clean(a.get_text(" ", strip=True)).casefold()
            ),
            "",
        )
    record["country"] = country_from_text(body) or record["country"]
    record["email"] = record["mail"]
    record["phone"] = record["contact_number"]
    return record


def serper_fallback(record: dict[str, str], api_key: str) -> None:
    if record["domain"] or not api_key:
        return
    query = f'"{record["exhibitor_name"]}" official website {EVENT_YEAR} United Kingdom'
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
            token for token in re.findall(r"[a-z0-9]+", record["exhibitor_name"].casefold())
            if len(token) > 2
        }
        candidates = []
        for result in data.get("organic", []):
            candidate = normalize_domain(result.get("link"))
            if not candidate:
                continue
            host = candidate.casefold()
            title = clean(result.get("title")).casefold()
            score = (5 if any(token in host for token in name_tokens) else 0)
            score += sum(token in title for token in name_tokens) * 2
            if score >= 5:
                candidates.append((score, candidate))
        if candidates:
            record["domain"] = max(candidates, key=lambda pair: pair[0])[1]
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


def scrape() -> list[dict[str, str]]:
    load_dotenv(ROOT.parent / ".env")
    session = requests.Session()
    session.headers.update(HEADERS)
    records = list_exhibitors(session)

    def fetch(record: dict[str, str]) -> dict[str, str]:
        try:
            response = session.get(record["profile_url"], timeout=45)
            response.raise_for_status()
            return parse_profile(record, response.text)
        except requests.RequestException:
            return record

    with ThreadPoolExecutor(max_workers=20) as executor:
        jobs = [executor.submit(fetch, record) for record in records]
        records = [job.result() for job in as_completed(jobs)]

    api_key = os.getenv("SERPER_API_KEY", "")
    missing_domains = [record for record in records if not record["domain"]]
    with ThreadPoolExecutor(max_workers=8) as executor:
        jobs = [executor.submit(serper_fallback, record, api_key) for record in missing_domains]
        for job in jobs:
            job.result()
    return sorted(records, key=lambda row: row["exhibitor_name"].casefold())


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
