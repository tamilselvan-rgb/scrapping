"""
Denkmal 2026 exhibitor scraper.
Discovers exhibitors via the official API, then visits each EN profile page.
"""

import concurrent.futures
import json
import os
import re
import time
from html import unescape
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

API_URL = "https://www.denkmal-leipzig.de/api/exhibitors"
LISTING_URL = (
    "https://www.denkmal-leipzig.de/en/exhibitor-products/"
    "?limitSearchResults=344&catalog=EXHIBITOR"
)
BASE_URL = "https://www.denkmal-leipzig.de"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
    "Referer": LISTING_URL,
}

BLACKLISTED_DOMAINS = {
    "denkmal-leipzig.de",
    "leipziger-messe.de",
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "xing.com",
    "pinterest.com",
    "wikipedia.org",
    "yellowpages.com",
    "yelp.com",
}

DENKMAL_LINKEDIN_URLS = {
    "https://www.linkedin.com/showcase/98585645",
    "https://linkedin.com/showcase/98585645",
}


def clean_html_text(html: Optional[str]) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()


def to_en_profile_url(api_url: Optional[str]) -> str:
    if not api_url:
        return ""
    return (
        api_url.replace("/aussteller-produkte/aussteller/", "/exhibitors-products/exhibitor/")
        .replace("http://", "https://")
    )


def channel_value(channels: List[Dict], channel_type: str) -> str:
    for channel in channels or []:
        if (channel.get("type") or "").upper() == channel_type.upper():
            return (channel.get("value") or "").strip()
    return ""


def build_address(street: str, zip_code: str, city: str) -> str:
    parts = []
    if street:
        parts.append(street.strip())
    city_line = " ".join(p for p in [zip_code.strip(), city.strip()] if p)
    if city_line:
        parts.append(city_line)
    return ", ".join(parts)


def parse_profile_page(html: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    result = {
        "desc": "",
        "email": "",
        "phone": "",
        "domain": "",
        "linkedin_url": "",
    }

    profile_section = soup.select_one(".company-profile, .exhibitor-profile, [data-onpage-nav='Profile']")
    if profile_section:
        result["desc"] = re.sub(r"\s+", " ", profile_section.get_text(" ", strip=True))

    contact = soup.select_one(".company-contact")
    if contact:
        text = contact.get_text("\n", strip=True)
        email_match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", text)
        if email_match:
            result["email"] = email_match.group(0)
        phone_match = re.search(r"Phone:\s*([^\n]+)", text, re.I)
        if phone_match:
            result["phone"] = phone_match.group(1).strip()

        for a in contact.find_all("a", href=True):
            href = a["href"].strip()
            label = (a.get("aria-label") or a.get_text(" ", strip=True)).lower()
            if href.startswith("http"):
                host = urlparse(href).netloc.lower()
                if "linkedin.com" in host:
                    result["linkedin_url"] = href
                elif "denkmal-leipzig.de" not in host and not result["domain"]:
                    if not any(blocked in host for blocked in BLACKLISTED_DOMAINS):
                        result["domain"] = href

    social_bar = soup.select_one(".company-contact .company-contact__social-bar")
    if social_bar:
        for a in social_bar.find_all("a", href=True):
            href = a["href"].strip()
            if "linkedin.com" in href.lower() and href not in DENKMAL_LINKEDIN_URLS:
                result["linkedin_url"] = href

    return result


def fetch_profile(url: str, retries: int = 3) -> Dict[str, str]:
    if not url:
        return {}
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            if resp.status_code == 200:
                return parse_profile_page(resp.text)
        except requests.RequestException:
            pass
        time.sleep(0.5 * (attempt + 1))
    return {}


def parse_api_exhibitor(item: Dict) -> Dict:
    channels = item.get("contactChannels") or []
    street = (item.get("streetWithNo") or "").strip()
    zip_code = (item.get("zipCode") or "").strip()
    city = (item.get("city") or "").strip()
    country = (item.get("country") or "").strip()

    desc = clean_html_text(item.get("companyProfile"))
    if not desc:
        desc = (item.get("companyProfileTruncated") or "").strip()

    profile_url = to_en_profile_url(item.get("url"))
    booths = item.get("booths") or []
    booth_values = [b.get("boothInfoValue", "") for b in booths if b.get("boothInfoValue")]

    return {
        "source_id": item.get("sourceId", ""),
        "name": (item.get("name") or "").strip(),
        "desc": desc,
        "email": channel_value(channels, "EMAIL"),
        "phone": channel_value(channels, "PHONE"),
        "domain": channel_value(channels, "WEBSITE"),
        "address": build_address(street, zip_code, city),
        "city": city,
        "country_raw": country,
        "linkedin_url": channel_value(channels, "LINKEDIN"),
        "detail_url": profile_url,
        "fair_stand": "; ".join(booth_values),
        "product_groups": "; ".join(item.get("productGroups") or []),
    }


def fetch_exhibitors_from_api() -> List[Dict]:
    print(f"[INFO] Fetching exhibitor catalog from API: {API_URL}")
    resp = requests.get(API_URL, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    exhibitors = data.get("exhibitors", [])
    en_items = [e for e in exhibitors if (e.get("lang") or "").upper() == "EN"]
    print(f"[INFO] Loaded {len(en_items)} English (2026) exhibitor records from API.")
    return [parse_api_exhibitor(item) for item in en_items]


def merge_profile_data(base: Dict, profile: Dict) -> Dict:
    merged = dict(base)
    for key in ("desc", "email", "phone", "domain"):
        if not merged.get(key) and profile.get(key):
            merged[key] = profile[key]
    profile_linkedin = (profile.get("linkedin_url") or "").strip()
    if (
        not merged.get("linkedin_url")
        and profile_linkedin
        and profile_linkedin not in DENKMAL_LINKEDIN_URLS
    ):
        merged["linkedin_url"] = profile_linkedin
    return merged


def scrape_all_exhibitors(
    cache_file: str = "raw_cache.json",
    force_refresh: bool = False,
    max_workers: int = 10,
) -> List[Dict]:
    cache_path = os.path.join(os.path.dirname(__file__), cache_file)
    if not force_refresh and os.path.exists(cache_path):
        print(f"[INFO] Loading cached raw exhibitors from {cache_path}")
        with open(cache_path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    api_records = fetch_exhibitors_from_api()
    print(f"[INFO] Visiting {len(api_records)} exhibitor profile pages...")
    results: List[Dict] = []
    completed = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(fetch_profile, record["detail_url"]): record
            for record in api_records
        }
        for future in concurrent.futures.as_completed(future_map):
            record = future_map[future]
            try:
                profile_data = future.result()
                results.append(merge_profile_data(record, profile_data))
            except Exception as exc:
                print(f"[WARN] Failed profile scrape for {record.get('name')}: {exc}")
                results.append(record)
            completed += 1
            if completed % 25 == 0 or completed == len(api_records):
                print(f"[PROGRESS] Profiles visited {completed}/{len(api_records)}")

    results.sort(key=lambda row: row.get("name", "").lower())
    with open(cache_path, "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2, ensure_ascii=False)
    print(f"[SUCCESS] Cached {len(results)} raw exhibitor records.")
    return results


if __name__ == "__main__":
    records = scrape_all_exhibitors(force_refresh=True)
    print(f"Total exhibitors scraped: {len(records)}")
