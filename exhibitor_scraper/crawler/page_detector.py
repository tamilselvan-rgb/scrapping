import re
from typing import List, Set, Dict, Any
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from utils.url_utils import resolve_url

# Common URL patterns indicating an exhibitor or company detail page
EXHIBITOR_URL_KEYWORDS = [
    '/exhibitor/', '/exhibitors/', 
    '/company/', '/companies/', 
    '/vendor/', '/vendors/', 
    '/profile/', '/exhibit/', 
    '/showcase/', '/directory/'
]

class PageDetector:
    @staticmethod
    def extract_candidate_urls(soup: BeautifulSoup, base_url: str) -> List[str]:
        """
        Extracts all candidate exhibitor profile URLs from the listing page using heuristics.
        """
        candidates: Set[str] = set()
        
        # 1. Look for hrefs matching standard directory paths
        for a in soup.find_all('a', href=True):
            href = a['href'].strip()
            if not href or href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                continue
                
            resolved = resolve_url(base_url, href)
            parsed_resolved = urlparse(resolved)
            path = parsed_resolved.path.lower()
            
            # Match against known keywords
            is_match = any(kw in path for kw in EXHIBITOR_URL_KEYWORDS)
            
            # Or match common patterns (e.g., /exhibitor-name, or if the class/ID of parent/anchor contains words)
            if not is_match:
                parent_text = " ".join(a.get('class', [])) + " " + " ".join(a.parent.get('class', []) if a.parent else [])
                if any(kw in parent_text.lower() for kw in ['exhibitor', 'directory-item', 'company-link']):
                    is_match = True
            
            if is_match:
                # Basic sanity check: avoid same-page anchors or query strings referencing page numbers
                if not re.search(r'(page=\d+|\bp=\d+)', path):
                    candidates.add(resolved)
                    
        # 2. Extract from JSON-LD if present (e.g. ItemList schema of exhibitors)
        json_ld_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                import json
                data = json.loads(script.string or '')
                urls = PageDetector._extract_urls_from_json_ld(data)
                for u in urls:
                    resolved = resolve_url(base_url, u)
                    candidates.add(resolved)
            except Exception:
                pass

        return list(candidates)

    @staticmethod
    def _extract_urls_from_json_ld(data: Any) -> List[str]:
        urls = []
        if isinstance(data, dict):
            if data.get('@type') in ('ItemList', 'ExhibitorList', 'DirectoryCategory'):
                elements = data.get('itemListElement', [])
                if isinstance(elements, list):
                    for el in elements:
                        urls.extend(PageDetector._extract_urls_from_json_ld(el))
            elif 'url' in data and data.get('@type') in ('Organization', 'LocalBusiness', 'Exhibitor'):
                if isinstance(data['url'], str):
                    urls.append(data['url'])
            # Recurse other fields
            for k, v in data.items():
                if isinstance(v, (dict, list)):
                    urls.extend(PageDetector._extract_urls_from_json_ld(v))
        elif isinstance(data, list):
            for item in data:
                urls.extend(PageDetector._extract_urls_from_json_ld(item))
        return urls

    @staticmethod
    def detect_exhibitor_cards(soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """
        Attempts to detect repeated DOM elements representing exhibitor cards.
        Returns a list of structured data matching those cards.
        """
        cards = []
        # Find structural elements that recur frequently
        # Focus on elements that contain a heading or anchor pointing to profiles
        # We can find tags like article, div, li that have common exhibitor-related classes
        candidates = soup.find_all(['div', 'li', 'article', 'tr'])
        
        for el in candidates:
            classes = " ".join(el.get('class', []))
            if any(kw in classes.lower() for kw in ['exhibitor', 'directory', 'card', 'item', 'vendor', 'company']):
                # Find the main link inside
                link = el.find('a', href=True)
                if link:
                    name_text = el.get_text(separator=' ').strip()
                    cards.append({
                        "element": el,
                        "url": link['href'],
                        "text": name_text
                    })
        return cards
