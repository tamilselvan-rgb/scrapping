"""
Enrichment for Denkmal 2026 exhibitors.
Fills missing domains via Serper and normalizes output fields.
"""

import os
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

ENV_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv(ENV_PATH)
SERPER_API_KEY = os.getenv("SERPER_API_KEY")

DENKMAL_LINKEDIN_URLS = {
    "https://www.linkedin.com/showcase/98585645",
    "https://linkedin.com/showcase/98585645",
}

GENERIC_EMAIL_HOSTS = {
    "gmail.com", "gmx.de", "gmx.net", "web.de", "t-online.de", "yahoo.de", "yahoo.com",
    "hotmail.com", "hotmail.de", "outlook.de", "outlook.com", "freenet.de", "icloud.com",
}

BLACKLISTED_DOMAINS = {
    "denkmal-leipzig.de",
    "leipziger-messe.de",
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "xing.com",
    "pinterest.com",
    "wikipedia.org",
    "yellowpages.com",
    "yelp.com",
    "google.com",
}

COUNTRY_MAP = {
    "DEUTSCHLAND": "Germany",
    "GERMANY": "Germany",
    "DE": "Germany",
    "ÖSTERREICH": "Austria",
    "OESTERREICH": "Austria",
    "AUSTRIA": "Austria",
    "AT": "Austria",
    "SCHWEIZ": "Switzerland",
    "SWITZERLAND": "Switzerland",
    "CH": "Switzerland",
    "FRANKREICH": "France",
    "FRANCE": "France",
    "FR": "France",
    "ITALIEN": "Italy",
    "ITALY": "Italy",
    "IT": "Italy",
    "BELGIEN": "Belgium",
    "BELGIUM": "Belgium",
    "BE": "Belgium",
    "NIEDERLANDE": "Netherlands",
    "NETHERLANDS": "Netherlands",
    "NL": "Netherlands",
    "POLEN": "Poland",
    "POLAND": "Poland",
    "PL": "Poland",
    "UNITED KINGDOM": "United Kingdom",
    "UK": "United Kingdom",
    "GROSSBRITANNIEN": "United Kingdom",
    "GROßBRITANNIEN": "United Kingdom",
    "GB": "United Kingdom",
    "UNITED STATES": "United States",
    "USA": "United States",
    "US": "United States",
    "SPANIEN": "Spain",
    "SPAIN": "Spain",
    "ES": "Spain",
    "DÄNEMARK": "Denmark",
    "DAENEMARK": "Denmark",
    "DENMARK": "Denmark",
    "DK": "Denmark",
    "CZECH REPUBLIC": "Czech Republic",
    "CZECHIA": "Czech Republic",
    "HUNGARY": "Hungary",
    "ROMANIA": "Romania",
    "SWEDEN": "Sweden",
    "NORWAY": "Norway",
    "FINLAND": "Finland",
    "IRELAND": "Ireland",
    "PORTUGAL": "Portugal",
    "GREECE": "Greece",
    "LUXEMBOURG": "Luxembourg",
    "SLOVAKIA": "Slovakia",
    "SLOVENIA": "Slovenia",
    "CROATIA": "Croatia",
    "ESTONIA": "Estonia",
    "LATVIA": "Latvia",
    "LITHUANIA": "Lithuania",
    "UKRAINE": "Ukraine",
    "TURKEY": "Turkey",
    "CHINA": "China",
    "JAPAN": "Japan",
    "INDIA": "India",
}


def normalize_country(raw_country: str) -> str:
    if not raw_country:
        return "Germany"
    cleaned = raw_country.strip().upper()
    return COUNTRY_MAP.get(cleaned, raw_country.strip())


def clean_domain(url_or_domain: Optional[str]) -> str:
    if not url_or_domain:
        return ""
    value = url_or_domain.strip()
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    try:
        netloc = urlparse(value).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        if not netloc or any(blocked in netloc for blocked in BLACKLISTED_DOMAINS):
            return ""
        return netloc
    except Exception:
        return ""


def search_serper(company_name: str, city: str = "") -> Dict:
    if not SERPER_API_KEY or not company_name:
        return {}
    query = f'"{company_name}" official website 2026'
    if city:
        query += f" {city}"
    headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}
    try:
        resp = requests.post(
            "https://google.serper.dev/search",
            headers=headers,
            json={"q": query, "num": 8},
            timeout=12,
        )
        if resp.status_code == 200:
            return resp.json()
    except requests.RequestException:
        pass
    return {}


