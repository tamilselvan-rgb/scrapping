import json
import logging
import re
import html
import os
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("interpoma_scraper")

LISTING_URL = "https://www.fierabolzano.it/en/interpoma/exhibitor-list"
BASE_URL = "https://www.fierabolzano.it"
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw_cache.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

def clean_text(text: Optional[str]) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def clean_domain(url: Optional[str]) -> str:
    if not url:
        return ""
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        parsed = urllib.parse.urlparse("http://" + url)
    else:
        parsed = urllib.parse.urlparse(url)
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc or url

class InterpomaScraper:
    def __init__(self, max_workers: int = 12):
        self.max_workers = max_workers
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        
        # Configure robust connection pool and automatic retries
        retries = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            raise_on_status=False
        )
        adapter = HTTPAdapter(
            pool_connections=25,
            pool_maxsize=25,
            max_retries=retries
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def fetch_exhibitor_list(self) -> List[Dict[str, Any]]:
        """
        Fetches the main exhibitor listing page and parses exhibitors from data-exhibitors.
        """
        logger.info(f"Fetching exhibitor directory from {LISTING_URL}...")
        resp = self.session.get(LISTING_URL, timeout=30)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        div = soup.find(attrs={"data-exhibitors": True})
        if not div:
            m = re.search(r'data-exhibitors=([\'"])(.*?)\1', resp.text)
            if not m:
                raise ValueError("Could not find data-exhibitors attribute on listing page!")
            raw_json = html.unescape(m.group(2))
        else:
            raw_json = div["data-exhibitors"]

        exhibitors = json.loads(raw_json)
        logger.info(f"Successfully discovered {len(exhibitors)} exhibitors from directory metadata.")
        return exhibitors

    def fetch_detail_page(self, ex: Dict[str, Any], max_attempts: int = 3) -> Dict[str, Any]:
        """
        Visits the individual exhibitor detail page and extracts contact & address fields.
        """
        route = ex.get("route", "")
        if not route:
            slug = ex.get("parent_slug") or ex.get("id")
            route = f"{BASE_URL}/en/interpoma/exhibitor/{slug}"

        ex_name = ex.get("name", "")
        catalog_loc = ex.get("location", "")
        fair_hall = ex.get("fair_hall", "")
        
        stands = ex.get("fair_stand", [])
        stand_str = ""
        if isinstance(stands, list) and stands:
            stand_parts = []
            for st in stands:
                if isinstance(st, dict):
                    stand_parts.append(st.get("stand", ""))
                elif isinstance(st, str):
                    stand_parts.append(st)
            stand_str = ", ".join(filter(None, stand_parts))

        record = {
            "id": ex.get("id"),
            "id_odoo": ex.get("id_odoo"),
            "exhibitor_name": ex_name,
            "type": ex.get("type", "main"),
            "parent_name": ex.get("parent_name", ""),
            "parent_slug": ex.get("parent_slug", ""),
            "fair_hall": fair_hall,
            "fair_stand": stand_str,
            "country": ex.get("country", ""),
            "domain": "",
            "website_url": "",
            "number": "",
            "mail": "",
            "address": "",
            "detail_url": route,
            "raw_location": catalog_loc,
        }

        for attempt in range(1, max_attempts + 1):
            try:
                r = self.session.get(route, timeout=20)
                if r.status_code == 200:
                    s = BeautifulSoup(r.text, "html.parser")

                    # Exhibitor Name
                    name_el = s.find("h4", class_="name")
                    if name_el:
                        record["exhibitor_name"] = clean_text(name_el.get_text())

                    # Location / Address
                    loc_el = s.find("div", class_="location")
                    if loc_el:
                        div_parts = [clean_text(d.get_text()) for d in loc_el.find_all("div")]
                        div_parts = [p for p in div_parts if p]
                        if div_parts:
                            record["address"] = ", ".join(div_parts)
                    
                    if not record["address"] and catalog_loc:
                        record["address"] = clean_text(catalog_loc)

                    # Phone number
                    phone_el = s.find("div", class_="phone")
                    if phone_el:
                        phone_a = phone_el.find("a")
                        if phone_a:
                            record["number"] = clean_text(phone_a.get_text())
                        else:
                            txt = clean_text(phone_el.get_text())
                            record["number"] = re.sub(r"^T\.?\s*", "", txt)

                    # Website
                    web_el = s.find("div", class_="website")
                    if web_el:
                        web_a = web_el.find("a")
                        if web_a:
                            raw_href = web_a.get("href", "").strip()
                            record["website_url"] = raw_href
                            record["domain"] = clean_domain(raw_href)

                    # Email / Mailto
                    mail_el = s.find("input", attrs={"name": "mailto"})
                    if mail_el and mail_el.get("value"):
                        record["mail"] = clean_text(mail_el["value"])
                    else:
                        mailtos = s.find_all("a", href=re.compile(r"^mailto:", re.I))
                        for m in mailtos:
                            href_mail = m["href"].replace("mailto:", "").split("?")[0].strip()
                            if href_mail and "fieramesse" not in href_mail and "fierabolzano" not in href_mail:
                                record["mail"] = href_mail
                                break
                    break
                else:
                    logger.warning(f"Status {r.status_code} for {route} (attempt {attempt})")
                    if attempt < max_attempts:
                        time.sleep(1)

            except Exception as e:
                logger.warning(f"Attempt {attempt} failed for '{ex_name}' ({route}): {e}")
                if attempt < max_attempts:
                    time.sleep(1.5 * attempt)
                else:
                    logger.error(f"Final error fetching '{ex_name}' ({route}): {e}")

        # Clean address string
        addr = record["address"]
        if addr in ["- IT", "-", "IT", "None"]:
            record["address"] = ""

        return record

    def scrape_all(self, use_cache: bool = True) -> List[Dict[str, Any]]:
        """
        Coordinates full scraping of the directory and all detail pages.
        Caches results locally to ensure resilience against transient connection drops.
        """
        if use_cache and os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                if len(cached_data) >= 332 and sum(1 for c in cached_data if c.get("mail")) > 200:
                    logger.info(f"Loaded {len(cached_data)} cached records from {CACHE_FILE}")
                    return cached_data
            except Exception as e:
                logger.warning(f"Could not read cache: {e}")

        exhibitors = self.fetch_exhibitor_list()
        total = len(exhibitors)
        logger.info(f"Starting concurrent crawl of {total} detail pages with {self.max_workers} threads...")

        results: List[Dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_ex = {executor.submit(self.fetch_detail_page, ex): ex for ex in exhibitors}
            completed = 0
            for future in as_completed(future_to_ex):
                completed += 1
                try:
                    res = future.result()
                    results.append(res)
                except Exception as e:
                    ex = future_to_ex[future]
                    logger.error(f"Failed to process {ex.get('name')}: {e}")
                if completed % 50 == 0 or completed == total:
                    logger.info(f"Progress: {completed}/{total} pages fetched ({completed/total*100:.1f}%)")

        logger.info(f"Completed detail page crawling for {len(results)} exhibitors.")

        # Save to cache
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            logger.info(f"Cached raw scraped data to: {CACHE_FILE}")
        except Exception as e:
            logger.warning(f"Failed to write cache: {e}")

        return results

if __name__ == "__main__":
    scraper = InterpomaScraper()
    items = scraper.scrape_all()
    print(f"Total scraped: {len(items)}")
