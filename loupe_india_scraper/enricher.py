"""
Enrichment module for LOUPE India Exhibitor dataset.
Handles country normalization, Serper Google Search fallback, and website contact crawling.
"""

import json
import os
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Load environment variables
ENV_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv(ENV_PATH)
SERPER_API_KEY = os.getenv("SERPER_API_KEY")

COUNTRY_CODE_MAP = {
    "in": "India",
    "fr": "France",
    "us": "United States",
    "de": "Germany",
    "gb": "United Kingdom",
    "uk": "United Kingdom",
    "it": "Italy",
    "ch": "Switzerland",
    "nl": "Netherlands",
    "be": "Belgium",
    "ca": "Canada",
    "cn": "China",
    "jp": "Japan",
    "ar": "Argentina",
    "ae": "United Arab Emirates",
}

BLACKLISTED_DOMAINS = {
    "linkedin.com", "facebook.com", "instagram.com", "youtube.com", "twitter.com", "x.com",
    "pinterest.com", "tiktok.com", "indiamart.com", "falconebiz.com", "zaubacorp.com",
    "tofler.in", "justdial.com", "tradeindia.com", "wikipedia.org", "yellowpages.com",
    "yelp.com", "exportersindia.com", "crunchbase.com", "glassdoor.co.in", "glassdoor.com",
    "zoominfo.com", "dnb.com", "ambitionbox.com", "economictimes.indiatimes.com",
    "connect2india.com", "cybex.in", "instahyre.com"
}


def normalize_country(country_code: str, exhibitor_name: str, detected_location: str = "") -> str:
    """Normalize country code or name to full English country name."""
    if country_code:
        code_clean = country_code.strip().lower()
        if code_clean in COUNTRY_CODE_MAP:
            return COUNTRY_CODE_MAP[code_clean]

    # Check location text
    if detected_location:
        loc_lower = detected_location.lower()
        for code, full_name in COUNTRY_CODE_MAP.items():
            if full_name.lower() in loc_lower:
                return full_name

    # Check company name cues
    name_lower = exhibitor_name.lower()
    if any(k in name_lower for k in ["pvt ltd", "pvt. ltd", "private limited", "india", "limited", "ltd"]):
        return "India"

    return "India"


def clean_domain(url_or_domain: Optional[str]) -> Optional[str]:
    """Clean and extract official website root domain."""
    if not url_or_domain:
        return None
    url_str = url_or_domain.strip().lower()
    if not url_str.startswith(("http://", "https://")):
        url_str = "https://" + url_str

    try:
        parsed = urlparse(url_str)
        netloc = parsed.netloc
        if not netloc:
            netloc = parsed.path.split("/")[0]

        netloc = netloc.split(":")[0].strip()
        if netloc.startswith("www."):
            netloc = netloc[4:]

        if not netloc or "." not in netloc:
            return None

        for blacklisted in BLACKLISTED_DOMAINS:
            if netloc == blacklisted or netloc.endswith("." + blacklisted):
                return None

        return netloc
    except Exception:
        return None


def extract_emails(text: str) -> List[str]:
    """Extract and validate corporate email addresses from text."""
    raw_emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
    valid_emails = []
    for em in raw_emails:
        em_clean = em.strip().rstrip(".")
        em_lower = em_clean.lower()
        if any(ext in em_lower for ext in [".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".css", ".js"]):
            continue
        if any(b in em_lower for b in ["sentry", "wixpress", "example.com", "domain.com", "email.com"]):
            continue
        if len(em_clean) > 5 and "." in em_clean.split("@")[-1]:
            valid_emails.append(em_clean)
    return valid_emails


def extract_phones(text: str) -> List[str]:
    """Extract plausible telephone / mobile numbers from text, filtering out postal PIN codes."""
    # Look for phone patterns
    candidates = re.findall(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,5}\)?[-.\s]?\d{3,5}[-.\s]?\d{3,5}", text)
    valid_phones = []
    for cand in candidates:
        cand_clean = cand.strip()
        digits = re.sub(r"\D", "", cand_clean)
        # Phone numbers should have 8 to 14 digits
        if 8 <= len(digits) <= 14:
            # Exclude Indian 6-digit PIN codes or repeated numbers
            if len(set(digits)) > 2:
                valid_phones.append(cand_clean)
    return valid_phones


def search_serper(exhibitor_name: str, country: str) -> Dict:
    """Fallback Google search using Serper API."""
    if not SERPER_API_KEY:
        return {}

    query = f'"{exhibitor_name}" official website {country}'
    headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {"q": query}

    try:
        resp = requests.post("https://google.serper.dev/search", headers=headers, json=payload, timeout=12)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"[WARN] Serper request failed for '{exhibitor_name}': {e}")
    return {}


