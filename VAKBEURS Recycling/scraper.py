"""Scrape the official English 2026 Vakbeurs Recycling exhibitor directory."""

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

EVENT_NAME = "VAKBEURS Recycling"
EVENT_YEAR = "2026"
SOURCE_URL = "https://www.afvalmanagement-recycling.nl/en/exhibitors/"
BASE_URL = "https://www.afvalmanagement-recycling.nl"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
CSV_PATH = OUTPUT / "VAKBEURS_RECYCLING_2026_exhibitors.csv"
JSON_PATH = OUTPUT / "VAKBEURS_RECYCLING_2026_exhibitors.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
BLOCKED = {
    "afvalmanagement-recycling.nl", "linkedin.com", "facebook.com",
    "instagram.com", "twitter.com", "x.com", "youtube.com", "wikipedia.org",
    "yellowpages.com", "yelp.com", "google.com",
    "rocketreach.co", "drimble.nl", "recyclinginside.com", "portstrategy.com",
    "euroshop-tradefair.com",
}
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "booth_no", "name", "desc", "email", "phone", "address", "city",
    "linkedin_url", "profile_url", "source_year", "source_url",
]


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def normalize_domain(value: object) -> str:
    raw = clean(value).strip("<>")
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


def country_from_text(text: str) -> str:
    countries = {
        "netherlands": "Netherlands", "belgium": "Belgium", "germany": "Germany",
        "france": "France", "italy": "Italy", "finland": "Finland",
        "canada": "Canada", "czech republic": "Czech Republic",
        "united kingdom": "United Kingdom", "england": "United Kingdom",
        "poland": "Poland", "turkey": "Türkiye", "türkiye": "Türkiye",
    }
    lower = text.casefold()
    for key, country in countries.items():
        if re.search(rf"\b{re.escape(key)}\b", lower):
            return country
    return ""


def base_record(name: str, stand: str, profile_url: str) -> dict[str, str]:
    return {
        "exhibitor_name": name, "domain": "", "contact_number": "", "mail": "",
        "location": "", "country": "", "booth_no": stand, "name": name,
        "desc": "", "email": "", "phone": "", "address": "", "city": "",
        "linkedin_url": "", "profile_url": profile_url,
        "source_year": EVENT_YEAR, "source_url": SOURCE_URL,
    }


def list_exhibitors(session: requests.Session) -> list[dict[str, str]]:
    records = []
    seen = set()
    for page in range(1, 8):
        url = SOURCE_URL if page == 1 else f"{SOURCE_URL}?stands%5Bpage%5D={page}"
        response = session.get(url, timeout=45)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for card in soup.select("article.card"):
            anchor = card.select_one("a.card__link[href]")
            heading = card.select_one("h2")
            if not anchor or not heading:
                continue
            profile_url = urljoin(BASE_URL, anchor["href"])
            if profile_url in seen:
                continue
            seen.add(profile_url)
            stand = clean(card.select_one(".stand-header__stand-number").get_text(" ", strip=True)
                          if card.select_one(".stand-header__stand-number") else "")
            description = card.select_one(".hit__description-wrapper")
            record = base_record(
                clean(heading.get_text(" ", strip=True)), stand, profile_url
            )
            record["desc"] = clean(description.get_text(" ", strip=True)) if description else ""
            records.append(record)
    if len(records) != 98:
        raise RuntimeError(f"Expected 98 2026 exhibitors, found {len(records)}")
    return records


def parse_location(body: str, record: dict[str, str]) -> None:
    record["country"] = country_from_text(body)
    match = re.search(
        r"\b\d{4}\s?[A-Z]{2}\s+([A-Z][^,\n]+?)(?:,\s*|\s+)(Netherlands|Belgium|Germany|France|Italy|Finland|Canada|Poland|Türkiye|Turkey)\b",
        body,
        re.I,
    )
    if match:
        record["city"] = clean(match.group(1))
        record["address"] = clean(match.group(0))
    record["location"] = ", ".join(x for x in (record["address"], record["city"], record["country"]) if x)


def parse_profile(record: dict[str, str], content: str) -> dict[str, str]:
    soup = BeautifulSoup(content, "html.parser")
    heading = soup.select_one("main h1, h1")
    if heading:
        record["exhibitor_name"] = record["name"] = clean(heading.get_text(" ", strip=True))
    body = clean(soup.get_text(" ", strip=True))
    if not record["booth_no"]:
        stand = re.search(r"\bStand\s*:?\s*([A-Z0-9][A-Z0-9 -/]*)", body, re.I)
        record["booth_no"] = clean(stand.group(1)) if stand else ""
    if not record["desc"]:
        about = re.search(r"About us\s+(.*?)(?:Contact information|Send us a message|$)", body, re.I)
        record["desc"] = clean(about.group(1)) if about else ""
    record["mail"] = extract_email(body)
    tel = soup.select_one('a[href^="tel:"]')
    record["contact_number"] = clean(tel.get("href", "")[4:]) if tel else ""
    record["domain"] = next(
        (
            normalize_domain(a.get("href"))
            for a in soup.find_all("a", href=True)
            if normalize_domain(a.get("href"))
            and (
                "website" in clean(a.get_text(" ", strip=True)).casefold()
                or normalize_domain(a.get("href")) in body
            )
        ),
        record["domain"],
    )
    record["linkedin_url"] = next(
        (
            clean(a.get("href")).split("?")[0]
            for a in soup.find_all("a", href=True)
            if "linkedin.com/" in clean(a.get("href")).lower()
            and "showcase" not in clean(a.get("href")).lower()
        ),
        "",
    )
    parse_location(body, record)
    record["email"] = record["mail"]
    record["phone"] = record["contact_number"]
    return record


def serper_fallback(record: dict[str, str], api_key: str) -> None:
    if record["domain"] or not api_key:
        return
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website {EVENT_YEAR}', "num": 8},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return
    knowledge = data.get("knowledgeGraph") or {}
    record["domain"] = normalize_domain(knowledge.get("website"))
    if not record["domain"]:
        tokens = {token for token in re.findall(r"[a-z0-9]+", record["exhibitor_name"].casefold()) if len(token) > 2}
        candidates = []
        for result in data.get("organic", []):
            candidate = normalize_domain(result.get("link"))
            if not candidate:
                continue
            title = clean(result.get("title")).casefold()
            score = (5 if any(token in candidate for token in tokens) else 0)
            score += sum(token in title for token in tokens) * 2
            if score >= 5:
                candidates.append((score, candidate))
        if candidates:
            record["domain"] = max(candidates, key=lambda item: item[0])[1]
    if not record["desc"]:
        record["desc"] = clean(knowledge.get("description"))
    if not record["linkedin_url"]:
        record["linkedin_url"] = next(
            (clean(item.get("link")).split("?")[0] for item in data.get("organic", [])
             if "linkedin.com/" in clean(item.get("link")).lower()),
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

    with ThreadPoolExecutor(max_workers=16) as executor:
        records = [job.result() for job in as_completed([executor.submit(fetch, item) for item in records])]

    api_key = os.getenv("SERPER_API_KEY", "")
    with ThreadPoolExecutor(max_workers=8) as executor:
        jobs = [executor.submit(serper_fallback, record, api_key) for record in records if not record["domain"]]
        for job in jobs:
            job.result()
    return sorted(records, key=lambda item: item["exhibitor_name"].casefold())


def write_outputs(records: list[dict[str, str]]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "event": EVENT_NAME, "year": EVENT_YEAR, "source": SOURCE_URL,
        "scraped_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(records), "exhibitors": records,
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
