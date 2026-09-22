import json
import logging
from bs4 import BeautifulSoup
from typing import Dict, List, Any

logger = logging.getLogger("company_intelligence.extractors.structured_data")

class StructuredDataExtractor:
    @staticmethod
    def extract_json_ld(soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """
        Finds and parses all JSON-LD blocks on the page.
        """
        json_ld_data = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                content = script.string
                if content:
                    # Clean up common formatting issues
                    data = json.loads(content.strip())
                    if isinstance(data, list):
                        json_ld_data.extend(data)
                    else:
                        json_ld_data.append(data)
            except Exception as e:
                logger.debug(f"Failed to parse JSON-LD block: {e}")
                
        return json_ld_data

    @staticmethod
    def extract_opengraph(soup: BeautifulSoup) -> Dict[str, str]:
        """
        Extracts all OpenGraph metadata tags (og:title, og:description, etc.).
        """
        og_data = {}
        for meta in soup.find_all("meta", property=True):
            prop = meta["property"].strip().lower()
            if prop.startswith("og:"):
                og_data[prop] = meta.get("content", "").strip()
                
        # Also include twitter: tags
        for meta in soup.find_all("meta", attrs={"name": True}):
            name = meta["name"].strip().lower()
            if name.startswith("twitter:"):
                og_data[name] = meta.get("content", "").strip()
                
        return og_data

    @classmethod
    def extract_all(cls, html: str) -> Dict[str, Any]:
        """
        Parses HTML and extracts JSON-LD and OpenGraph tags.
        """
        try:
            soup = BeautifulSoup(html, "lxml")
            return {
                "json_ld": cls.extract_json_ld(soup),
                "opengraph": cls.extract_opengraph(soup)
            }
        except Exception as e:
            logger.error(f"Error extracting structured data: {e}")
            return {"json_ld": [], "opengraph": {}}
