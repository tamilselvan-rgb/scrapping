import json
import re
import logging
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional

logger = logging.getLogger("scraper.api_detector")

class ApiDetector:
    @staticmethod
    def detect_next_data(soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
        """
        Detects Next.js __NEXT_DATA__ scripts and returns the parsed JSON.
        """
        script = soup.find('script', id='__NEXT_DATA__')
        if script and script.string:
            try:
                return json.loads(script.string)
            except Exception as e:
                logger.debug(f"Failed to parse __NEXT_DATA__: {e}")
        return None

    @staticmethod
    def detect_nuxt_data(soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
        """
        Detects Nuxt.js data. Nuxt often embeds states in window.__NUXT__ scripts.
        """
        for script in soup.find_all('script'):
            content = script.string or ''
            if 'window.__NUXT__' in content:
                # Nuxt state can be complex JavaScript. Let's do a simple regex extraction
                # to extract objects, or look for JSON patterns
                try:
                    # Attempt to extract JSON-like structures from the JS assignment
                    match = re.search(r'data:\s*(\[.*?\]|\{.*?\}),', content, re.DOTALL)
                    if match:
                        return json.loads(match.group(1))
                except Exception as e:
                    logger.debug(f"Failed to extract Nuxt data via regex: {e}")
        return None

    @staticmethod
    def find_json_objects_in_scripts(soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """
        Finds any generic script tags containing JSON data or large javascript objects.
        """
        results = []
        for script in soup.find_all('script'):
            content = script.string or ''
            if not content:
                continue
            
            # Look for JSON arrays or objects assigned to variables
            # e.g., var exhibitors = [...];
            # We can run a regex search for pattern: = ([{...}]|\[...\]);
            matches = re.finditer(r'=\s*(\[[^\]]{20,}\]|\{[^\}]{20,\})', content)
            for match in matches:
                try:
                    obj_str = match.group(1)
                    # Clean up JS-like keys/comments if any
                    # Simple JSON parse attempt
                    parsed = json.loads(obj_str)
                    if isinstance(parsed, (dict, list)):
                        results.append(parsed)
                except Exception:
                    # Often fails if it's raw JS, ignore
                    pass
        return results

    @staticmethod
    def extract_urls_from_data(data: Any) -> List[str]:
        """
        Recursively searches an arbitrary dictionary/list for URL values that look like exhibitor profiles.
        """
        urls = []
        if isinstance(data, dict):
            # Check keys
            for k, v in data.items():
                if k in {'url', 'href', 'slug', 'path', 'link'} and isinstance(v, str):
                    # Check if the string matches an exhibitor/company pattern
                    if any(kw in v.lower() for kw in ['exhibitor', 'company', 'profile', 'vendor']):
                        urls.append(v)
                elif isinstance(v, (dict, list)):
                    urls.extend(ApiDetector.extract_urls_from_data(v))
        elif isinstance(data, list):
            for item in data:
                urls.extend(ApiDetector.extract_urls_from_data(item))
        return urls
