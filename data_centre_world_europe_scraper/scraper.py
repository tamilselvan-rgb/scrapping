#!/usr/bin/env python3
"""
DATA CENTRE WORLD EUROPE - MADRID 2026 Exhibitor Scraper
Portal: Tech Show Madrid (ASP.events SHOWOFF CMS)
Target URL: https://www.techshowmadrid.es/expositores?filters.events=Data%20Centre%20World
"""

import os
import re
import sys
import json
import time
import shutil
import logging
from pathlib import Path
from urllib.parse import urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
import pandas as pd
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Setup Logging & Environment
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Load .env (checking current dir and parent dirs)
env_path = Path(__file__).resolve().parent / '.env'
if not env_path.exists():
    env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

SERPER_API_KEY = os.getenv('SERPER_API_KEY', '')

# ---------------------------------------------------------------------------
# Constants & Country Normalization
# ---------------------------------------------------------------------------
EVENT_NAME = "DATA CENTRE WORLD EUROPE - MADRID 2026"
BASE_URL = "https://www.techshowmadrid.es"
EXHIBITOR_LIST_URL = "https://www.techshowmadrid.es/expositores?filters.events=Data%20Centre%20World"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    'Referer': 'https://www.techshowmadrid.es/data-centre-world'
}

KNOWN_COUNTRIES = {
    'SPAIN': 'Spain',
    'UNITED KINGDOM': 'United Kingdom',
    'FRANCE': 'France',
    'GERMANY': 'Germany',
    'ITALY': 'Italy',
    'NETHERLANDS': 'Netherlands',
    'BELGIUM': 'Belgium',
    'UNITED STATES': 'United States',
    'CHINA': 'China',
    'HONG KONG': 'Hong Kong',
    'PORTUGAL': 'Portugal',
    'IRELAND': 'Ireland',
    'POLAND': 'Poland',
    'SWEDEN': 'Sweden',
    'DENMARK': 'Denmark',
    'GREECE': 'Greece',
    'NEW ZEALAND': 'New Zealand',
    'SWITZERLAND': 'Switzerland',
    'TURKEY': 'Turkey',
    'AUSTRIA': 'Austria',
    'NORWAY': 'Norway',
    'FINLAND': 'Finland',
    'CANADA': 'Canada',
    'AUSTRALIA': 'Australia',
    'INDIA': 'India',
    'JAPAN': 'Japan',
    'SINGAPORE': 'Singapore'
}

CODE_MAP = {
    'ES': 'Spain', 'ESP': 'Spain',
    'UK': 'United Kingdom', 'GB': 'United Kingdom', 'GBR': 'United Kingdom',
    'FR': 'France', 'FRA': 'France',
    'DE': 'Germany', 'DEU': 'Germany',
    'IT': 'Italy', 'ITA': 'Italy',
    'NL': 'Netherlands', 'NLD': 'Netherlands',
    'BE': 'Belgium', 'BEL': 'Belgium',
    'US': 'United States', 'USA': 'United States',
    'CN': 'China', 'CHN': 'China',
    'HK': 'Hong Kong', 'HKG': 'Hong Kong',
    'PT': 'Portugal', 'PRT': 'Portugal',
    'IE': 'Ireland', 'IRL': 'Ireland',
    'PL': 'Poland', 'POL': 'Poland',
    'SE': 'Sweden', 'SWE': 'Sweden',
    'DK': 'Denmark', 'DNK': 'Denmark',
    'GR': 'Greece', 'GRC': 'Greece',
    'NZ': 'New Zealand', 'NZL': 'New Zealand',
    'CH': 'Switzerland', 'CHE': 'Switzerland',
    'TR': 'Turkey', 'TUR': 'Turkey',
    'AT': 'Austria', 'AUT': 'Austria',
    'NO': 'Norway', 'NOR': 'Norway',
    'FI': 'Finland', 'FIN': 'Finland',
    'CA': 'Canada', 'CAN': 'Canada',
    'AU': 'Australia', 'AUS': 'Australia',
    'IN': 'India', 'IND': 'India',
    'JP': 'Japan', 'JPN': 'Japan',
    'SG': 'Singapore', 'SGP': 'Singapore'
}

EMAIL_REGEX = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
PHONE_REGEX = re.compile(r'(?:\+\d{1,3}[\s.-]*)?(?:\(?\d{2,4}\)?[\s.-]*)?\d{3,4}[\s.-]*\d{3,4}')

