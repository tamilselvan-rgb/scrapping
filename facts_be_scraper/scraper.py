"""
Scraper module for FACTS Belgium Exhibitor Directory.
Crawls all 28 directory pages from https://www.facts.be/en/exhibitors/
and visits every individual exhibitor profile page.
"""

import concurrent.futures
import json
import os
import re
import time
from typing import Dict, List, Optional
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.facts.be/en/exhibitors/?stands%5Bpage%5D="
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,nl;q=0.8,fr;q=0.7",
}

BLACKLISTED_URL_DOMAINS = {
    "facts.be", "easyfairs.com", "easyfairsgroup.com", "easyfairsassets.com",
    "jobs.easyfairs.be", "heroes.live", "heroes-world.be", "zendesk.com",
    "google.com", "iubenda.com", "visitcloud.com", "facebook.com",
    "instagram.com", "youtube.com", "twitter.com", "discord.gg", "discord.com"
}


def collect_all_profile_urls() -> List[str]:
    """Collects all exhibitor profile links across directory pages."""
    print("[INFO] Discovering exhibitor profile links across directory pages...")
    all_links = {}
    page = 1

    while True:
        url = f"{BASE_URL}{page}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                print(f"[WARN] Page {page} returned status {resp.status_code}. Stopping.")
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            page_links = []
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                match = re.search(r"/en/exhibitors/([^/?#]+-\d+)/?", href)
                if match:
                    slug = match.group(1)
                    full_profile_url = f"https://www.facts.be/en/exhibitors/{slug}/"
                    if full_profile_url not in all_links:
                        all_links[full_profile_url] = True
                        page_links.append(full_profile_url)

            print(f"[INFO] Page {page}: discovered {len(page_links)} new profile links (Total: {len(all_links)})")
            if not page_links:
                print(f"[INFO] No more exhibitors found after page {page - 1}. Discovery complete.")
                break

            page += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"[ERR] Error fetching directory page {page}: {e}")
            break

    profile_urls = list(all_links.keys())
    print(f"[SUCCESS] Discovered total {len(profile_urls)} exhibitor profile URLs.")
    return profile_urls


def parse_profile(html: str, url: str) -> Dict:
    """Parses an individual exhibitor profile page."""
    soup = BeautifulSoup(html, "html.parser")

    # 1. Exhibitor Name
    name = ""
    name_el = soup.select_one("h1.stand-details__title")
    if name_el:
        name = name_el.get_text(strip=True)
    if not name:
        title_el = soup.find("title")
        if title_el:
            name = title_el.get_text(strip=True).split("|")[0].split("-")[0].strip()

    # 2. Fair Stand / Booth
    stand = ""
    stand_el = soup.select_one(".stand-details__info-line-content")
    if stand_el:
        stand = re.sub(r"^Stand\s*:\s*", "", stand_el.get_text(strip=True), flags=re.IGNORECASE).strip()
    if not stand:
        for text_el in soup.find_all(string=re.compile(r"Stand\s*:\s*", re.I)):
            stand = re.sub(r"^Stand\s*:\s*", "", text_el.strip(), flags=re.IGNORECASE).strip()
            if stand:
                break

    # 3. Location & Website from Contact Card
    location = ""
    website_url = ""
    social_links = []

    contact_wrapper = soup.select_one(".contact-info-card__info-lines-wrapper")
    if contact_wrapper:
        lines = contact_wrapper.select(".contact-info-card__info-line")
        for line in lines:
            text = line.get_text(" ", strip=True)
            # Check for PlaceIcon
            if line.find("svg", attrs={"data-testid": "PlaceIcon"}):
                location = text
            # Check for PublicIcon
            elif line.find("svg", attrs={"data-testid": "PublicIcon"}):
                link = line.find("a", href=True)
                if link:
                    website_url = link["href"].strip()
                elif text:
                    website_url = text
            else:
                # Fallback heuristics
                if any(w in text.lower() for w in ["www.", "http://", "https://", ".com", ".be", ".nl", ".de", ".fr", ".it"]):
                    if not website_url:
                        website_url = text
                elif not location and len(text) > 3:
                    location = text

    # If website still not found, check other external links on page
    if not website_url:
        main_content = soup.find("main") or soup.find(id="content") or soup
        for a in main_content.find_all("a", href=True):
            href = a["href"].strip()
            if not href.startswith(("http://", "https://", "www.")):
                continue
            parsed_netloc = urlparse(href if href.startswith("http") else "https://" + href).netloc.lower()
            if not any(b in parsed_netloc for b in BLACKLISTED_URL_DOMAINS):
                website_url = href
                break

    # 4. Social Links
    socials_wrapper = soup.select_one(".contact-info-card__socials")
    if socials_wrapper:
        for sa in socials_wrapper.find_all("a", href=True):
            shref = sa["href"].strip()
            if any(soc in shref.lower() for soc in ["facebook.com", "instagram.com", "twitter.com", "youtube.com", "linkedin.com", "tiktok.com"]):
                if not any(b in shref.lower() for b in ["factsconvention", "heroes", "easyfairs"]):
                    social_links.append(shref)

    # Clean website URL format
    if website_url:
        website_url = website_url.strip()
        if website_url.startswith("www."):
            website_url = "https://" + website_url

    return {
        "name": name,
        "stand": stand,
        "location": location,
        "website_url": website_url,
        "social_links": social_links,
        "detail_url": url,
    }


def fetch_single_profile(url: str, retries: int = 3) -> Optional[Dict]:
    """Fetch and parse a single exhibitor profile page."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                return parse_profile(resp.text, url)
        except Exception:
            time.sleep(1.0)
    return None


def scrape_all_exhibitor_profiles(cache_file: str = "raw_cache.json", force_refresh: bool = False, max_workers: int = 8) -> List[Dict]:
    """Scrapes all exhibitor profiles or loads from cache."""
    cache_path = os.path.join(os.path.dirname(__file__), cache_file)
    if not force_refresh and os.path.exists(cache_path):
        print(f"[INFO] Loading raw scraped exhibitors from cache: {cache_path}")
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # 1. Collect profile URLs
    profile_urls = collect_all_profile_urls()

    # 2. Visit each profile URL multithreadedly
    print(f"[INFO] Visiting and scraping {len(profile_urls)} individual exhibitor profile pages...")
    results = []
    completed = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {executor.submit(fetch_single_profile, url): url for url in profile_urls}
        for future in concurrent.futures.as_completed(future_to_url):
            url = future_to_url[future]
            try:
                res = future.result()
                if res and res.get("name"):
                    results.append(res)
                completed += 1
                if completed % 25 == 0 or completed == len(profile_urls):
                    print(f"[PROGRESS] Scraped {completed}/{len(profile_urls)} profiles...")
            except Exception as e:
                print(f"[ERR] Failed scraping profile {url}: {e}")

    print(f"[SUCCESS] Successfully scraped {len(results)} exhibitor profiles.")

    # Save cache
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"[INFO] Saved raw profile cache to {cache_path}")

    return results


if __name__ == "__main__":
    profiles = scrape_all_exhibitor_profiles(force_refresh=True)
    print(f"Total profiles scraped: {len(profiles)}")
