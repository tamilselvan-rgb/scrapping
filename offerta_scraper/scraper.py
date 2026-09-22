import os
import json
import logging
import time
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("offerta_scraper")

SEARCH_URL = "https://www.offerta.de/api/exibitor-register/search"
DETAILS_URL = "https://www.offerta.de/api/exibitor-register/exhibitor-details"
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw_cache.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Referer": "https://www.offerta.de/offerta-live/ausstellendenverzeichnis/",
}

class OffertaScraper:
    def __init__(self, max_workers: int = 10):
        self.max_workers = max_workers
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        
        # Configure connection pool and automatic retries
        retries = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            raise_on_status=False
        )
        adapter = HTTPAdapter(
            pool_connections=20,
            pool_maxsize=20,
            max_retries=retries
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def fetch_all_search_records(self) -> List[Dict[str, Any]]:
        """
        Paginates through the catalog search API to retrieve all exhibitor items.
        """
        logger.info("Fetching exhibitor search catalog...")
        all_exhibitors: List[Dict[str, Any]] = []
        page = 1
        total_pages = 1

        while page <= total_pages:
            payload = {
                "eventId": "OFF",
                "language": "de_DE",
                "filterMap": {},
                "searchTerm": "",
                "page": page
            }
            try:
                resp = self.session.post(SEARCH_URL, json=payload, timeout=20)
                resp.raise_for_status()
                data = resp.json()
                
                page_info = data.get("page", {})
                total_pages = page_info.get("totalPages", total_pages)
                total_elements = page_info.get("totalElements", 0)
                
                items = data.get("data", [])
                all_exhibitors.extend(items)
                
                logger.info(f"Retrieved page {page}/{total_pages} (Total fetched: {len(all_exhibitors)}/{total_elements})")
                
                if not page_info.get("hasNext", False):
                    break
                page += 1
                time.sleep(0.05)
            except Exception as e:
                logger.error(f"Failed to fetch page {page}: {e}")
                break

        logger.info(f"Completed catalog search. Found {len(all_exhibitors)} total exhibitors.")
        return all_exhibitors

    def fetch_exhibitor_details(self, exhibitor: Dict[str, Any], max_attempts: int = 3) -> Dict[str, Any]:
        """
        Fetches full profile details for a single exhibitor.
        """
        ex_id = exhibitor.get("id", "")
        ex_name = exhibitor.get("companyName", "")

        payload = {
            "eventId": "OFF",
            "language": "de_DE",
            "exhibitorId": ex_id
        }

        for attempt in range(1, max_attempts + 1):
            try:
                resp = self.session.post(DETAILS_URL, json=payload, timeout=15)
                if resp.status_code == 200:
                    detail_data = resp.json().get("data")
                    if detail_data:
                        return detail_data
                    else:
                        return exhibitor
                else:
                    logger.warning(f"Status {resp.status_code} for exhibitor '{ex_name}' ({ex_id})")
                    if attempt < max_attempts:
                        time.sleep(1)
            except Exception as e:
                logger.warning(f"Attempt {attempt} failed for '{ex_name}': {e}")
                if attempt < max_attempts:
                    time.sleep(1.5 * attempt)
                else:
                    logger.error(f"Final error fetching '{ex_name}': {e}")

        return exhibitor

    def scrape_all(self, use_cache: bool = True) -> List[Dict[str, Any]]:
        """
        Scrapes all exhibitors and their full detail pages.
        Utilizes local caching to guard against transient network interruptions.
        """
        if use_cache and os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                if len(cached) >= 333:
                    logger.info(f"Loaded {len(cached)} cached exhibitor records from {CACHE_FILE}")
                    return cached
            except Exception as e:
                logger.warning(f"Cache load failed: {e}")

        search_items = self.fetch_all_search_records()
        total = len(search_items)
        logger.info(f"Fetching details for {total} exhibitors with {self.max_workers} threads...")

        details_list: List[Dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_ex = {executor.submit(self.fetch_exhibitor_details, ex): ex for ex in search_items}
            completed = 0
            for future in as_completed(future_to_ex):
                completed += 1
                try:
                    res = future.result()
                    details_list.append(res)
                except Exception as e:
                    ex = future_to_ex[future]
                    logger.error(f"Failed processing {ex.get('companyName')}: {e}")
                    details_list.append(ex)

                if completed % 50 == 0 or completed == total:
                    logger.info(f"Progress: {completed}/{total} details fetched ({completed/total*100:.1f}%)")

        logger.info(f"All details retrieved ({len(details_list)} records).")

        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(details_list, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved raw details cache to {CACHE_FILE}")
        except Exception as e:
            logger.warning(f"Failed to write cache: {e}")

        return details_list

if __name__ == "__main__":
    scraper = OffertaScraper()
    items = scraper.scrape_all()
    print(f"Scraped count: {len(items)}")
