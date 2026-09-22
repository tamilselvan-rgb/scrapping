"""Scrape the official Haus & Bau 2026 exhibitor directory."""

from __future__ import annotations

import asyncio
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
from playwright.async_api import async_playwright

EVENT_NAME = "Haus & Bau"
EVENT_YEAR = "2026"
SOURCE_URL = "https://www.hausundbau.at/ausstellerverzeichnis/"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
CSV_PATH = OUTPUT / "HAUS_BAU_2026_exhibitors.csv"
JSON_PATH = OUTPUT / "HAUS_BAU_2026_exhibitors.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/151.0 Safari/537.36"
    ),
    "Accept-Language": "de-AT,de;q=0.9,en;q=0.8",
}
BLOCKED_HOSTS = {
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com",
    "hausundbau.at", "messe-ried.at",
}
CSV_FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "name", "desc", "email", "phone", "address", "city", "linkedin_url",
    "profile_url", "source_year", "postal_code", "categories", "source_url",
]
COUNTRIES = {
    "AT": "Austria", "DE": "Germany", "CZ": "Czech Republic",
}
GENERIC_EMAIL_HOSTS = {
    "gmail.com", "gmx.at", "gmx.de", "hotmail.com", "outlook.com", "yahoo.com",
}


def clean(value: str) -> str:
    value = html.unescape(value or "").replace("\xa0", " ")
    value = value.replace("\ufffd", "–")
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
    if any(host == blocked or host.endswith("." + blocked) for blocked in BLOCKED_HOSTS):
        return ""
    return host


def country_name(code: str) -> str:
    return COUNTRIES.get(clean(code).upper().split("-")[0].strip(), "")


