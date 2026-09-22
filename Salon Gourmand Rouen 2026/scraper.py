"""Scrape the exhibitors shown in the official Salon Gourmand Rouen 2026 section."""

from __future__ import annotations

import asyncio
import csv
import html
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from playwright.async_api import async_playwright

EVENT_NAME = "Salon Gourmand Rouen"
EVENT_YEAR = "2026"
SOURCE_URL = "https://www.salongourmandrouen.com/presentation/"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
CSV_PATH = OUTPUT / "SALON_GOURMAND_ROUEN_2026_exhibitors.csv"
PROFILE_HOST = "salongourmandrouen.com"
BLOCKED_HOSTS = {
    PROFILE_HOST, "facebook.com", "instagram.com", "linkedin.com",
    "twitter.com", "x.com", "youtube.com", "cleantalk.org",
}
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "name", "desc", "email", "phone", "address", "city", "linkedin_url",
    "profile_url", "source_year", "category", "source_url",
]
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/151.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}
GENERIC_EMAIL_HOSTS = {"gmail.com", "hotmail.com", "outlook.com", "yahoo.com"}


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "").replace("\xa0", " ")).strip()


def root_domain(value: str) -> str:
    value = clean(value)
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


def parse_listing(page_html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(page_html, "html.parser")
    records = []
    seen = set()
    for card in soup.find_all("div", class_="uael-post-wrapper"):
        title = card.find("h4", class_="uael-post__title")
        anchor = title.find("a", href=True) if title else None
        name = clean(anchor.get_text(" ", strip=True) if anchor else "")
        profile_url = urljoin(SOURCE_URL, anchor["href"]) if anchor else ""
        if not name or profile_url in seen:
            continue
        seen.add(profile_url)
        category = " ".join(
            value for value in card.get("class", [])
            if value not in {"uael-post-wrapper", "uael-post__wrapper"}
        )
        excerpt = card.find("div", class_="uael-post__excerpt")
        records.append({
            "exhibitor_name": name,
            "domain": "",
            "contact_number": "",
            "mail": "",
            "location": "Rouen, Normandy, France",
            "country": "France",
            "name": name,
            "desc": clean(excerpt.get_text(" ", strip=True) if excerpt else ""),
            "email": "",
            "phone": "",
            "address": "",
            "city": "Rouen",
            "linkedin_url": "",
            "profile_url": profile_url,
            "source_year": EVENT_YEAR,
            "category": category,
            "source_url": SOURCE_URL,
        })
    if not records:
        raise RuntimeError("No exhibitors found in the 2026 section")
    return records


def parse_profile(record: dict[str, str], profile_html: str) -> None:
    soup = BeautifulSoup(profile_html, "html.parser")
    description = soup.find("meta", attrs={"property": "og:description"})
    if description and description.get("content"):
        record["desc"] = clean(description["content"])
    content = soup.find("article") or soup.find("main") or soup
    body = clean(content.get_text(" ", strip=True))
    emails = [
        clean(a.get("href", "")[7:].split("?", 1)[0])
        for a in soup.find_all("a", href=True)
        if a.get("href", "").lower().startswith("mailto:")
    ]
    email_match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", body)
    record["mail"] = next((email for email in emails if email), "") or (
        email_match.group(0) if email_match else ""
    )
    phone = next(
        (
            clean(a.get("href", "")[4:])
            for a in soup.find_all("a", href=True)
            if a.get("href", "").lower().startswith("tel:")
        ),
        "",
    )
    if not phone:
        match = re.search(r"(?:\+|00)?\d[\d\s()./-]{7,}\d", body)
        phone = clean(match.group(0)) if match else ""
    record["contact_number"] = phone
    record["address"] = clean(
        soup.find("address").get_text(" ", strip=True)
        if soup.find("address") else ""
    )
    external_links = [
        a.get("href", "") for a in soup.find_all("a", href=True)
        if root_domain(a.get("href", ""))
    ]
    record["domain"] = next((root_domain(link) for link in external_links), "")
    record["linkedin_url"] = next(
        (link for link in soup.find_all("a", href=True)
         for link in [link.get("href", "")]
         if "linkedin.com" in link.lower()),
        "",
    )
    record["email"] = record["mail"]
    record["phone"] = record["contact_number"]
    if record["address"]:
        record["location"] = record["address"]


async def scrape_profiles(records: list[dict[str, str]]) -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(
            locale="fr-FR", user_agent=HEADERS["User-Agent"]
        )
        semaphore = asyncio.Semaphore(3)

        async def visit(record: dict[str, str]) -> None:
            async with semaphore:
                page = await context.new_page()
                try:
                    await page.goto(
                        record["profile_url"],
                        wait_until="domcontentloaded",
                        timeout=60000,
                    )
                    await page.wait_for_timeout(3500)
                    parse_profile(record, await page.content())
                except Exception as exc:
                    print(f"Profile unavailable: {record['exhibitor_name']} ({exc})")
                finally:
                    await page.close()

        await asyncio.gather(*(visit(record) for record in records))
        await browser.close()


def serper_fallback(records: list[dict[str, str]], api_key: str) -> None:
    if not api_key:
        return
    session = requests.Session()
    session.headers.update(HEADERS)
    for record in records:
        if record["domain"]:
            continue
        query = f'"{record["exhibitor_name"]}" official website {EVENT_YEAR} Rouen'
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
        record["domain"] = root_domain(knowledge.get("website", ""))
        if not record["domain"]:
            for result in data.get("organic", []):
                candidate = root_domain(result.get("link", ""))
                if candidate:
                    record["domain"] = candidate
                    break
        if not record["contact_number"]:
            record["contact_number"] = clean(knowledge.get("phone", ""))
        if not record["address"]:
            record["address"] = clean(knowledge.get("address", ""))
        record["email"] = record["mail"]
        record["phone"] = record["contact_number"]


def write_csv(records: list[dict[str, str]]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(sorted(records, key=lambda row: row["exhibitor_name"].casefold()))


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    response = requests.get(SOURCE_URL, headers=HEADERS, timeout=45)
    response.raise_for_status()
    records = parse_listing(response.text)
    asyncio.run(scrape_profiles(records))
    serper_fallback(records, os.getenv("SERPER_API_KEY", ""))
    write_csv(records)
    print(f"Saved {len(records)} exhibitors to {CSV_PATH}")
    print(f"Scraped at {datetime.now(timezone.utc).isoformat()}")


if __name__ == "__main__":
    main()
