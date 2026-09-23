"""Scrape all events listed in Expomap's English country directory."""

from __future__ import annotations

import asyncio
import csv
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup


BASE = "https://expomap.ru"
INDEX_URL = f"{BASE}/en/expo/country/"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "expomap.csv"
CHECKPOINT = ROOT / "expomap_checkpoint.json"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
FIELDS = [
    "s_no",
    "event_name",
    "domain",
    "website_url",
    "start_date",
    "end_date",
    "venue",
    "hall",
    "city",
    "country",
    "instagram_url",
    "event_page_url",
]


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def country_name(text: str) -> str:
    text = re.sub(r"\s*\(\s*\d+\s*\)\s*$", "", clean(text))
    return {
        "Эфиопия": "Ethiopia",
        "США": "United States",
        "USA": "United States",
        "ОАЭ": "United Arab Emirates",
        "Германия": "Germany",
        "Россия": "Russia",
        "Руанда": "Rwanda",
        "Новая Зеландия": "New Zealand",
        "Франция": "France",
        "Польша": "Poland",
        "Казахстан": "Kazakhstan",
        "Кения": "Kenya",
        "Китай": "China",
        "Греция": "Greece",
        "Турция": "Turkey",
        "Испания": "Spain",
        "Узбекистан": "Uzbekistan",
        "Индонезия": "Indonesia",
        "Южно-Африканская Республика": "South Africa",
        "Австрия": "Austria",
        "Таиланд": "Thailand",
    }.get(text, text)


def root_domain(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.hostname or "").lower().removeprefix("www.")
    return host


def date_only(value: object) -> str:
    value = clean(value)
    return value[:10] if re.match(r"\d{4}-\d{2}-\d{2}", value) else value


