"""
Scraper module for LOUPE India Exhibitor Directory.
Crawls all paginated pages from https://www.loupe-india.com/exhibitor-list-visitor.
"""

import json
import os
import re
import time
from typing import Dict, List, Optional
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.loupe-india.com/exhibitor-list-visitor"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_page(page_num: int, retries: int = 3) -> Optional[str]:
    """Fetch HTML for a given page number with retry logic."""
    url = f"{BASE_URL}?page={page_num}"
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            if resp.status_code == 200:
                return resp.text
            print(f"[WARN] Page {page_num} returned status {resp.status_code} (attempt {attempt + 1})")
        except Exception as e:
            print(f"[ERR] Error fetching page {page_num} (attempt {attempt + 1}): {e}")
        time.sleep(1.5)
    return None


def parse_page_items(html: str, page_num: int) -> List[Dict]:
    """Parse exhibitor cards from page HTML."""
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select(".exhibitor-list--item")
    parsed_items = []

    for item in items:
        # 1. Exhibitor Name
        name_elem = item.select_one(".exhibitor__name")
        if not name_elem:
            continue
        name = name_elem.get_text(strip=True)
        if not name:
            continue

        # 2. Booth / Stand
        stand = ""
        stand_elem = item.select_one(".exhibitor__stand")
        if stand_elem:
            stand_text = stand_elem.get_text(strip=True)
            stand = re.sub(r"^Booth\(s\)\s*:\s*", "", stand_text, flags=re.IGNORECASE).strip()

        # 3. Country Flag Class
        flag_code = ""
        flag_elem = item.select_one(".country-flag")
        if flag_elem:
            for cls in flag_elem.get("class", []):
                if cls.startswith("flag-") and cls != "flag-instead":
                    flag_code = cls.replace("flag-", "").strip().lower()
                    break

        # 4. Details Section Links & Categories
        website_url = ""
        social_links = []
        categories = ""

        details_sec = item.select_one(".exhibitor-details")
        if details_sec:
            # Look for website link
            web_elem = details_sec.select_one("p.website-link a, a.website-link")
            if web_elem and web_elem.get("href"):
                website_url = web_elem.get("href").strip()
            else:
                # Any <a> tag that looks like a website or external link
                for a in details_sec.find_all("a", href=True):
                    href = a["href"].strip()
                    if not href.startswith("http"):
                        continue
                    if any(soc in href.lower() for soc in ["instagram.com", "linkedin.com", "youtube.com", "facebook.com", "twitter.com", "x.com"]):
                        social_links.append(href)
                    elif not website_url:
                        website_url = href

            # Check text for categories ("Suppliers of: ...")
            details_text = details_sec.get_text(" ", strip=True)
            cat_match = re.search(r"Suppliers of\s*:\s*(.*?)(?:Close|Connect|$)", details_text, re.IGNORECASE)
            if cat_match:
                categories = cat_match.group(1).strip()

        # 5. Is New Exhibitor Tag
        is_new = bool(item.select_one(".exhibitor-tags .new"))

        parsed_items.append({
            "page": page_num,
            "name": name,
            "stand": stand,
            "country_code": flag_code,
            "portal_website": website_url,
            "social_links": social_links,
            "categories": categories,
            "is_new": is_new,
        })

    return parsed_items


def scrape_all_exhibitors(cache_file: str = "raw_cache.json", force_refresh: bool = False) -> List[Dict]:
    """Scrapes all pages from Loupe India directory or loads from cache."""
    cache_path = os.path.join(os.path.dirname(__file__), cache_file)
    if not force_refresh and os.path.exists(cache_path):
        print(f"[INFO] Loading raw scraped exhibitors from cache: {cache_path}")
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)

    print("[INFO] Starting scrape of LOUPE India Exhibitor Directory...")
    all_exhibitors = []
    page_num = 0

    while True:
        print(f"[INFO] Fetching page {page_num}...")
        html = fetch_page(page_num)
        if not html:
            print(f"[WARN] Failed to fetch page {page_num}. Ending pagination.")
            break

        items = parse_page_items(html, page_num)
        if not items:
            print(f"[INFO] No items found on page {page_num}. Completed pagination.")
            break

        print(f"[INFO] Page {page_num}: parsed {len(items)} exhibitors.")
        all_exhibitors.extend(items)
        page_num += 1
        time.sleep(0.5)

    print(f"[SUCCESS] Scraped total {len(all_exhibitors)} exhibitors across {page_num} pages.")

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(all_exhibitors, f, indent=2, ensure_ascii=False)
    print(f"[INFO] Saved raw exhibitor cache to {cache_path}")

    return all_exhibitors


if __name__ == "__main__":
    exhibitors = scrape_all_exhibitors(force_refresh=True)
    print(f"Total parsed: {len(exhibitors)}")
