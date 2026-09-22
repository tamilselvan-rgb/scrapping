#!/usr/bin/env python3
"""
Vendelux November 2026 Upcoming Events Scraper.

Extracts all upcoming B2B events from Vendelux for November 2026:
- Traverses Listing -> Attendee List -> App Event Page
- Extracts: event_name, event_start_date, event_end_, venue, city, country, event_domain
- Saves incrementally to CSV with resume support.
"""

import argparse
import asyncio
import csv
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession

# Fix Windows event loop policy for asyncio
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

ROOT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT_DIR / "output"
DEFAULT_OUTPUT_CSV = OUTPUT_DIR / "vendelux_november_2026_events.csv"
START_URL = "https://vendelux.com/b2b-events/november-2026"

CSV_COLUMNS = [
    "event_name",
    "event_start_date",
    "event_end_",
    "venue",
    "city",
    "country",
    "event_domain",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("vendelux")


def extract_domain(url: str) -> str:
    """Extract clean domain from URL, ignoring vendelux.com internal links."""
    if not url or not str(url).strip():
        return ""
    val = str(url).strip()
    if not val.startswith(("http://", "https://")):
        val = "https://" + val.lstrip("/")
    try:
        parsed = urlparse(val)
        host = (parsed.netloc or parsed.path.split("/")[0]).lower()
        if host.startswith("www."):
            host = host[4:]
        dom = host.split(":")[0].strip()
        if "vendelux.com" in dom or not dom or "." not in dom:
            return ""
        return dom
    except Exception:
        return ""


def parse_listing_date_loc(date_loc_str: str) -> tuple[str, str, str, str]:
    """
    Parse duration and location string from listing page.
    Example: 'Nov 1 to 4, 2026 · San Antonio, United States'
    Returns: (start_date, end_date, city, country)
    """
    parts = [p.strip() for p in date_loc_str.split("·") if p.strip()]
    date_part = parts[0] if len(parts) > 0 else ""
    loc_part = parts[1] if len(parts) > 1 else ""

    city, country = "", ""
    if loc_part:
        loc_sub = [s.strip() for s in loc_part.split(",") if s.strip()]
        if len(loc_sub) >= 2:
            city = loc_sub[0]
            country = loc_sub[-1]
        elif len(loc_sub) == 1:
            country = loc_sub[0]

    # Attempt to parse date ranges like "Nov 1 to 4, 2026" or "Nov 1, 2026"
    start_date, end_date = "", ""
    month_map = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
    }
    try:
        # Pattern: Nov 1 to 4, 2026
        m_range = re.search(r"([A-Za-z]+)\s+(\d+)\s+to\s+(\d+),\s+(\d{4})", date_part)
        if m_range:
            m_str, d1, d2, y = m_range.groups()
            m_num = month_map.get(m_str.lower()[:3], 11)
            start_date = f"{y}-{m_num:02d}-{int(d1):02d}"
            end_date = f"{y}-{m_num:02d}-{int(d2):02d}"
        else:
            # Pattern: Nov 1, 2026
            m_single = re.search(r"([A-Za-z]+)\s+(\d+),\s+(\d{4})", date_part)
            if m_single:
                m_str, d1, y = m_single.groups()
                m_num = month_map.get(m_str.lower()[:3], 11)
                start_date = f"{y}-{m_num:02d}-{int(d1):02d}"
                end_date = start_date
    except Exception:
        pass

    return start_date, end_date, city, country


async def fetch_with_retry(session: AsyncSession, url: str, max_retries: int = 3) -> Optional[str]:
    """Fetch URL with exponential backoff on temporary errors."""
    for attempt in range(1, max_retries + 1):
        try:
            r = await session.get(url)
            if r.status_code == 200:
                return r.text
            elif r.status_code in (429, 500, 502, 503):
                logger.warning(f"HTTP {r.status_code} on {url} (attempt {attempt}/{max_retries})")
                await asyncio.sleep(attempt * 2)
            else:
                logger.warning(f"HTTP {r.status_code} for {url}")
                return None
        except Exception as e:
            if attempt == max_retries:
                logger.debug(f"Failed to fetch {url} after {max_retries} attempts: {e}")
                return None
            await asyncio.sleep(attempt * 1.5)
    return None


async def scrape_event_details(
    session: AsyncSession,
    attendee_url: str,
    fallback_start: str,
    fallback_end: str,
    fallback_city: str,
    fallback_country: str,
) -> Dict[str, str]:
    """
    Hop 1: Fetch attendee list page to find 'View event insights' app URL.
    Hop 2: Fetch app event page to extract JSON-LD structured data and website.
    """
    result = {
        "event_start_date": fallback_start,
        "event_end_": fallback_end,
        "venue": "",
        "city": fallback_city,
        "country": fallback_country,
        "event_domain": "",
    }

    # Hop 1: Attendee list page
    html_att = await fetch_with_retry(session, attendee_url)
    if not html_att:
        return result

    soup_att = BeautifulSoup(html_att, "lxml")
    app_url = None
    for a in soup_att.find_all("a"):
        href = a.get("href", "")
        if "/app/event/" in href or "view event insights" in a.get_text().lower():
            app_url = href
            break

    if not app_url:
        return result

    # Hop 2: App event page
    html_app = await fetch_with_retry(session, app_url)
    if not html_app:
        return result

    soup_app = BeautifulSoup(html_app, "lxml")
    event_data = None
    for s in soup_app.find_all("script", type="application/ld+json"):
        try:
            d = json.loads(s.string)
            if isinstance(d, dict) and d.get("@type") == "Event":
                event_data = d
                break
        except Exception:
            pass

    if event_data:
        if event_data.get("startDate"):
            result["event_start_date"] = str(event_data.get("startDate"))[:10]
        if event_data.get("endDate"):
            result["event_end_"] = str(event_data.get("endDate"))[:10]

        loc = event_data.get("location")
        if isinstance(loc, dict):
            if loc.get("name"):
                result["venue"] = str(loc.get("name")).strip()
            addr = loc.get("address")
            if isinstance(addr, dict):
                if addr.get("addressLocality"):
                    result["city"] = str(addr.get("addressLocality")).strip()
                if addr.get("addressCountry"):
                    result["country"] = str(addr.get("addressCountry")).strip()

        website = event_data.get("url", "")
        dom = extract_domain(website)
        if dom:
            result["event_domain"] = dom

    # Secondary fallback for website if not found in JSON-LD
    if not result["event_domain"]:
        for a in soup_app.find_all("a"):
            txt = a.get_text().strip().lower()
            if "visit event website" in txt or "event website" in txt:
                dom = extract_domain(a.get("href", ""))
                if dom:
                    result["event_domain"] = dom
                    break

    return result


