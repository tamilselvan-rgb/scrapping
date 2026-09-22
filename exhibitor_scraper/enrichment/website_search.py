import os
import logging
import urllib.parse
from typing import List, Dict, Any, Optional
import httpx
from utils.url_utils import normalize_url, get_domain

logger = logging.getLogger("scraper.website_search")

# Blacklisted domains representing social, directories, marketplaces, info engines etc.
BLACKLISTED_DOMAINS = {
    'linkedin.com', 'facebook.com', 'instagram.com', 'youtube.com', 'twitter.com', 'x.com',
    'indiamart.com', 'tradeindia.com', 'justdial.com', '10times.com', 'crunchbase.com',
    'zoominfo.com', 'rocketreach.co', 'yelp.com', 'tripadvisor.com', 'wikipedia.org',
    'glassdoor.com', 'pinterest.com', 'amazon.com', 'ebay.com', 'alibaba.com', 'aliexpress.com',
    'yellowpages.com', 'directory.com', 'exhibitor.com', 'eventbrite.com', 'bloomberg.com',
    'apollo.io', 'mapquest.com', 'waze.com', 'reddit.com', 'medium.com', 'github.com'
}

class WebsiteSearch:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("SERPER_API_KEY")
        self.endpoint = "https://google.serper.dev/search"

    async def search_company_website(
        self, 
        company_name: str, 
        country: Optional[str] = None, 
        industry: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Queries the Serper API to find candidate websites for a company.
        Constructs custom queries and filters out directories/social media.
        Returns a list of candidate details:
        [{"title": str, "url": str, "snippet": str}]
        """
        if not self.api_key:
            logger.warning("SERPER_API_KEY is not configured. Skipping website search.")
            return []

        if not company_name or company_name.lower() == "unknown exhibitor":
            return []

        # Construct primary search query
        query = f'"{company_name}" official website'
        
        # Build alternative terms if needed
        # We can construct up to 1-2 fallback parameters if the first returns nothing, 
        # but to save API credits, we do one robust search and retrieve more results (e.g. num=10)
        if country:
            query += f" {country}"
        if industry:
            query += f" {industry}"

        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json"
        }
        
        payload = {
            "q": query,
            "num": 10
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(self.endpoint, headers=headers, json=payload)
                if response.status_code == 403:
                    logger.error("Serper API key is invalid or unauthorized.")
                    return []
                response.raise_for_status()
                
                results = response.json()
                organic = results.get("organic", [])
                
                candidates: List[Dict[str, Any]] = []
                for result in organic:
                    url = result.get("link")
                    if not url:
                        continue
                        
                    normalized = normalize_url(url)
                    domain = get_domain(normalized)
                    
                    # Skip directories, social media and other noisy sites
                    if any(blacklisted in domain for blacklisted in BLACKLISTED_DOMAINS):
                        continue
                        
                    candidates.append({
                        "title": result.get("title", ""),
                        "url": normalized,
                        "snippet": result.get("snippet", "")
                    })
                    
                logger.info(f"Found {len(candidates)} candidate websites for company '{company_name}' after filtering.")
                return candidates
                
        except Exception as e:
            logger.error(f"Error searching Serper API for '{company_name}': {e}")
            return []