async def load_directory() -> str:
    """Expand the official directory's load-more control and return its HTML."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(locale="de-AT", user_agent=HEADERS["User-Agent"])
        await page.goto(SOURCE_URL + "?nowprocket=1", wait_until="networkidle", timeout=90000)
        last_count = 0
        stalled_clicks = 0
        for _ in range(20):
            count = await page.locator(
                ".jet-listing-grid--330 .jet-listing-grid__item"
            ).count()
            button = page.locator("#mehr")
            if count >= 120 or not await button.is_visible():
                break
            await button.evaluate("(element) => element.click()")
            try:
                await page.wait_for_function(
                    "(old) => document.querySelectorAll("
                    "'.jet-listing-grid--330 .jet-listing-grid__item').length > old",
                    count,
                    timeout=25000,
                )
            except Exception:
                await page.wait_for_timeout(8000)
            new_count = await page.locator(
                ".jet-listing-grid--330 .jet-listing-grid__item"
            ).count()
            if new_count == count:
                stalled_clicks += 1
                if stalled_clicks >= 3:
                    break
            else:
                stalled_clicks = 0
            last_count = new_count
        final_count = await page.locator(
            ".jet-listing-grid--330 .jet-listing-grid__item"
        ).count()
        if final_count < 120:
            raise RuntimeError(f"Expected at least 120 exhibitors, found {final_count}")
        content = await page.content()
        await browser.close()
        return content


def parse_cards(page_html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(page_html, "html.parser")
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for card in soup.find_all("div", class_="jet-listing-grid__item"):
        if not any(
            cls.startswith("jet-listing-dynamic-post-")
            for cls in card.get("class", [])
        ):
            continue
        headings = card.find_all("h3")
        if not headings:
            continue
        name = clean(headings[0].get_text(" ", strip=True))
        if not name or name in seen:
            continue
        seen.add(name)
        paragraphs = [clean(p.get_text(" ", strip=True)) for p in card.find_all("p")]
        paragraphs = [value for value in paragraphs if value]
        code = paragraphs[0].split("-", 1)[0].strip() if paragraphs else ""
        postal_code = paragraphs[1] if len(paragraphs) > 1 else ""
        city = paragraphs[2] if len(paragraphs) > 2 else ""
        website = next(
            (a.get("href", "") for a in card.find_all("a", href=True)
             if normalize_domain(a.get("href", ""))),
            "",
        )
        terms = card.find("div", class_="jet-listing-dynamic-terms")
        categories = clean(terms.get_text(" ", strip=True)) if terms else ""
        description = categories
        location = ", ".join(part for part in [postal_code, city] if part)
        records.append({
            "exhibitor_name": name,
            "domain": normalize_domain(website),
            "contact_number": "",
            "mail": "",
            "location": location,
            "country": country_name(code),
            "name": name,
            "desc": description,
            "email": "",
            "phone": "",
            "address": "",
            "city": city,
            "linkedin_url": "",
            "profile_url": f"{SOURCE_URL}#exhibitor-{name.casefold().replace(' ', '-')}",
            "source_year": EVENT_YEAR,
            "postal_code": postal_code,
            "categories": categories,
            "source_url": SOURCE_URL,
        })
    if len(records) != 120:
        raise RuntimeError(f"Expected 120 unique 2026 exhibitors, found {len(records)}")
    return records


def extract_contacts(session: requests.Session, record: dict[str, str]) -> None:
    domain = record["domain"]
    if not domain:
        return
    candidates = [
        f"https://{domain}/", f"https://{domain}/kontakt/",
        f"https://{domain}/contact/", f"https://{domain}/impressum/",
        f"https://{domain}/about/",
    ]
    visited: set[str] = set()
    for url in candidates:
        if url in visited:
            continue
        visited.add(url)
        try:
            response = session.get(url, timeout=15, allow_redirects=True)
            if response.status_code >= 400:
                continue
        except requests.RequestException:
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        body = clean(soup.get_text(" ", strip=True))
        if not record["mail"]:
            mail = next(
                (a.get("href", "")[7:].split("?", 1)[0] for a in soup.find_all(
                    "a", href=True) if a.get("href", "").lower().startswith("mailto:")),
                "",
            )
            match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", body)
            record["mail"] = clean(mail or (match.group(0) if match else ""))
        if not record["contact_number"]:
            tel = next(
                (a.get("href", "")[4:] for a in soup.find_all(
                    "a", href=True) if a.get("href", "").lower().startswith("tel:")),
                "",
            )
            match = re.search(r"(?:\+|00)?\d[\d\s()./-]{7,}\d", body)
            record["contact_number"] = clean(tel or (match.group(0) if match else ""))
        if not record["address"]:
            address = soup.find("address")
            if address:
                record["address"] = clean(address.get_text(" ", strip=True))
        if not record["linkedin_url"]:
            linkedin = next(
                (a.get("href", "") for a in soup.find_all("a", href=True)
                 if "linkedin.com" in a.get("href", "").lower()),
                "",
            )
            record["linkedin_url"] = linkedin
        if not record["mail"] or not record["contact_number"] or not record["address"]:
            for link in soup.find_all("a", href=True):
                href = urljoin(response.url, link["href"])
                label = clean(link.get_text(" ", strip=True)).lower()
                if ("contact" in label or "kontakt" in label or "impressum" in label) and urlparse(href).netloc == urlparse(response.url).netloc:
                    candidates.append(href)
        if record["mail"] and record["contact_number"] and record["address"]:
            break
    record["email"] = record["mail"]
    record["phone"] = record["contact_number"]
    if record["address"]:
        record["location"] = record["address"]


def serper_enrich(session: requests.Session, record: dict[str, str], api_key: str) -> None:
    if not api_key or record["domain"]:
        return
    query = f'"{record["exhibitor_name"]}" official website {record["city"]} {EVENT_YEAR}'
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
        return
    knowledge = data.get("knowledgeGraph") or {}
    record["domain"] = normalize_domain(knowledge.get("website", ""))
    if not record["domain"]:
        for result in data.get("organic", []):
            candidate = normalize_domain(result.get("link", ""))
            if candidate:
                record["domain"] = candidate
                break
    if not record["contact_number"]:
        record["contact_number"] = clean(knowledge.get("phone", ""))
    if not record["address"]:
        record["address"] = clean(knowledge.get("address", ""))
    record["email"] = record["mail"]
    record["phone"] = record["contact_number"]
    if record["address"]:
        record["location"] = record["address"]


def enrich_one(record: dict[str, str], api_key: str) -> dict[str, str]:
    session = requests.Session()
    session.headers.update(HEADERS)
    serper_enrich(session, record, api_key)
    extract_contacts(session, record)
    return record


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
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(records)


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    page_html = asyncio.run(load_directory())
    records = parse_cards(page_html)
    api_key = os.getenv("SERPER_API_KEY", "")
    with ThreadPoolExecutor(max_workers=8) as executor:
        jobs = [executor.submit(enrich_one, record, api_key) for record in records]
        for index, job in enumerate(as_completed(jobs), 1):
            job.result()
            if index % 10 == 0 or index == len(records):
                print(f"Enriched {index}/{len(records)} exhibitors", flush=True)
    records.sort(key=lambda row: row["exhibitor_name"].casefold())
    write_outputs(records)
    print(f"Saved {len(records)} exhibitors")
    print(CSV_PATH)
    print(JSON_PATH)


if __name__ == "__main__":
    main()
