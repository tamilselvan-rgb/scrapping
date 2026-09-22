import os
import re
import urllib.parse
import logging
from typing import Dict, Any, List, Optional
import requests
from dotenv import load_dotenv

logger = logging.getLogger("offerta_scraper.enricher")

# Load root .env file
ENV_PATH = r"d:\habsy\scrapping\.env"
load_dotenv(ENV_PATH)
SERPER_API_KEY = os.getenv("SERPER_API_KEY")

BLACKLISTED_DOMAINS = {
    "linkedin.com", "facebook.com", "instagram.com", "youtube.com", "twitter.com",
    "x.com", "wikipedia.org", "yellowpages.com", "yelp.com", "tripadvisor.com",
    "amazon.com", "ebay.com", "alibaba.com", "aliexpress.com", "crunchbase.com",
    "bloomberg.com", "northdata.de", "northdata.com", "firmenwissen.de", "unternehmensregister.de",
    "bundesanzeiger.de", "cylex.de", "dasoertliche.de", "dastelefonbuch.de", "wlw.de",
    "wer-liefert-was.de", "offerta.de", "messe-karlsruhe.de", "kompass.com",
    "web2.cylex.de", "meinestadt.de", "telefonbuch.de", "handelsregister.ai",
    "handelsregister.de", "online-handelsregister.de", "companyhouse.de", "firmendaten.com"
}

KNOWN_DOMAINS = {
    "(Rhöni) Litz Holding GmbH & Co. KG": "rhoeni.de",
    "Verbraucherzentrale Baden-Württemberg e.V.": "vz-bw.de",
    "Striezelwerk": "striezelwerk.de",
    "Tapas locas Sandra Mahler": "tapaslocas.de",
}

GENERIC_EMAIL_HOSTS = {
    "gmail.com", "gmx.de", "gmx.net", "web.de", "t-online.de", "yahoo.de", "yahoo.com",
    "hotmail.com", "hotmail.de", "outlook.de", "outlook.com", "freenet.de", "icloud.com",
    "aol.com", "mail.de", "posteo.de", "arcor.de", "me.com"
}

# Mapping of German and ISO country designations to full English country names
COUNTRY_MAP = {
    "DEUTSCHLAND": "Germany",
    "DE": "Germany",
    "GERMANY": "Germany",
    "ÖSTERREICH": "Austria",
    "OESTERREICH": "Austria",
    "AT": "Austria",
    "AUSTRIA": "Austria",
    "SCHWEIZ": "Switzerland",
    "CH": "Switzerland",
    "SWITZERLAND": "Switzerland",
    "FRANKREICH": "France",
    "FR": "France",
    "FRANCE": "France",
    "ITALIEN": "Italy",
    "IT": "Italy",
    "ITALY": "Italy",
    "BELGIEN": "Belgium",
    "BE": "Belgium",
    "BELGIUM": "Belgium",
    "NIEDERLANDE": "Netherlands",
    "NL": "Netherlands",
    "NETHERLANDS": "Netherlands",
    "POLEN": "Poland",
    "PL": "Poland",
    "POLAND": "Poland",
    "ESTLAND": "Estonia",
    "EE": "Estonia",
    "ESTONIA": "Estonia",
    "GROSSBRITANNIEN": "United Kingdom",
    "GROßBRITANNIEN": "United Kingdom",
    "GB": "United Kingdom",
    "UK": "United Kingdom",
    "UNITED KINGDOM": "United Kingdom",
    "INDIEN": "India",
    "IN": "India",
    "INDIA": "India",
    "SPANIEN": "Spain",
    "ES": "Spain",
    "SPAIN": "Spain",
    "DÄNEMARK": "Denmark",
    "DAENEMARK": "Denmark",
    "DK": "Denmark",
    "DENMARK": "Denmark",
}

def clean_domain(url: Optional[str]) -> str:
    """Extracts and standardizes the root domain from a website URL."""
    if not url:
        return ""
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "http://" + url
    try:
        parsed = urllib.parse.urlparse(url)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        # Remove any port
        netloc = netloc.split(":")[0]
        return netloc
    except Exception:
        return url.strip().lower()

def normalize_country(raw_country: Optional[str]) -> str:
    """Ensures country is always returned as a full English country name, never a short code."""
    if not raw_country:
        return "Germany"  # Default for Offerta if unspecified
    cleaned = raw_country.strip().upper()
    return COUNTRY_MAP.get(cleaned, raw_country.strip().title())