def parse_serper_results(serper_data: Dict) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Parse domain, phone, email, and address from Serper response."""
    domain = None
    phone = None
    email = None
    location = None

    # 1. Knowledge Graph
    kg = serper_data.get("knowledgeGraph", {})
    if kg:
        if kg.get("website"):
            domain = clean_domain(kg.get("website"))
        if kg.get("phone"):
            phone = kg.get("phone").strip()
        if kg.get("address"):
            location = kg.get("address").strip()

    # 2. Organic Results
    organic = serper_data.get("organic", [])
    for org in organic:
        link = org.get("link", "")
        snippet = org.get("snippet", "")
        title = org.get("title", "")
        combined_text = f"{title} {snippet}"

        if not domain:
            dom = clean_domain(link)
            if dom:
                domain = dom

        if not email:
            found_emails = extract_emails(combined_text)
            if found_emails:
                email = found_emails[0]

        if not phone:
            found_phones = extract_phones(combined_text)
            if found_phones:
                phone = found_phones[0]

        if not location:
            # Check for city / state / PIN code cues
            pin_match = re.search(r"(\b[1-9][0-9]{5}\b)", snippet)
            if pin_match:
                # Snippet likely contains address details
                loc_cand = snippet.split(".")[0].strip()
                if len(loc_cand) > 10:
                    location = loc_cand

    return domain, phone, email, location


def crawl_website_for_contacts(domain: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Crawl homepage and contact pages of a company website for email, phone, and address."""
    if not domain:
        return None, None, None

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    base_url = f"https://{domain}"

    found_email = None
    found_phone = None
    found_location = None

    def inspect_html(html_text: str, current_url: str):
        nonlocal found_email, found_phone, found_location
        soup = BeautifulSoup(html_text, "html.parser")

        # 1. Mailto links
        if not found_email:
            for mailto in soup.select('a[href^="mailto:"]'):
                m_href = mailto["href"].replace("mailto:", "").split("?")[0].strip()
                if m_href and "@" in m_href:
                    found_email = m_href
                    break

        # 2. Tel links
        if not found_phone:
            for tel in soup.select('a[href^="tel:"]'):
                t_href = tel["href"].replace("tel:", "").strip()
                if len(re.sub(r"\D", "", t_href)) >= 8:
                    found_phone = t_href
                    break

        # 3. Text regex
        text = soup.get_text(" ", strip=True)
        if not found_email:
            emails = extract_emails(text)
            if emails:
                found_email = emails[0]

        if not found_phone:
            phones = extract_phones(text)
            if phones:
                found_phone = phones[0]

        if not found_location:
            addr_elem = soup.find("address")
            if addr_elem:
                addr_text = addr_elem.get_text(" ", strip=True)
                if len(addr_text) > 10:
                    found_location = addr_text

    try:
        resp = requests.get(base_url, headers=headers, timeout=8)
        if resp.status_code == 200:
            inspect_html(resp.text, base_url)
            soup = BeautifulSoup(resp.text, "html.parser")

            # Look for Contact page links
            contact_urls = []
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                link_text = a.get_text(strip=True).lower()
                if any(k in href.lower() or k in link_text for k in ["contact", "about", "reach-us", "reachus"]):
                    full_link = urljoin(base_url, href)
                    if urlparse(full_link).netloc == urlparse(base_url).netloc and full_link not in contact_urls:
                        contact_urls.append(full_link)

            for curl in contact_urls[:2]:
                if found_email and found_phone and found_location:
                    break
                try:
                    cresp = requests.get(curl, headers=headers, timeout=8)
                    if cresp.status_code == 200:
                        inspect_html(cresp.text, curl)
                except Exception:
                    pass
    except Exception:
        pass

    return found_email, found_phone, found_location


def enrich_record(raw_item: Dict) -> Dict:
    """Enrich a single raw exhibitor record."""
    name = raw_item.get("name", "").strip()
    raw_country_code = raw_item.get("country_code", "")
    portal_website = raw_item.get("portal_website", "")
    stand = raw_item.get("stand", "")

    domain = clean_domain(portal_website)
    country = normalize_country(raw_country_code, name)
    contact_number = None
    mail = None
    location = None
    enrichment_source = "portal_direct" if domain else ""

    # Serper Search if domain is missing or contact info needed
    serper_data = search_serper(name, country)
    if serper_data:
        s_domain, s_phone, s_email, s_loc = parse_serper_results(serper_data)
        if not domain and s_domain:
            domain = s_domain
            enrichment_source = "serper_search"
        if not contact_number and s_phone:
            contact_number = s_phone
        if not mail and s_email:
            mail = s_email
        if not location and s_loc:
            location = s_loc

    # Fallback to crawling the website if missing email or phone
    if domain and (not mail or not contact_number or not location):
        w_email, w_phone, w_loc = crawl_website_for_contacts(domain)
        if not mail and w_email:
            mail = w_email
        if not contact_number and w_phone:
            contact_number = w_phone
        if not location and w_loc:
            location = w_loc

    # Default location if street address not found
    if not location:
        location = country

    return {
        "exhibitor_name": name,
        "domain": domain or "",
        "contact_number": contact_number or "",
        "mail": mail or "",
        "location": location,
        "country": country,
        "fair_stand": stand,
        "enrichment_source": enrichment_source or "portal_catalog",
    }
