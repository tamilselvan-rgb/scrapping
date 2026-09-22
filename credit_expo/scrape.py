"""
Scrape Credit Expo 2026 exhibitor list and profile details.

Source:
    https://www.creditexpo.nl/event/exposantenlijst-2026/

Outputs:
    output/CREDIT_EXPO_exhibitors.csv
    output/CREDIT_EXPO_exhibitors.json
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

LIST_URL = "https://www.creditexpo.nl/event/exposantenlijst-2026/"
EVENT_NAME = "CREDIT_EXPO"
EVENT_YEAR = "2026"

ROOT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT_DIR / "output"
CSV_PATH = OUTPUT_DIR / f"{EVENT_NAME}_exhibitors.csv"
JSON_PATH = OUTPUT_DIR / f"{EVENT_NAME}_exhibitors.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,nl;q=0.8",
}

CSV_FIELDS = [
    "name",
    "desc",
    "email",
    "phone",
    "domain",
    "address",
    "city",
    "linkedin_url",
    "stand",
    "partner_tier",
    "profile_url",
    "postcode",
    "country",
]

HTTP_CONCURRENCY = 6
TIMEOUT_SECONDS = 60.0
MAX_RETRIES = 4

BLACKLISTED_DOMAINS = {
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "twitter.com",
    "x.com",
    "wikipedia.org",
    "creditexpo.nl",
    "yellowpages.com",
    "yelp.com",
}


def log(message: str) -> None:
    print(message, flush=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def decode_cfemail(encoded: str) -> str:
    if not encoded:
        return ""
    try:
        key = int(encoded[:2], 16)
        return "".join(chr(int(encoded[i : i + 2], 16) ^ key) for i in range(2, len(encoded), 2))
    except (ValueError, IndexError):
        return ""


def normalize_domain(raw: str) -> str:
    if not raw:
        return ""
    value = raw.strip()
    if not value:
        return ""
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
        value = "https://" + value.lstrip("/")
    host = urlparse(value).netloc.lower().removeprefix("www.")
    if not host or "." not in host:
        return ""
    return host


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def extract_stand_info(stand_text: str) -> tuple[str, str]:
    text = clean_text(stand_text)
    if not text:
        return "", ""
    match = re.match(r"Stand\s+(\d+)\s*-\s*(.+)$", text, re.I)
    if not match:
        return text, ""
    return f"Stand {match.group(1)}", clean_text(match.group(2))


def card_description(item: BeautifulSoup) -> str:
    content = item.select_one(".exhibitors-item__text.wysiwyg")
    if not content:
        return ""
    paragraphs = [clean_text(p.get_text(" ", strip=True)) for p in content.find_all("p")]
    paragraphs = [p for p in paragraphs if p]
    return "\n\n".join(paragraphs)


def parse_list_page(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    exhibitors: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for item in soup.select(".exhibitors-item"):
        name_el = item.select_one(".exhibitors-item__head .exhibitors-item__headline")
        stand_el = item.select_one(".exhibitors-item__head .exhibitors-item__stand-num")
        profile_el = item.select_one(".exhibitors-item__content-link a[href*='/dienstverlener/']")

        name = clean_text(name_el.get_text()) if name_el else ""
        profile_url = ""
        if profile_el and profile_el.get("href"):
            profile_url = profile_el["href"].split("?")[0]
            if not profile_url.endswith("/"):
                profile_url += "/"

        if not name or not profile_url or profile_url in seen_urls:
            continue
        seen_urls.add(profile_url)

        stand_text = clean_text(stand_el.get_text()) if stand_el else ""
        stand, partner_tier = extract_stand_info(stand_text)

        exhibitors.append(
            {
                "name": name,
                "desc": card_description(item),
                "email": "",
                "phone": "",
                "domain": "",
                "address": "",
                "city": "",
                "linkedin_url": "",
                "stand": stand,
                "partner_tier": partner_tier,
                "profile_url": profile_url,
                "postcode": "",
                "country": "",
            }
        )

    if not exhibitors:
        raise ValueError("No exhibitors found on the 2026 list page")
    return exhibitors


def table_value(soup: BeautifulSoup, label: str) -> str:
    for row in soup.select("table tr"):
        header = row.find("th")
        cell = row.find("td")
        if not header or not cell:
            continue
        if clean_text(header.get_text()).casefold() == label.casefold():
            email_el = cell.select_one("a.__cf_email__")
            if email_el and email_el.get("data-cfemail"):
                return decode_cfemail(email_el["data-cfemail"])
            mailto = cell.select_one('a[href^="mailto:"]')
            if mailto and mailto.get("href"):
                return clean_text(mailto["href"].replace("mailto:", ""))
            return clean_text(cell.get_text(" ", strip=True))
    return ""


def linkedin_from_profile(soup: BeautifulSoup) -> str:
    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "")
        if "linkedin.com" in href.lower() and "credit-expo" not in href.lower():
            return href.split("?")[0]
    return ""


def domain_from_description(desc: str) -> str:
    if not desc:
        return ""
    for match in re.finditer(r"(?:https?://)?(?:www\.)?([a-z0-9][a-z0-9.-]+\.[a-z]{2,})", desc, re.I):
        host = match.group(1).lower()
        if host not in BLACKLISTED_DOMAINS and "creditexpo" not in host:
            return host
    return ""


def parse_profile_page(html: str, record: dict[str, str]) -> dict[str, str]:
    soup = BeautifulSoup(html, "lxml")
    wysiwyg = soup.select_one(".post-content .wysiwyg")
    profile_desc = ""
    if wysiwyg:
        paragraphs = [clean_text(p.get_text(" ", strip=True)) for p in wysiwyg.find_all("p")]
        paragraphs = [p for p in paragraphs if p]
        profile_desc = "\n\n".join(paragraphs)

    street = table_value(soup, "Adres")
    postcode = table_value(soup, "Postcode")
    city = table_value(soup, "Plaats")
    country = table_value(soup, "Land")
    phone = table_value(soup, "Telefoon")
    email = table_value(soup, "E-mail")
    internet = table_value(soup, "Internet")
    company_name = table_value(soup, "Bedrijfsnaam")

    address_parts = [part for part in [street, postcode, city, country] if part]
    address = ", ".join(address_parts)

    record["name"] = company_name or record["name"]
    record["desc"] = profile_desc or record["desc"]
    record["email"] = email
    record["phone"] = phone
    record["domain"] = normalize_domain(internet) or domain_from_description(record["desc"])
    record["address"] = address
    record["city"] = city
    record["postcode"] = postcode
    record["country"] = country
    record["linkedin_url"] = linkedin_from_profile(soup)
    return record


async def request_text(client: httpx.AsyncClient, url: str) -> str:
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = await client.get(url)
            if response.status_code in {429, 500, 502, 503, 504}:
                wait = min(2**attempt, 16)
                log(f"  HTTP {response.status_code} for {url} — retry {attempt}/{MAX_RETRIES}")
                await asyncio.sleep(wait)
                continue
            response.raise_for_status()
            return response.text
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
            last_error = exc
            wait = min(2**attempt, 16)
            log(f"  Request failed ({type(exc).__name__}): {exc} — retry {attempt}/{MAX_RETRIES}")
            await asyncio.sleep(wait)
    raise RuntimeError(f"Failed after {MAX_RETRIES} retries: {url}") from last_error


class SerperEnricher:
    def __init__(self, api_key: str | None) -> None:
        self.api_key = api_key
        self.endpoint = "https://google.serper.dev/search"

    async def enrich(self, client: httpx.AsyncClient, record: dict[str, str]) -> dict[str, str]:
        if not self.api_key:
            return record
        if record.get("domain") and record.get("desc") and record.get("linkedin_url"):
            return record

        query = f'"{record["name"]}" official website {EVENT_YEAR}'
        headers = {"X-API-KEY": self.api_key, "Content-Type": "application/json"}
        payload = {"q": query, "num": 10}

        try:
            response = await client.post(self.endpoint, headers=headers, json=payload, timeout=20.0)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            log(f"  Serper failed for {record['name']}: {exc}")
            return record

        organic = data.get("organic", [])
        knowledge = data.get("knowledgeGraph") or {}

        if not record.get("domain"):
            website = knowledge.get("website")
            if website:
                record["domain"] = normalize_domain(website)
            if not record.get("domain"):
                for item in organic:
                    link = item.get("link", "")
                    domain = normalize_domain(link)
                    if not domain:
                        continue
                    if any(blocked in domain for blocked in BLACKLISTED_DOMAINS):
                        continue
                    record["domain"] = domain
                    break

        if not record.get("desc"):
            snippet = knowledge.get("description")
            if snippet:
                record["desc"] = clean_text(snippet)
            elif organic:
                record["desc"] = clean_text(organic[0].get("snippet", ""))

        if not record.get("linkedin_url"):
            for item in organic:
                link = item.get("link", "")
                if "linkedin.com/company" in link.lower() or "linkedin.com/in/" in link.lower():
                    record["linkedin_url"] = link.split("?")[0]
                    break

        return record


async def scrape(concurrency: int, enrich: bool) -> list[dict[str, str]]:
    timeout = httpx.Timeout(TIMEOUT_SECONDS)
    limits = httpx.Limits(max_connections=concurrency + 4, max_keepalive_connections=concurrency)
    semaphore = asyncio.Semaphore(concurrency)

    load_dotenv(ROOT_DIR.parent / ".env")
    serper = SerperEnricher(os.getenv("SERPER_API_KEY"))

    async with httpx.AsyncClient(
        headers=HEADERS,
        timeout=timeout,
        limits=limits,
        follow_redirects=True,
    ) as client:
        log("[1/4] Fetching Credit Expo 2026 exhibitor list...")
        list_html = await request_text(client, LIST_URL)
        exhibitors = parse_list_page(list_html)
        log(f"Found {len(exhibitors)} exhibitors on 2026 list page")

        log(f"[2/4] Opening {len(exhibitors)} exhibitor profile pages...")

        async def load_profile(record: dict[str, str]) -> dict[str, str]:
            async with semaphore:
                html = await request_text(client, record["profile_url"])
            return parse_profile_page(html, record)

        tasks = [load_profile(record) for record in exhibitors]
        records: list[dict[str, str]] = []
        completed = 0
        for coro in asyncio.as_completed(tasks):
            records.append(await coro)
            completed += 1
            if completed % 5 == 0 or completed == len(tasks):
                log(f"Profiles scraped: {completed}/{len(tasks)}")

        missing_domains = [row for row in records if not row.get("domain")]
        if enrich and missing_domains:
            log(f"[3/4] Enriching {len(missing_domains)} exhibitors with Serper...")
            enriched = 0
            for row in records:
                if row.get("domain"):
                    continue
                row.update(await serper.enrich(client, row))
                if row.get("domain"):
                    enriched += 1
            log(f"Serper resolved domains for {enriched}/{len(missing_domains)} exhibitors")
        else:
            log("[3/4] Skipping Serper enrichment")

    records.sort(key=lambda row: row["name"].casefold())
    return records


def write_outputs(records: list[dict[str, str]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "event": "Credit Expo",
        "year": EVENT_YEAR,
        "source": LIST_URL,
        "scraped_at": utc_now(),
        "total": len(records),
        "with_domain": sum(1 for row in records if row["domain"]),
        "without_domain": sum(1 for row in records if not row["domain"]),
        "exhibitors": records,
    }
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in records:
            writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})


def print_summary(records: list[dict[str, str]]) -> None:
    with_domain = sum(1 for row in records if row["domain"])
    with_email = sum(1 for row in records if row["email"])
    with_phone = sum(1 for row in records if row["phone"])
    log("")
    log("[4/4] Results")
    log(f"Exhibitors: {len(records)}")
    log(f"Domains: {with_domain}")
    log(f"Emails: {with_email}")
    log(f"Phones: {with_phone}")
    log("")
    log("Saved:")
    log(f"  CSV:  {CSV_PATH}")
    log(f"  JSON: {JSON_PATH}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape Credit Expo 2026 exhibitors")
    parser.add_argument("--concurrency", type=int, default=HTTP_CONCURRENCY)
    parser.add_argument("--no-enrich", action="store_true", help="Skip Serper domain enrichment")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        records = asyncio.run(scrape(concurrency=args.concurrency, enrich=not args.no_enrich))
    except KeyboardInterrupt:
        log("Interrupted.")
        return 130
    except Exception as exc:
        log(f"Scrape failed: {exc}")
        return 1

    write_outputs(records)
    print_summary(records)
    return 0


if __name__ == "__main__":
    sys.exit(main())