class OffertaEnricher:
    def __init__(self, serper_api_key: Optional[str] = None):
        self.api_key = serper_api_key or SERPER_API_KEY
        if not self.api_key:
            logger.warning(f"SERPER_API_KEY not found in {ENV_PATH}! Serper fallback will be disabled.")
        else:
            logger.info("SERPER_API_KEY loaded successfully.")

    def search_domain_via_serper(self, company_name: str, city: str = "", country: str = "") -> Dict[str, str]:
        """
        Uses Serper Google Search to discover official website, address, and phone
        when the catalog profile lacks a website.
        """
        if not self.api_key or not company_name:
            return {"domain": "", "location": "", "contact_number": ""}

        # Clean noise from company name (e.g. leading brackets or telephone numbers in name)
        clean_name = re.sub(r"^\([^)]+\)\s*", "", company_name)
        clean_name = re.sub(r"\s+\d{6,}\s*$", "", clean_name).strip()

        query = f'"{clean_name}" official website'
        if city:
            query += f" {city}"
        if country:
            query += f" {country}"

        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json"
        }
        payload = {"q": query, "num": 8}

        try:
            resp = requests.post("https://google.serper.dev/search", json=payload, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()

                # 1. Inspect Knowledge Graph
                kg = data.get("knowledgeGraph", {})
                kg_web = kg.get("website", "")
                kg_addr = kg.get("address", "")
                kg_phone = kg.get("phone", "")

                if kg_web:
                    dom = clean_domain(kg_web)
                    if dom and not any(b in dom for b in BLACKLISTED_DOMAINS):
                        return {"domain": dom, "location": kg_addr, "contact_number": kg_phone}

                # 2. Inspect Organic Results
                for org in data.get("organic", []):
                    link = org.get("link", "")
                    dom = clean_domain(link)
                    if dom and not any(b in dom for b in BLACKLISTED_DOMAINS):
                        return {"domain": dom, "location": kg_addr, "contact_number": kg_phone}

        except Exception as e:
            logger.error(f"Error executing Serper search for '{company_name}': {e}")

        return {"domain": "", "location": "", "contact_number": ""}

    def enrich_records(self, raw_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Processes and enriches raw exhibitor records according to workspace scraping rules.
        """
        logger.info(f"Starting enrichment across {len(raw_records)} exhibitor records...")
        enriched: List[Dict[str, Any]] = []
        serper_count = 0

        for r in raw_records:
            company_name = (r.get("companyName") or "").strip()
            city = (r.get("city") or "").strip()
            raw_country = r.get("country", "")
            country_full = normalize_country(raw_country)
            
            # Format Location / Physical Address
            street = (r.get("street") or "").strip()
            zip_code = (r.get("zipCode") or "").strip()
            loc_parts = []
            if street:
                loc_parts.append(street)
            city_part = f"{zip_code} {city}".strip()
            if city_part:
                loc_parts.append(city_part)
            location = ", ".join(loc_parts)

            phone = (r.get("phone") or "").strip()
            email = (r.get("email") or "").strip()
            
            # Booth info
            booths = r.get("boothSet", [])
            hall_parts = []
            stand_parts = []
            if isinstance(booths, list):
                for b in booths:
                    if isinstance(b, dict):
                        b_name = b.get("buildingName") or b.get("hallId")
                        b_no = b.get("boothNo")
                        if b_name and b_name not in hall_parts:
                            hall_parts.append(b_name)
                        if b_no and b_no not in stand_parts:
                            stand_parts.append(b_no)

            fair_hall = ", ".join(hall_parts)
            fair_stand = ", ".join(stand_parts)

            # Web Domain Resolution
            raw_web = r.get("web") or r.get("webWithUtm") or ""
            domain = clean_domain(raw_web)
            source = "detail_api"

            # Tier 0 Fallback: Known curated brand domains
            if not domain and company_name in KNOWN_DOMAINS:
                domain = KNOWN_DOMAINS[company_name]
                source = "curated_brand_domain"

            # Tier 1 Fallback: Corporate email domain
            if not domain and email:
                mail_match = re.search(r'@([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', email)
                if mail_match:
                    host = mail_match.group(1).lower().strip()
                    if host not in GENERIC_EMAIL_HOSTS:
                        domain = host
                        source = "corporate_email"

            # Tier 2 Fallback: Serper Google Search
            if not domain:
                logger.info(f"Domain missing for '{company_name}'. Triggering Serper search...")
                serp_res = self.search_domain_via_serper(company_name, city=city, country=country_full)
                if serp_res.get("domain"):
                    domain = serp_res["domain"]
                    source = "serper_search"
                    serper_count += 1
                    # Enrich phone or location if missing
                    if not phone and serp_res.get("contact_number"):
                        phone = serp_res["contact_number"]
                    if not location and serp_res.get("location"):
                        location = serp_res["location"]

            detail_url = f"https://www.offerta.de/offerta-live/ausstellendenverzeichnis/?exhibitorId={r.get('id')}&name={r.get('companyNameForUrl', '')}"

            record = {
                "exhibitor_name": company_name,
                "domain": domain,
                "contact_number": phone,
                "mail": email,
                "location": location,
                "country": country_full,
                "fair_hall": fair_hall,
                "fair_stand": fair_stand,
                "detail_url": detail_url,
                "enrichment_source": source
            }
            enriched.append(record)

        logger.info(f"Enrichment finished. Total records: {len(enriched)} (Enriched via Serper: {serper_count}).")
        return enriched
