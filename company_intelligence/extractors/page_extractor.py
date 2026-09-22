import logging
import re
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from typing import Dict, List, Any

logger = logging.getLogger("company_intelligence.extractors.page_extractor")

class PageExtractor:
    def __init__(self, start_url: str):
        self.start_url = start_url

    def extract_links(self, soup: BeautifulSoup, current_url: str) -> List[str]:
        """
        Extracts all hrefs from the page and resolves relative URLs.
        """
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href:
                continue
            # Avoid mailto, tel, javascript links
            if href.startswith(("mailto:", "tel:", "javascript:", "sms:", "#")):
                continue
            resolved = urljoin(current_url, href)
            links.append(resolved)
        return list(set(links))

    def extract_page_text(self, soup: BeautifulSoup) -> str:
        """
        Extracts clean paragraphs and lists from the main body content,
        stripping away navigation, footers, headers, script, and style blocks.
        """
        # Create a copy so we don't mutate the original soup
        body = soup.find("body")
        if not body:
            body = soup
            
        # Strip noisy elements
        for element in body.find_all(["script", "style", "nav", "footer", "header", "form", "aside", "noscript"]):
            element.decompose()
            
        text_blocks = []
        
        # Process elements in order to preserve structure
        for elem in body.find_all(["h1", "h2", "h3", "p", "ul", "ol", "table"]):
            if elem.name in ["h1", "h2", "h3"]:
                text_blocks.append(f"\n{elem.name.upper()}: {elem.get_text().strip()}")
            elif elem.name == "p":
                p_text = elem.get_text().strip()
                if p_text:
                    text_blocks.append(p_text)
            elif elem.name in ["ul", "ol"]:
                items = [f"- {li.get_text().strip()}" for li in elem.find_all("li") if li.get_text().strip()]
                if items:
                    text_blocks.append("\n".join(items))
            elif elem.name == "table":
                rows = []
                for tr in elem.find_all("tr"):
                    cols = [td.get_text().strip() for td in tr.find_all(["td", "th"])]
                    if any(cols):
                        rows.append(" | ".join(cols))
                if rows:
                    text_blocks.append("\nTable:\n" + "\n".join(rows))
                    
        return "\n\n".join(text_blocks).strip()

    def classify_page_type(self, url: str, title: str, content: str) -> str:
        """
        Heuristic-based page classifier.
        Uses URL patterns, page titles, and body content keywords to classify the page category.
        """
        url_lower = url.lower()
        title_lower = title.lower() if title else ""
        content_lower = content.lower() if content else ""
        
        parsed = urlparse(url_lower)
        path = parsed.path.strip("/")
        
        # 1. Homepage checks
        if not path or path in ["index.html", "index.php", "home"]:
            return "homepage"
            
        # 2. Contact checks
        if any(x in url_lower or x in title_lower for x in ["contact", "support", "get-in-touch", "locations", "office"]):
            return "contact"
            
        # 3. About checks
        if any(x in url_lower or x in title_lower for x in ["about", "story", "history", "who-we-are", "company", "profile"]):
            return "about"
            
        # 4. Careers checks
        if any(x in url_lower or x in title_lower for x in ["careers", "jobs", "join-us", "openings", "work-at", "recruitment"]):
            return "careers"
            
        # 5. Team / Leadership checks
        if any(x in url_lower or x in title_lower for x in ["team", "leadership", "executives", "directors", "board"]):
            return "leadership"
            
        # 6. Products checks
        if any(x in url_lower or x in title_lower for x in ["product", "software", "platform", "app", "features", "pricing"]):
            return "products"
            
        # 7. Services checks
        if any(x in url_lower or x in title_lower for x in ["services", "consulting", "offerings", "professional-services"]):
            return "services"
            
        # 8. Solutions checks
        if any(x in url_lower or x in title_lower for x in ["solutions", "use-cases", "case-studies"]):
            if "case-studies" in url_lower or "case-study" in url_lower or "customers" in url_lower:
                return "case studies"
            return "solutions"
            
        # 9. Blog / News / Events
        if any(x in url_lower or x in title_lower for x in ["blog", "news", "press", "media", "announcements"]):
            return "blog"
        if "event" in url_lower or "webinar" in url_lower or "events" in title_lower:
            return "events"
            
        # 10. Partner checks
        if any(x in url_lower or x in title_lower for x in ["partners", "affiliates", "resellers"]):
            return "partners"
            
        # 11. Documentation / Resources
        if any(x in url_lower or x in title_lower for x in ["docs", "documentation", "resources", "downloads", "whitepapers", "guides"]):
            return "documentation"
            
        return "other"

    def extract(self, html: str, url: str) -> Dict[str, Any]:
        """
        Parses page HTML and extracts title, meta tags, headers, main text, and links.
        """
        soup = BeautifulSoup(html, "lxml")
        
        # Meta extraction
        title_tag = soup.find("title")
        title = title_tag.get_text().strip() if title_tag else ""
        
        meta_desc = ""
        meta_desc_tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
        if meta_desc_tag:
            meta_desc = meta_desc_tag.get("content", "").strip()
            
        canonical_url = ""
        canonical_tag = soup.find("link", rel="canonical")
        if canonical_tag:
            canonical_url = canonical_tag.get("href", "").strip()
            
        # Headings
        h1s = [h.get_text().strip() for h in soup.find_all("h1") if h.get_text().strip()]
        h2s = [h.get_text().strip() for h in soup.find_all("h2") if h.get_text().strip()]
        h3s = [h.get_text().strip() for h in soup.find_all("h3") if h.get_text().strip()]
        
        # Main text content
        main_text = self.extract_page_text(soup)
        
        # Links
        links = self.extract_links(soup, url)
        internal_links = [l for l in links if urlparse(l).netloc.lower() == urlparse(url).netloc.lower()]
        external_links = [l for l in links if urlparse(l).netloc.lower() != urlparse(url).netloc.lower()]
        
        # Classify
        page_type = self.classify_page_type(url, title, main_text)
        
        return {
            "url": url,
            "canonical_url": canonical_url or url,
            "title": title,
            "meta_description": meta_desc,
            "h1": h1s,
            "h2": h2s,
            "h3": h3s,
            "content": main_text,
            "internal_links": internal_links,
            "external_links": external_links,
            "page_type": page_type
        }