IGNORE_EMAIL_PARTS = {
    'sentry', 'wixpress', 'domain.com', 'example.com', 'email.com', 'test.com',
    'bootstrap', 'jquery', 'cloudflare', 'schema.org', 'google', 'asp.events',
    'showoff', 'closerstillmedia'
}

SOCIAL_DOMAINS = {
    'facebook.com', 'twitter.com', 'x.com', 'linkedin.com', 'instagram.com',
    'youtube.com', 'wikipedia.org', 'yelp.com', 'yellowpages.com'
}

def clean_domain(url_or_domain: str) -> str:
    """Normalize URL to clean root domain."""
    if not url_or_domain:
        return ""
    val = url_or_domain.strip().lower()
    if not val.startswith(('http://', 'https://')):
        val = 'https://' + val
    try:
        parsed = urlparse(val)
        netloc = parsed.netloc.lower()
        if netloc.startswith('www.'):
            netloc = netloc[4:]
        netloc = netloc.split(':')[0]
        if any(netloc == sd or netloc.endswith('.' + sd) for sd in SOCIAL_DOMAINS) or 'techshowmadrid' in netloc or 'asp.events' in netloc:
            return ""
        return netloc
    except Exception:
        return ""

def normalize_country(country_str: str) -> str:
    """Ensure country is full English name, never code."""
    if not country_str:
        return ""
    c_clean = country_str.strip()
    c_upper = c_clean.upper()
    if c_upper in KNOWN_COUNTRIES:
        return KNOWN_COUNTRIES[c_upper]
    if c_upper in CODE_MAP:
        return CODE_MAP[c_upper]
    # Check word boundaries for codes or known countries
    for name_upper, canonical in KNOWN_COUNTRIES.items():
        if re.search(r'\b' + re.escape(name_upper) + r'\b', c_upper):
            return canonical
    for code, canonical in CODE_MAP.items():
        if re.search(r'\b' + re.escape(code) + r'\b', c_upper):
            return canonical
    return c_clean.title()

def clean_email(email_str: str) -> str:
    """Validate and clean email address."""
    if not email_str:
        return ""
    em = email_str.lower().strip().strip('.,;:()[]{}<>"\'')
    if any(ign in em for ign in IGNORE_EMAIL_PARTS):
        return ""
    if em.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.js', '.css', '.html')):
        return ""
    if '@' not in em or '.' not in em.split('@')[-1]:
        return ""
    return em

def clean_phone(phone_str: str) -> str:
    """Clean phone number."""
    if not phone_str:
        return ""
    ph = phone_str.strip()
    # Ensure digits count is between 7 and 18
    digits = re.sub(r'\D', '', ph)
    if 7 <= len(digits) <= 18:
        # Standardize format
        ph_clean = re.sub(r'\s+', ' ', ph)
        return ph_clean
    return ""

def normalize_company_name(name: str) -> str:
    """Normalize company name for deduplication."""
    if not name:
        return ""
    n = name.lower()
    for suff in [' sl', ' slu', ' sa', ' sau', ' s.l.', ' s.a.', ' ltd', ' llc', ' inc', ' gmbh', ' bv', ' b.v.', ' srl', ' s.r.l.']:
        if n.endswith(suff):
            n = n[:-len(suff)]
    n = re.sub(r'[^a-z0-9]', '', n)
    return n.strip()

# ---------------------------------------------------------------------------
# Serper Fallback Search
# ---------------------------------------------------------------------------
def search_serper(query: str) -> dict:
    """Query Serper API for domain, address, or phone."""
    if not SERPER_API_KEY:
        return {}
    try:
        url = "https://google.serper.dev/search"
        payload = json.dumps({"q": query, "num": 5})
        headers = {
            'X-API-KEY': SERPER_API_KEY,
            'Content-Type': 'application/json'
        }
        res = requests.post(url, headers=headers, data=payload, timeout=8)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        logger.debug(f"Serper error for query '{query}': {e}")
    return {}

