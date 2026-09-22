"""
Enrichment module for FACTS Belgium Exhibitor dataset.
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

COUNTRY_NAME_MAP = {
    # English & Dutch/French/German variations -> Full English Country Name
    "belgium": "Belgium",
    "belgië": "Belgium",
    "belgique": "Belgium",
    "belgien": "Belgium",
    "netherlands": "Netherlands",
    "nederland": "Netherlands",
    "the netherlands": "Netherlands",
    "pays-bas": "Netherlands",
    "france": "France",
    "frankrijk": "France",
    "germany": "Germany",
    "duitsland": "Germany",
    "allemagne": "Germany",
    "deutschland": "Germany",
    "italy": "Italy",
    "italië": "Italy",
    "italie": "Italy",
    "spain": "Spain",
    "spanje": "Spain",
    "espagne": "Spain",
    "united kingdom": "United Kingdom",
    "uk": "United Kingdom",
    "verenigd koninkrijk": "United Kingdom",
    "royaume-uni": "United Kingdom",
    "great britain": "United Kingdom",
    "england": "United Kingdom",
    "united states": "United States",
    "usa": "United States",
    "us": "United States",
    "verenigde staten": "United States",
    "états-unis": "United States",
    "japan": "Japan",
    "japon": "Japan",
    "poland": "Poland",
    "polen": "Poland",
    "pologne": "Poland",
    "switzerland": "Switzerland",
    "zwitserland": "Switzerland",
    "suisse": "Switzerland",
    "austria": "Austria",
    "oostenrijk": "Austria",
    "autriche": "Austria",
    "canada": "Canada",
    "china": "China",
    "chine": "China",
    "sweden": "Sweden",
    "zweden": "Sweden",
    "denmark": "Denmark",
    "denemarken": "Denmark",
    "norway": "Norway",
    "noorwegen": "Norway",
    "finland": "Finland",
    "ireland": "Ireland",
    "ierland": "Ireland",
    "portugal": "Portugal",
    "greece": "Greece",
    "griekenland": "Greece",
    "czech republic": "Czech Republic",
    "tsjechië": "Czech Republic",
    "slovakia": "Slovakia",
    "slowakije": "Slovakia",
    "hungary": "Hungary",
    "hongarije": "Hungary",
    "romania": "Romania",
    "roemenië": "Romania",
    "bulgaria": "Bulgaria",
    "bulgarije": "Bulgaria",
    "croatia": "Croatia",
    "kroatië": "Croatia",
    "slovenia": "Slovenia",
    "slovenië": "Slovenia",
    "estonia": "Estonia",
    "estland": "Estonia",
    "latvia": "Latvia",
    "letland": "Latvia",
    "lithuania": "Lithuania",
    "litouwen": "Lithuania",
    "luxembourg": "Luxembourg",
    "luxemburg": "Luxembourg",
    "india": "India",
    "indië": "India",
    "australia": "Australia",
    "australië": "Australia",
    "south korea": "South Korea",
    "zuid-korea": "South Korea",
    "korea": "South Korea",
}

BLACKLISTED_DOMAINS = {
    "facts.be", "easyfairs.com", "easyfairsgroup.com", "easyfairsassets.com",
    "jobs.easyfairs.be", "heroes.live", "heroes-world.be", "zendesk.com",
    "google.com", "iubenda.com", "visitcloud.com", "facebook.com",
    "instagram.com", "youtube.com", "twitter.com", "x.com", "discord.gg",
    "discord.com", "linkedin.com", "pinterest.com", "tiktok.com",
    "wikipedia.org", "yellowpages.com", "yelp.com", "goldenpages.be",
    "infobel.com", "trendstop.knack.be", "companyweb.be", "etsy.com",
    "ebay.com", "amazon.com", "amazon.de", "amazon.fr", "patreon.com",
    "bsky.app", "researchgate.net", "aliexpress.com"
}


def normalize_country(location_text: str) -> str:
    """Extract and normalize country to full English name."""
    if not location_text:
        return "Belgium"

    loc_lower = location_text.lower().strip()
    # Check comma separated parts
    parts = [p.strip() for p in loc_lower.split(",")]
    if len(parts) > 1:
        last_part = parts[-1]
        for key, full_name in COUNTRY_NAME_MAP.items():
            if key == last_part or last_part.endswith(" " + key):
                return full_name

    # Check words across the whole location
    for key, full_name in COUNTRY_NAME_MAP.items():
        if re.search(rf"\b{re.escape(key)}\b", loc_lower):
            return full_name

    return "Belgium"


def clean_domain(url_or_domain: Optional[str]) -> Optional[str]:
    """Clean and extract official root domain."""
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
        if any(b in em_lower for b in ["sentry", "wixpress", "example.com", "domain.com", "easyfairs", "facts.be"]):
            continue
        if len(em_clean) > 5 and "." in em_clean.split("@")[-1]:
            valid_emails.append(em_clean)
    return valid_emails


def extract_phones(text: str) -> List[str]:
    """Extract plausible telephone / mobile numbers from text."""
    candidates = re.findall(r"(?:\+?\d{1,4}[-.\s]?)?\(?\d{2,5}\)?[-.\s]?\d{3,5}[-.\s]?\d{3,5}", text)
    valid_phones = []
    for cand in candidates:
        cand_clean = cand.strip()
        digits = re.sub(r"\D", "", cand_clean)
        if 8 <= len(digits) <= 15:
            if len(set(digits)) > 2:
                valid_phones.append(cand_clean)
    return valid_phones


def search_serper(exhibitor_name: str, country: str) -> Dict:
    """Fallback Google search using Serper API."""
    if not SERPER_API_KEY:
        return {}

    query = f'"{exhibitor_name}" official website {country}'.strip()
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
    address = None

    # 1. Knowledge Graph
    kg = serper_data.get("knowledgeGraph", {})
    if kg:
        if kg.get("website"):
            domain = clean_domain(kg.get("website"))
        if kg.get("phone"):
            phone = kg.get("phone").strip()
        if kg.get("address"):
            address = kg.get("address").strip()

    # 2. Organic Results
    organic = serper_data.get("organic", [])
    for org in organic:
        link = org.get("link", "")
        snippet = org.get("snippet", "")
        title = org.get("title", "")
        combined_text = f"{title} {snippet}"

        if not domain:
            # Check snippet for explicit Website: ...
            web_match = re.search(r"(?:Website|Web|Site)\s*:\s*https?://(?:www\.)?([a-zA-Z0-9-]+\.[a-zA-Z]{2,})", snippet, re.IGNORECASE)
            if web_match:
                dom = clean_domain(web_match.group(1))
                if dom:
                    domain = dom

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

    return domain, phone, email, address


def crawl_website_for_contacts(domain: str) -> Tuple[Optional[str], Optional[str]]:
    """Crawl homepage and contact page of a company website for email and phone."""
    if not domain:
        return None, None

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    base_url = f"https://{domain}"

    found_email = None
    found_phone = None

    def inspect_html(html_text: str):
        nonlocal found_email, found_phone
        soup = BeautifulSoup(html_text, "html.parser")

        # Mailto links
        if not found_email:
            for mailto in soup.select('a[href^="mailto:"]'):
                m_href = mailto["href"].replace("mailto:", "").split("?")[0].strip()
                if m_href and "@" in m_href:
                    found_email = m_href
                    break

        # Tel links
        if not found_phone:
            for tel in soup.select('a[href^="tel:"]'):
                t_href = tel["href"].replace("tel:", "").strip()
                if len(re.sub(r"\D", "", t_href)) >= 8:
                    found_phone = t_href
                    break

        # Text regex
        text = soup.get_text(" ", strip=True)
        if not found_email:
            emails = extract_emails(text)
            if emails:
                found_email = emails[0]

        if not found_phone:
            phones = extract_phones(text)
            if phones:
                found_phone = phones[0]

    try:
        resp = requests.get(base_url, headers=headers, timeout=8)
        if resp.status_code == 200:
            inspect_html(resp.text)
            if not found_email or not found_phone:
                soup = BeautifulSoup(resp.text, "html.parser")
                contact_urls = []
                for a in soup.find_all("a", href=True):
                    href = a["href"].strip()
                    link_text = a.get_text(strip=True).lower()
                    if any(k in href.lower() or k in link_text for k in ["contact", "about", "over-ons", "contactez", "kontakt"]):
                        full_link = urljoin(base_url, href)
                        if urlparse(full_link).netloc == urlparse(base_url).netloc and full_link not in contact_urls:
                            contact_urls.append(full_link)

                for curl in contact_urls[:2]:
                    if found_email and found_phone:
                        break
                    try:
                        cresp = requests.get(curl, headers=headers, timeout=8)
                        if cresp.status_code == 200:
                            inspect_html(cresp.text)
                    except Exception:
                        pass
    except Exception:
        pass

    return found_email, found_phone


def enrich_record(raw_item: Dict) -> Dict:
    """Enrich a single raw exhibitor record from FACTS Belgium."""
    name = raw_item.get("name", "").strip()
    stand = raw_item.get("stand", "").strip()
    raw_location = raw_item.get("location", "").strip()
    website_url = raw_item.get("website_url", "").strip()
    detail_url = raw_item.get("detail_url", "").strip()

    country = normalize_country(raw_location)
    domain = clean_domain(website_url)
    contact_number = None
    mail = None
    location = raw_location or country
    enrichment_source = "profile_direct" if domain else ""

    # Serper Search if domain is missing or contact info needed
    serper_data = search_serper(name, country)
    if serper_data:
        s_domain, s_phone, s_email, s_addr = parse_serper_results(serper_data)
        if not domain and s_domain:
            domain = s_domain
            enrichment_source = "serper_search"
        if not contact_number and s_phone:
            contact_number = s_phone
        if not mail and s_email:
            mail = s_email
        if (not location or location == country) and s_addr:
            location = s_addr

    # Fallback to crawling the website if missing email or phone
    if domain and (not mail or not contact_number):
        w_email, w_phone = crawl_website_for_contacts(domain)
        if not mail and w_email:
            mail = w_email
        if not contact_number and w_phone:
            contact_number = w_phone

    return {
        "exhibitor_name": name,
        "domain": domain or "",
        "contact_number": contact_number or "",
        "mail": mail or "",
        "location": location,
        "country": country,
        "fair_stand": stand,
        "detail_url": detail_url,
        "enrichment_source": enrichment_source or "profile_catalog",
    }