async def main():
    parser = argparse.ArgumentParser(description="Vendelux November 2026 Upcoming Events Scraper")
    parser.add_argument("--output", "-o", default=str(DEFAULT_OUTPUT_CSV), help="Output CSV path")
    parser.add_argument("--concurrency", "-c", type=int, default=6, help="Concurrent workers (default: 6)")
    parser.add_argument("--limit", "-l", type=int, default=0, help="Limit number of events (0 = all)")
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Check for existing completed events to support resume
    completed_events = set()
    file_exists = output_path.exists() and output_path.stat().st_size > 0
    if file_exists:
        try:
            with output_path.open("r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get("event_name", "").strip()
                    if name:
                        completed_events.add(name)
            logger.info(f"Resume active: Found {len(completed_events)} previously scraped events in {output_path.name}.")
        except Exception as e:
            logger.warning(f"Could not read existing CSV for resume: {e}")

    # Initialize CSV file with headers if not existing
    csv_file = output_path.open("a", newline="", encoding="utf-8-sig")
    csv_writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
    if not file_exists:
        csv_writer.writeheader()
        csv_file.flush()

    write_lock = asyncio.Lock()

    async with AsyncSession(impersonate="chrome120", timeout=35) as session:
        logger.info(f"Fetching listing page: {START_URL}")
        r_start = await session.get(START_URL)
        if r_start.status_code != 200:
            logger.error(f"Failed to fetch {START_URL} (status {r_start.status_code})")
            csv_file.close()
            return 1

        soup = BeautifulSoup(r_start.text, "lxml")
        upcoming_h2 = soup.find(lambda tag: tag.name == "h2" and "Upcoming events" in tag.get_text())
        if not upcoming_h2:
            logger.error("Could not locate 'Upcoming events' section on page.")
            csv_file.close()
            return 1

        ul = upcoming_h2.find_next_sibling("ul")
        if not ul:
            logger.error("Could not find events list <ul> following Upcoming events.")
            csv_file.close()
            return 1

        lis = ul.find_all("li")
        logger.info(f"Discovered {len(lis)} upcoming events in November 2026.")

        # Parse listing items
        raw_events = []
        for li in lis:
            a = li.find("a")
            if not a or not a.get("href"):
                continue
            attendee_url = a.get("href").strip()
            spans = a.find_all("span")
            event_name = spans[0].get_text(strip=True) if spans else a.get_text(strip=True)
            date_loc = spans[1].get_text(" ", strip=True) if len(spans) > 1 else ""
            s_date, e_date, city, country = parse_listing_date_loc(date_loc)

            raw_events.append({
                "event_name": event_name,
                "attendee_url": attendee_url,
                "start_date": s_date,
                "end_date": e_date,
                "city": city,
                "country": country,
            })

        if args.limit > 0:
            raw_events = raw_events[:args.limit]
            logger.info(f"Applying limit: processing first {len(raw_events)} events.")

        events_to_process = [e for e in raw_events if e["event_name"] not in completed_events]
        total_events = len(raw_events)
        already_done = total_events - len(events_to_process)
        logger.info(f"Ready to scrape: {len(events_to_process)} events remaining ({already_done} already completed).")

        semaphore = asyncio.Semaphore(args.concurrency)
        counter = already_done

        async def worker(item: Dict[str, Any]):
            nonlocal counter
            ev_name = item["event_name"]
            att_url = item["attendee_url"]

            async with semaphore:
                details = await scrape_event_details(
                    session=session,
                    attendee_url=att_url,
                    fallback_start=item["start_date"],
                    fallback_end=item["end_date"],
                    fallback_city=item["city"],
                    fallback_country=item["country"],
                )

                row = {
                    "event_name": ev_name,
                    "event_start_date": details["event_start_date"],
                    "event_end_": details["event_end_"],
                    "venue": details["venue"],
                    "city": details["city"],
                    "country": details["country"],
                    "event_domain": details["event_domain"],
                }

                async with write_lock:
                    csv_writer.writerow(row)
                    csv_file.flush()
                    counter += 1
                    logger.info(
                        f"[{counter}/{total_events}] {ev_name} | {row['event_start_date']} | "
                        f"{row['city']}, {row['country']} | Domain: {row['event_domain'] or 'N/A'}"
                    )

        tasks = [asyncio.create_task(worker(item)) for item in events_to_process]
        if tasks:
            await asyncio.gather(*tasks)

    csv_file.close()
    logger.info(f"Scraping completed! Results saved to: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