def parse_serper_results(data: Dict) -> Tuple[str, str, str, str]:
    domain = ""
    phone = ""
    email = ""
    linkedin_url = ""

    kg = data.get("knowledgeGraph", {})
    if kg.get("website"):
        domain = clean_domain(kg.get("website"))
    if kg.get("phone"):
        phone = str(kg.get("phone")).strip()

    for org in data.get("organic", []):
        link = org.get("link", "")
        snippet = org.get("snippet", "")
        title = org.get("title", "")
        combined = f"{title} {snippet}"

        if not domain:
            domain = clean_domain(link)
        if not email:
            match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", combined)
            if match:
                email = match.group(0)
        if not phone:
            match = re.search(
                r"(?:\+?\d{1,4}[-.\s]?)?\(?\d{2,5}\)?[-.\s]?\d{3,5}[-.\s]?\d{3,5}",
                combined,
            )
            if match:
                phone = match.group(0).strip()
        if not linkedin_url and "linkedin.com" in link.lower():
            linkedin_url = link

    return domain, phone, email, linkedin_url


def crawl_website_for_contacts(domain: str) -> Tuple[str, str, str]:
    if not domain:
        return "", "", ""
    headers = {"User-Agent": HEADERS_USER_AGENT}
    base_url = f"https://{domain}"
    found_email = ""
    found_phone = ""
    found_linkedin = ""

    def inspect_html(html: str) -> None:
        nonlocal found_email, found_phone, found_linkedin
        soup = BeautifulSoup(html, "html.parser")
        if not found_email:
            for node in soup.select('a[href^="mailto:"]'):
                found_email = node["href"].replace("mailto:", "").split("?")[0].strip()
                break
        if not found_phone:
            for node in soup.select('a[href^="tel:"]'):
                found_phone = node["href"].replace("tel:", "").strip()
                break
        if not found_linkedin:
            for node in soup.select('a[href*="linkedin.com"]'):
                found_linkedin = node["href"].strip()
                break
        if not found_email:
            match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", soup.get_text(" ", strip=True))
            if match:
                found_email = match.group(0)

    try:
        resp = requests.get(base_url, headers=headers, timeout=8)
        if resp.status_code == 200:
            inspect_html(resp.text)
    except requests.RequestException:
        pass

    return found_email, found_phone, found_linkedin


HEADERS_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def is_valid_company_linkedin(url: str) -> bool:
    if not url:
        return False
    normalized = url.strip().rstrip("/")
    return normalized not in DENKMAL_LINKEDIN_URLS and "linkedin.com" in normalized.lower()


def enrich_record(raw: Dict) -> Dict:
    name = (raw.get("name") or "").strip()
    desc = (raw.get("desc") or "").strip()
    email = (raw.get("email") or "").strip()
    phone = (raw.get("phone") or "").strip()
    domain = clean_domain(raw.get("domain"))
    address = (raw.get("address") or "").strip()
    city = (raw.get("city") or "").strip()
    linkedin_url = (raw.get("linkedin_url") or "").strip()
    if not is_valid_company_linkedin(linkedin_url):
        linkedin_url = ""
    enrichment_source = "catalog_api"

    if not domain and email:
        match = re.search(r"@([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", email)
        if match:
            host = match.group(1).lower()
            if host not in GENERIC_EMAIL_HOSTS:
                domain = host
                enrichment_source = "corporate_email"

    if not domain:
        serper_data = search_serper(name, city=city)
        if serper_data:
            s_domain, s_phone, s_email, s_linkedin = parse_serper_results(serper_data)
            if s_domain:
                domain = s_domain
                enrichment_source = "serper_search"
            if not phone and s_phone:
                phone = s_phone
            if not email and s_email:
                email = s_email
            if not linkedin_url and is_valid_company_linkedin(s_linkedin):
                linkedin_url = s_linkedin
            if not desc:
                kg = serper_data.get("knowledgeGraph", {})
                if kg.get("description"):
                    desc = str(kg.get("description")).strip()

    if domain and (not email or not linkedin_url):
        w_email, w_phone, w_linkedin = crawl_website_for_contacts(domain)
        if not email and w_email:
            email = w_email
        if not phone and w_phone:
            phone = w_phone
        if not linkedin_url and is_valid_company_linkedin(w_linkedin):
            linkedin_url = w_linkedin

    return {
        "name": name,
        "desc": desc,
        "email": email,
        "phone": phone,
        "domain": domain,
        "address": address,
        "city": city,
        "linkedin_url": linkedin_url,
        "detail_url": raw.get("detail_url", ""),
        "fair_stand": raw.get("fair_stand", ""),
        "product_groups": raw.get("product_groups", ""),
        "country": normalize_country(raw.get("country_raw", "")),
        "enrichment_source": enrichment_source,
    }


def enrich_records(records: List[Dict]) -> List[Dict]:
    enriched = []
    for index, record in enumerate(records, start=1):
        enriched.append(enrich_record(record))
        if index % 25 == 0 or index == len(records):
            print(f"[PROGRESS] Enriched {index}/{len(records)} exhibitors")
    return enriched