def detail_links(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    result = []
    seen = set()
    event_prefixes = ("/en/expo/", "/en/conference/", "/en/webinar/")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        for item in data if isinstance(data, list) else [data]:
            if item.get("@type") != "Event" or not item.get("url"):
                continue
            url = urljoin(BASE, item["url"]).split("?")[0].rstrip("/") + "/"
            if (
                any(prefix in url for prefix in event_prefixes)
                and "/country/" not in url
                and url not in seen
            ):
                seen.add(url)
                result.append(url)
    # The JSON-LD is normally sufficient; this catches events without it.
    for anchor in soup.find_all("a", href=True):
        href = urljoin(BASE, anchor["href"]).split("?")[0].rstrip("/") + "/"
        if (
            any(prefix in href for prefix in event_prefixes)
            and "/country/" not in href
            and "/tag/" not in href
            and href not in seen
            and clean(anchor.get_text(" ", strip=True)).lower() in {"details", "detail"}
        ):
            seen.add(href)
            result.append(href)
    return result


def country_links(html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    pattern = re.compile(r"^/en/expo/country/[a-z0-9_-]+/?$")
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if pattern.match(href):
            found[href.rstrip("/") + "/"] = country_name(anchor.get_text(" ", strip=True))
    return list(found.items())


def max_page(html: str, base_url: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    max_seen = 1
    for anchor in soup.find_all("a", href=True):
        href = urljoin(BASE, anchor["href"])
        if href.split("?")[0].rstrip("/") == base_url.rstrip("/"):
            match = re.search(r"[?&]page=(\d+)", href)
            if match:
                max_seen = max(max_seen, int(match.group(1)))
    # Some pages do not render the final pagination links in the server HTML.
    # Event cards are paginated in batches of 12, so the visible total gives
    # us a reliable lower bound for the number of pages to request.
    match = re.search(r"\bFound\s+([\d,]+)\s+events?\b", soup.get_text(" ", strip=True), re.I)
    if match:
        total = int(match.group(1).replace(",", ""))
        max_seen = max(max_seen, (total + 11) // 12)
    return max_seen


def flight_event(html: str) -> dict:
    """Read the event object embedded in the Next.js flight payload."""
    marker_at = html.rfind("eventPageStore")
    if marker_at < 0:
        return {}
    try:
        push_at = html.rfind("self.__next_f.push(", 0, marker_at)
        list_start = html.find("[", push_at)
        payload, _ = json.JSONDecoder().raw_decode(html, list_start)
        text = payload[1] if isinstance(payload, list) and len(payload) > 1 else ""
        event_at = text.find('"event":{')
        event, _ = json.JSONDecoder().raw_decode(text[event_at + len('"event":') :])
        return event if isinstance(event, dict) else {}
    except json.JSONDecodeError:
        return {}


def official_website(soup: BeautifulSoup) -> str:
    for anchor in soup.find_all("a", href=True):
        label = clean(anchor.get_text(" ", strip=True)).lower()
        href = anchor["href"].strip()
        if (
            href.startswith(("http://", "https://"))
            and "expomap." not in urlparse(href).netloc.lower()
            and ("official" in label or "site" in label or "website" in label)
        ):
            return href
    # Detail pages use the exact label in the current site version.
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if href.startswith(("http://", "https://")) and "expomap." not in href:
            if "official" in clean(anchor.parent.get_text(" ", strip=True)).lower():
                return href
    return ""


def parse_detail(html: str, url: str, fallback_country: str = "") -> dict:
    soup = BeautifulSoup(html, "html.parser")
    data = flight_event(html)
    location = data.get("location") or {}
    place = location.get("place") or {}
    address = place.get("address") or {}
    city = clean((location.get("city") or {}).get("name"))
    country = country_name(
        clean((location.get("country") or {}).get("name")) or fallback_country
    )
    website = official_website(soup)
    if not website:
        website = clean(data.get("web_page_url"))
    if not website:
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            if href.startswith(("http://", "https://")) and "expomap." not in href:
                if not any(x in href.lower() for x in ("telegram", "facebook", "vk.com", "youtube")):
                    website = href
                    break

    instagram = ""
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if "instagram.com" in href.lower():
            instagram = href
            break

    # Expomap currently gives a venue/place but not a separate hall field.
    venue = clean(place.get("name"))
    if not venue:
        venue = clean((location.get("place_alt") or ""))
    return {
        "event_name": clean(data.get("title")) or clean((soup.find("h1") or {}).get_text(" ", strip=True)),
        "domain": root_domain(website),
        "website_url": website,
        "start_date": date_only(data.get("date_start")),
        "end_date": date_only(data.get("date_end")),
        "venue": venue,
        "hall": "",
        "city": city,
        "country": country,
        "instagram_url": instagram,
        "event_page_url": url,
    }


async def fetch(client: httpx.AsyncClient, url: str) -> str:
    for attempt in range(5):
        try:
            response = await client.get(url)
            response.raise_for_status()
            return response.text
        except (httpx.HTTPError, UnicodeError):
            if attempt == 4:
                return ""
            await asyncio.sleep(min(12, 1.5 * (2**attempt)))
    return ""


async def crawl() -> None:
    limits = httpx.Limits(max_connections=18, max_keepalive_connections=10)
    timeout = httpx.Timeout(45.0, connect=20.0)
    async with httpx.AsyncClient(
        headers=HEADERS, follow_redirects=True, timeout=timeout, limits=limits
    ) as client:
        index = await fetch(client, INDEX_URL)
        countries = country_links(index)
        if not countries:
            raise RuntimeError("No country links found")
        print(f"Countries discovered: {len(countries)}")

        # Fetch the first page for every country concurrently. This also
        # reveals the highest pagination number for each country.
        country_semaphore = asyncio.Semaphore(12)

        async def first_country_page(country_url: str, country: str):
            async with country_semaphore:
                url = urljoin(BASE, country_url)
                html = await fetch(client, url)
                return country_url, country, html, max_page(html, url)

        listing_jobs = list(
            await asyncio.gather(
                *(first_country_page(url, country) for url, country in countries)
            )
        )
        print(f"Country listings discovered; max pages: {max(x[3] for x in listing_jobs)}")

        listing_urls = []
        listing_html = {}
        for country_url, country, first, pages in listing_jobs:
            for page in range(1, pages + 1):
                url = urljoin(BASE, country_url)
                if page > 1:
                    url += f"?page={page}"
                listing_urls.append((url, country))
                if page == 1:
                    listing_html[url] = first
        pending = [(url, country) for url, country in listing_urls if url not in listing_html]
        results = await asyncio.gather(
            *(fetch(client, url) for url, _ in pending), return_exceptions=True
        )
        for (url, _), html in zip(pending, results):
            if isinstance(html, str):
                listing_html[url] = html

        event_meta: dict[str, list[str]] = {}
        for listing_url, country in listing_urls:
            for event_url in detail_links(listing_html.get(listing_url, "")):
                event_meta.setdefault(event_url, []).append(country)
        occurrence_count = sum(len(countries) for countries in event_meta.values())
        print(
            f"Unique event pages discovered: {len(event_meta)}; "
            f"category occurrences: {occurrence_count}"
        )

        checkpoint = {}
        if CHECKPOINT.exists():
            try:
                checkpoint = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                checkpoint = {}
        todo = [
            (url, countries[0])
            for url, countries in event_meta.items()
            if url not in checkpoint
        ]
        completed = len(checkpoint)
        semaphore = asyncio.Semaphore(18)

        async def one(url: str, country: str) -> tuple[str, dict]:
            async with semaphore:
                html = await fetch(client, url)
            return url, parse_detail(html, url, country) if html else {}

        for offset in range(0, len(todo), 250):
            batch = todo[offset : offset + 250]
            for url, row in await asyncio.gather(*(one(*item) for item in batch)):
                if row:
                    checkpoint[url] = row
            completed += len(batch)
            CHECKPOINT.write_text(json.dumps(checkpoint, ensure_ascii=False), encoding="utf-8")
            print(f"Details scraped: {min(completed, len(event_meta))}/{len(event_meta)}")

    rows = []
    for url, countries in event_meta.items():
        base_row = checkpoint.get(url)
        if not base_row:
            continue
        for category_country in countries:
            row = dict(base_row)
            row["country"] = country_name(category_country) or row.get("country", "")
            rows.append(row)
    rows.sort(key=lambda row: (row.get("start_date", ""), row.get("event_name", "").lower()))
    with OUTPUT.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for number, row in enumerate(rows, 1):
            writer.writerow({"s_no": number, **row})
    print(f"Wrote {len(rows)} rows to {OUTPUT}")


if __name__ == "__main__":
    asyncio.run(crawl())