def enrich_via_serper(company_name: str, location_hint: str) -> tuple[str, str, str, str]:
    """Fallback to Serper Google search."""
    domain, phone, address, location = "", "", "", ""
    query = f'"{company_name}" official website {location_hint}'.strip()
    data = search_serper(query)
    if not data:
        query = f'"{company_name}" official website'
        data = search_serper(query)
    
    if data:
        kg = data.get('knowledgeGraph', {})
        if kg:
            if kg.get('website'):
                domain = clean_domain(kg['website'])
            if kg.get('phoneNumber'):
                phone = clean_phone(kg['phoneNumber'])
            if kg.get('address'):
                address = kg['address'].strip()
        
        if not domain and data.get('organic'):
            for org in data['organic']:
                link = org.get('link', '')
                d = clean_domain(link)
                if d and not any(sd in d for sd in SOCIAL_DOMAINS):
                    domain = d
                    break
    return domain, phone, address, location

# ---------------------------------------------------------------------------
# Website Contact Probing
# ---------------------------------------------------------------------------
def probe_website_contacts(domain_or_url: str, session: requests.Session) -> tuple[str, str]:
    """Inspect company's official website pages for email and phone."""
    if not domain_or_url:
        return "", ""
    
    url = domain_or_url if domain_or_url.startswith(('http://', 'https://')) else f"https://{domain_or_url}"
    parsed = urlparse(url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    
    paths = ['', '/contacto', '/contact', '/contact-us', '/aviso-legal']
    found_emails = set()
    found_phones = set()
    
    for p in paths:
        target = root + p if p else url
        try:
            r = session.get(target, headers=HEADERS, timeout=5, allow_redirects=True)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                
                # Check links
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    if href.startswith('mailto:'):
                        em = clean_email(href.replace('mailto:', '').split('?')[0])
                        if em:
                            found_emails.add(em)
                    elif href.startswith('tel:'):
                        ph = clean_phone(href.replace('tel:', ''))
                        if ph:
                            found_phones.add(ph)
                            
                # Check regex in text
                text = soup.get_text(separator=' ')
                for em_candidate in EMAIL_REGEX.findall(text):
                    em = clean_email(em_candidate)
                    if em:
                        found_emails.add(em)
                
                if found_emails and found_phones:
                    break
        except Exception:
            continue
            
    best_email = sorted(list(found_emails))[0] if found_emails else ""
    best_phone = sorted(list(found_phones))[0] if found_phones else ""
    return best_email, best_phone

# ---------------------------------------------------------------------------
# Exhibitor List & Profile Scraping
# ---------------------------------------------------------------------------
def fetch_exhibitor_list(url: str, session: requests.Session) -> list[dict]:
    """Fetch all exhibitors from the event listing page."""
    logger.info(f"Fetching exhibitor directory from: {url}")
    res = session.get(url, headers=HEADERS, timeout=15)
    res.encoding = 'utf-8'
    soup = BeautifulSoup(res.text, 'html.parser')
    
    items = soup.find_all(class_='m-exhibitors-list__items__item')
    logger.info(f"Discovered {len(items)} exhibitor items on page")
    
    exhibitor_entries = []
    for it in items:
        # Extract name
        h2 = it.find('h2')
        name = h2.get_text(strip=True) if h2 else ""
        if not name:
            img = it.find('img')
            name = img.get('alt', '').strip() if img else ""
            
        # Extract profile URL from data-href
        data_href = it.get('data-href', '')
        m = re.search(r"openRemoteModal\('([^']+)'", data_href)
        modal_path = m.group(1) if m else ""
        
        # Stand
        stand_el = it.find(class_=lambda c: c and 'stand' in str(c))
        stand = stand_el.get_text(strip=True) if stand_el else ""
        
        if name and modal_path:
            profile_url = urljoin(BASE_URL, modal_path)
            exhibitor_entries.append({
                'name': name,
                'profile_url': profile_url,
                'stand': stand,
                'content_id': it.get('data-content-i-d', '')
            })
            
    return exhibitor_entries

def parse_profile_page(entry: dict, session: requests.Session) -> dict:
    """Visit exhibitor profile page and extract address, website, contacts."""
    profile_url = entry['profile_url']
    name = entry['name']
    
    domain = ""
    address = ""
    location = ""
    city = ""
    country = ""
    emails = []
    phones = []
    
    try:
        r = session.get(profile_url, headers=HEADERS, timeout=10)
        r.encoding = 'utf-8'
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            
            # Update name if more detailed
            title_el = soup.find(class_='m-exhibitor-entry__item__header__title')
            if title_el and title_el.get_text(strip=True):
                name = title_el.get_text(strip=True)
                
            # Website
            web_el = soup.find(class_='m-exhibitor-entry__item__body__contacts__additional__website')
            if web_el and web_el.find('a'):
                raw_web = web_el.find('a').get('href', '').strip()
                domain = clean_domain(raw_web)
            if not domain:
                logo_link = soup.find(class_='m-exhibitor-entry__item__body__contacts__logo')
                if logo_link and logo_link.find('a'):
                    domain = clean_domain(logo_link.find('a').get('href', ''))
                    
            # Address container
            addr_el = soup.find(class_='m-exhibitor-entry__item__body__contacts__address')
            if addr_el:
                raw_lines = [
                    l.strip() for l in addr_el.stripped_strings 
                    if l.lower() not in ['dirección', 'direccion', 'address']
                ]
                if raw_lines:
                    # Country is typically the last line
                    raw_country = raw_lines[-1]
                    country = normalize_country(raw_country)
                    
                    # Full address combining lines
                    address = ", ".join(raw_lines)
                    
                    # Determine city from remaining lines
                    # Format is often: Street, City, Region/State, PostalCode, Country
                    if len(raw_lines) >= 3:
                        city_candidate = raw_lines[1]
                        # Clean if it's all uppercase
                        city = city_candidate.title() if city_candidate.isupper() else city_candidate
                    elif len(raw_lines) == 2:
                        city = raw_lines[0].title() if raw_lines[0].isupper() else raw_lines[0]
            
            # Stand if not set
            if not entry.get('stand'):
                stand_el = soup.find(class_='m-exhibitor-entry__item__header__stand')
                if stand_el:
                    entry['stand'] = stand_el.get_text(strip=True)
                    
    except Exception as e:
        logger.warning(f"Failed to fetch profile {profile_url}: {e}")
        
    # Form clean location: <City>, <Country> or <Country>
    if city and country:
        # Avoid duplicate "Madrid, Madrid, Spain"
        location = f"{city}, {country}"
    elif country:
        location = country
    elif city:
        location = city

    # Fallback to Serper if domain is missing
    if not domain and SERPER_API_KEY:
        s_domain, s_phone, s_addr, s_loc = enrich_via_serper(name, location)
        if s_domain:
            domain = s_domain
        if s_phone:
            phones.append(s_phone)
        if not address and s_addr:
            address = s_addr
            if not country:
                country = "Spain" if "spain" in s_addr.lower() or "madrid" in s_addr.lower() else ""
                location = f"Madrid, {country}" if country == "Spain" else s_loc or country
                
    # Contact enrichment via official website
    if domain:
        w_email, w_phone = probe_website_contacts(domain, session)
        if w_email:
            emails.append(w_email)
        if w_phone:
            phones.append(w_phone)

    # Format structured contact: email | phone
    contact_parts = []
    if emails:
        contact_parts.append(emails[0])
    if phones:
        contact_parts.append(phones[0])
    contact = " | ".join(contact_parts)

    return {
        'exhibitor_name': name,
        'domain': domain,
        'contact': contact,
        'address': address,
        'location': location,
        'profile_url': profile_url
    }

# ---------------------------------------------------------------------------
# Deduplication & Data Quality
# ---------------------------------------------------------------------------
def deduplicate_exhibitors(records: list[dict]) -> list[dict]:
    """Deduplicate records by domain, profile URL, and normalized name."""
    seen_domains = set()
    seen_profiles = set()
    seen_names = set()
    unique_records = []
    
    # Sort to prioritize records with domain, contact, address
    def completeness_score(r):
        score = 0
        if r.get('domain'): score += 4
        if r.get('contact'): score += 3
        if r.get('address'): score += 2
        if r.get('location'): score += 1
        return score
        
    sorted_records = sorted(records, key=completeness_score, reverse=True)
    
    for r in sorted_records:
        domain = r.get('domain', '').strip().lower()
        profile = r.get('profile_url', '').strip()
        norm_name = normalize_company_name(r.get('exhibitor_name', ''))
        
        is_dup = False
        if domain and domain in seen_domains:
            is_dup = True
        elif profile and profile in seen_profiles:
            is_dup = True
        elif norm_name and norm_name in seen_names:
            is_dup = True
            
        if not is_dup:
            if domain:
                seen_domains.add(domain)
            if profile:
                seen_profiles.add(profile)
            if norm_name:
                seen_names.add(norm_name)
            unique_records.append(r)
            
    return sorted(unique_records, key=lambda x: x['exhibitor_name'].lower())

# ---------------------------------------------------------------------------
# Main Orchestrator
# ---------------------------------------------------------------------------
def main():
    start_time = time.time()
    logger.info("=" * 70)
    logger.info(f"Starting Scraper: {EVENT_NAME}")
    logger.info(f"Source URL: {EXHIBITOR_LIST_URL}")
    logger.info("=" * 70)

    # Base output directories
    script_dir = Path(__file__).resolve().parent
    output_dir = script_dir / 'output'
    output_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    
    # Step 1: Discover exhibitors from directory
    entries = fetch_exhibitor_list(EXHIBITOR_LIST_URL, session)
    total_discovered = len(entries)
    if not entries:
        logger.error("No exhibitors discovered! Exiting.")
        sys.exit(1)

    logger.info(f"Visiting and enriching {total_discovered} exhibitor profiles...")

    # Step 2: Concurrently scrape profiles and enrich contacts
    raw_results = []
    failed_profiles = 0
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_entry = {executor.submit(parse_profile_page, entry, session): entry for entry in entries}
        for idx, future in enumerate(as_completed(future_to_entry), 1):
            try:
                res = future.result()
                raw_results.append(res)
                if idx % 20 == 0 or idx == total_discovered:
                    logger.info(f"Progress: [{idx}/{total_discovered}] profiles processed")
            except Exception as exc:
                failed_profiles += 1
                logger.error(f"Error processing entry: {exc}")

    # Step 3: Deduplicate
    final_records = deduplicate_exhibitors(raw_results)
    total_deduped = len(final_records)

    # Clean records to only required fields
    clean_records = []
    for r in final_records:
        clean_records.append({
            'exhibitor_name': r['exhibitor_name'],
            'domain': r['domain'],
            'contact': r['contact'],
            'address': r['address'],
            'location': r['location']
        })

    # Step 4: Export Deliverables
    csv_primary = output_dir / 'exhibitors.csv'
    json_primary = output_dir / 'exhibitors.json'
    csv_user_named = output_dir / 'DATA CENTRE WORLD EUROPE .csv'
    csv_root_user_named = script_dir / 'DATA CENTRE WORLD EUROPE .csv'

    df = pd.DataFrame(clean_records)
    # Ensure column order
    cols = ['exhibitor_name', 'domain', 'contact', 'address', 'location']
    df = df[cols]

    # Save CSVs with utf-8-sig
    df.to_csv(csv_primary, index=False, encoding='utf-8-sig')
    df.to_csv(csv_user_named, index=False, encoding='utf-8-sig')
    df.to_csv(csv_root_user_named, index=False, encoding='utf-8-sig')

    # Save JSON
    with open(json_primary, 'w', encoding='utf-8') as f:
        json.dump(clean_records, f, ensure_ascii=False, indent=2)

    # Step 5: Calculate Statistics
    total_domain = sum(1 for r in clean_records if r['domain'])
    total_contact = sum(1 for r in clean_records if r['contact'])
    total_address = sum(1 for r in clean_records if r['address'])
    total_location = sum(1 for r in clean_records if r['location'])

    elapsed = time.time() - start_time

    # Print required summary format
    print("\n" + "=" * 70)
    print("EXECUTION SUMMARY")
    print("=" * 70)
    print(f"Event name: {EVENT_NAME}")
    print(f"Source URL: {EXHIBITOR_LIST_URL}")
    print("Scraping method used: HTML (Requests + BeautifulSoup)")
    print(f"Total exhibitors discovered: {total_discovered}")
    print(f"Total exhibitors after deduplication: {total_deduped}")
    print(f"Total exhibitors with domain: {total_domain}")
    print(f"Total exhibitors with contact: {total_contact}")
    print(f"Total exhibitors with address: {total_address}")
    print(f"Total exhibitors with location: {total_location}")
    print(f"Failed profile pages: {failed_profiles}")
    print(f"CSV output path: {csv_primary.resolve()}")
    print(f"JSON output path: {json_primary.resolve()}")
    print(f"User CSV output path: {csv_user_named.resolve()}")
    print(f"Total execution time: {elapsed:.2f} seconds")
    print("=" * 70)

    # Print sample records
    print("\nSample records (First 5):")
    for r in clean_records[:5]:
        print(f"• Name: {r['exhibitor_name']}")
        print(f"  Domain: {r['domain']}")
        print(f"  Contact: {r['contact']}")
        print(f"  Address: {r['address']}")
        print(f"  Location: {r['location']}\n")

if __name__ == '__main__':
    main()
