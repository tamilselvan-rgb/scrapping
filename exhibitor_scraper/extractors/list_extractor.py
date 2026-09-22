import logging
from bs4 import BeautifulSoup
from typing import List, Dict, Any
from crawler.page_detector import PageDetector
from crawler.api_detector import ApiDetector
from utils.url_utils import resolve_url
from utils.text_utils import clean_text

logger = logging.getLogger("scraper.list_extractor")

class ListExtractor:
    def __init__(self, base_url: str):
        self.base_url = base_url

    def extract(self, html_content: str) -> List[Dict[str, Any]]:
        """
        Parses the listing HTML content and returns a list of dictionaries with basic info:
        [{"company_name": str, "exhibitor_profile_url": str, "booth_number": str, "hall_number": str}]
        """
        soup = BeautifulSoup(html_content, 'lxml')
        exhibitors = []
        
        # 1. Try Next.js or Nuxt.js or script data first (Level 2)
        next_data = ApiDetector.detect_next_data(soup)
        if next_data:
            urls = ApiDetector.extract_urls_from_data(next_data)
            if urls:
                logger.info(f"Extracted {len(urls)} profile URLs from NextJS data.")
                for url in urls:
                    resolved = resolve_url(self.base_url, url)
                    exhibitors.append({
                        "company_name": "", # Will be enriched by profile scraper
                        "exhibitor_profile_url": resolved
                    })
                return exhibitors

        # 2. Try generic card detection (repeated components)
        cards = PageDetector.detect_exhibitor_cards(soup)
        if cards:
            for card in cards:
                url = card["url"]
                resolved = resolve_url(self.base_url, url)
                text = card["text"]
                
                # Try to parse booth or stand from card text
                booth = ""
                hall = ""
                booth_match = re.search(r'\b(?:booth|stand|stall)\b\s*:?\s*([a-zA-Z0-9\-\.]+)', text, re.IGNORECASE)
                if booth_match:
                    booth = booth_match.group(1)
                    
                hall_match = re.search(r'\b(?:hall)\b\s*:?\s*([a-zA-Z0-9\-\.]+)', text, re.IGNORECASE)
                if hall_match:
                    hall = hall_match.group(1)
                
                # Guess company name by taking first line or shortest segment
                name_guess = ""
                lines = [line.strip() for line in text.split('\n') if line.strip()]
                if lines:
                    name_guess = lines[0]
                    # If the name is too long or contains booth info, trim it
                    if len(name_guess) > 100:
                        name_guess = name_guess[:100]
                
                exhibitors.append({
                    "company_name": clean_text(name_guess),
                    "exhibitor_profile_url": resolved,
                    "booth_number": booth,
                    "hall_number": hall
                })
            
            # Deduplicate list
            seen_urls = set()
            deduped = []
            for item in exhibitors:
                u = item["exhibitor_profile_url"]
                if u not in seen_urls:
                    seen_urls.add(u)
                    deduped.append(item)
            if len(deduped) > 0:
                return deduped

        # 3. Fallback to basic link extractor (extract candidate URLs)
        candidate_urls = PageDetector.extract_candidate_urls(soup, self.base_url)
        for url in candidate_urls:
            exhibitors.append({
                "company_name": "",
                "exhibitor_profile_url": url
            })
            
        # Deduplicate
        seen_urls = set()
        deduped = []
        for item in exhibitors:
            u = item["exhibitor_profile_url"]
            if u not in seen_urls:
                seen_urls.add(u)
                deduped.append(item)
                
        return deduped

# Import re in module level helper
import re
