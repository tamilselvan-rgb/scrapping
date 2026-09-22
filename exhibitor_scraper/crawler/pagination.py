import re
import urllib.parse
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any
from utils.url_utils import resolve_url

# Common next page indicator strings or icons
NEXT_BUTTON_TEXTS = [
    'next', 'next page', 'forward', '>', '»', 'after', 'next >', 'next »', 'following'
]

LOAD_MORE_TEXTS = [
    'load more', 'show more', 'view more', 'more exhibitors', 'see more', 'more'
]

class PaginationDetector:
    @staticmethod
    def detect_pagination(soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """
        Analyzes the page and URL structure to detect the type of pagination.
        Returns a dict describing the type and parameters:
        {
            "type": "query_param" | "next_button" | "load_more" | "infinite_scroll" | "none",
            "param_name": str (for query_param),
            "selector": str (for buttons),
            "next_url": str (pre-calculated next url if possible)
        }
        """
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        
        # 1. Check for standard page/offset query parameters in the current URL
        for key in ['page', 'p', 'offset', 'page_num', 'pg', 'currentpage']:
            if key in query:
                return {
                    "type": "query_param",
                    "param_name": key,
                    "selector": None
                }
                
        # 2. Check for next page link in HTML (Numerical pagination or 'Next' link)
        next_link_info = PaginationDetector.find_next_button_link(soup, url)
        if next_link_info:
            return {
                "type": "next_button",
                "selector": next_link_info["selector"],
                "next_url": next_link_info["url"]
            }
            
        # 3. Check for Load More buttons (typically clicked in Playwright)
        load_more_selector = PaginationDetector.find_load_more_button(soup)
        if load_more_selector:
            return {
                "type": "load_more",
                "selector": load_more_selector
            }
            
        # 4. Check for path patterns: /page/1 or /page/2
        if re.search(r'/page/\d+', parsed.path) or re.search(r'/p/\d+', parsed.path):
            return {
                "type": "path_variable",
                "pattern": r'/(page|p)/(\d+)'
            }
            
        # Fallback to scroll check or none
        # If there are a lot of elements, it could be infinite scroll
        return {
            "type": "none",
            "selector": None
        }

    @staticmethod
    def find_next_button_link(soup: BeautifulSoup, base_url: str) -> Optional[Dict[str, str]]:
        """
        Looks for an anchor tag representing the 'Next' page.
        """
        # Try finding anchor tags by class name that suggest pagination next
        for a in soup.find_all('a', href=True):
            href = a['href'].strip()
            if not href or href.startswith(('#', 'javascript:', 'mailto:')):
                continue
                
            text = a.get_text().strip().lower()
            classes = " ".join(a.get('class', [])).lower()
            rel = " ".join(a.get('rel', [])).lower()
            
            # Check rel="next"
            if 'next' in rel:
                return {"selector": f"a[rel~='next']", "url": resolve_url(base_url, href)}
                
            # Check text matches
            if any(text == btn_text or btn_text in text for btn_text in NEXT_BUTTON_TEXTS):
                # Build a simple CSS selector using class or ID if possible
                selector = "a"
                if a.get('class'):
                    selector += "." + ".".join(a.get('class'))
                elif a.get('id'):
                    selector += f"#{a.get('id')}"
                return {"selector": selector, "url": resolve_url(base_url, href)}
                
            # Check classes matching next page
            if any(kw in classes for kw in ['next', 'pagination-next', 'pager-next']):
                selector = "a"
                if a.get('class'):
                    selector += "." + ".".join(a.get('class'))
                return {"selector": selector, "url": resolve_url(base_url, href)}
                
        return None

    @staticmethod
    def find_load_more_button(soup: BeautifulSoup) -> Optional[str]:
        """
        Looks for button or div that resembles a 'Load More' button.
        """
        # Search buttons, anchors, and divs
        for element in soup.find_all(['button', 'a', 'div', 'span']):
            text = element.get_text().strip().lower()
            classes = " ".join(element.get('class', [])).lower()
            element_id = element.get('id', '').lower()
            
            # Match text
            if any(btn_text in text for btn_text in LOAD_MORE_TEXTS) and len(text) < 30:
                # Build selector
                tag = element.name
                if element.get('id'):
                    return f"{tag}#{element.get('id')}"
                elif element.get('class'):
                    return f"{tag}." + ".".join(element.get('class'))
                return tag
                
            # Match class/ID names
            if any(kw in classes or kw in element_id for kw in ['load-more', 'loadmore', 'show-more', 'btn-more']):
                tag = element.name
                if element.get('id'):
                    return f"{tag}#{element.get('id')}"
                elif element.get('class'):
                    return f"{tag}." + ".".join(element.get('class'))
                return tag
                
        return None

    @staticmethod
    def generate_next_query_url(current_url: str, param_name: str, current_page: int) -> str:
        """
        Generates the next page URL by incrementing the query parameter.
        """
        parsed = urllib.parse.urlparse(current_url)
        query = urllib.parse.parse_qs(parsed.query)
        
        # Set new page
        query[param_name] = [str(current_page + 1)]
        
        new_query = urllib.parse.urlencode(query, doseq=True)
        return urllib.parse.urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment
        ))
        
    @staticmethod
    def generate_next_path_url(current_url: str, current_page: int) -> str:
        """
        Generates the next page URL for path pagination (e.g. /page/2).
        """
        parsed = urllib.parse.urlparse(current_url)
        path = parsed.path
        
        # Look for page/number or p/number
        if re.search(r'/page/\d+', path):
            new_path = re.sub(r'/page/\d+', f'/page/{current_page + 1}', path)
        elif re.search(r'/p/\d+', path):
            new_path = re.sub(r'/p/\d+', f'/p/{current_page + 1}', path)
        else:
            # Append if not found but detected as path variable type
            new_path = path.rstrip('/') + f'/page/{current_page + 1}'
            
        return urllib.parse.urlunparse((
            parsed.scheme,
            parsed.netloc,
            new_path,
            parsed.params,
            parsed.query,
            parsed.fragment
        ))
