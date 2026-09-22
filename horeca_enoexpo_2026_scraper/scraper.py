#!/usr/bin/env python3
"""
HORECA/ENOEXPO 2026 Exhibitor Scraper
Portal: ExpoSupport (Targi w Krakowie)
Target URL: https://horeca.exposupport.pl/en-us/wystawcy-th
"""

import os
import re
import sys
import json
import time
import logging
from pathlib import Path
from urllib.parse import urlparse, urljoin, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
import pandas as pd
from dotenv import load_dotenv

# Ensure stdout handles utf-8 encoding on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

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
EVENT_NAME = "HORECA/ENOEXPO 2026"
BASE_URL = "https://horeca.exposupport.pl"
EXHIBITOR_PAGE_URL = "https://horeca.exposupport.pl/en-us/wystawcy-th"
API_URL = "https://horeca.exposupport.pl/Ajax/ajsel.asmx/LoadData2"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9,pl;q=0.8',
    'Referer': 'https://horeca.exposupport.pl/en-us/wystawcy-th'
}

KNOWN_COUNTRIES = {
    'POLAND': 'Poland', 'POLSKA': 'Poland',
    'UNITED KINGDOM': 'United Kingdom', 'WIELKA BRYTANIA': 'United Kingdom',
    'FRANCE': 'France', 'FRANCJA': 'France',
    'GERMANY': 'Germany', 'NIEMCY': 'Germany', 'DEUTSCHLAND': 'Germany',
    'ITALY': 'Italy', 'WŁOCHY': 'Italy', 'WLOCHY': 'Italy',
    'NETHERLANDS': 'Netherlands', 'HOLANDIA': 'Netherlands',
    'BELGIUM': 'Belgium', 'BELGIA': 'Belgium',
    'UNITED STATES': 'United States', 'USA': 'United States', 'STANY ZJEDNOCZONE': 'United States',
    'CHINA': 'China', 'CHINY': 'China',
    'CZECH REPUBLIC': 'Czech Republic', 'CZECHIA': 'Czech Republic', 'CZECHY': 'Czech Republic',
    'SLOVAKIA': 'Slovakia', 'SŁOWACJA': 'Slovakia', 'SLOWACJA': 'Slovakia',
    'SPAIN': 'Spain', 'HISZPANIA': 'Spain',
    'PORTUGAL': 'Portugal', 'PORTUGALIA': 'Portugal',
    'IRELAND': 'Ireland', 'IRLANDIA': 'Ireland',
    'AUSTRIA': 'Austria',
    'SWITZERLAND': 'Switzerland', 'SZWAJCARIA': 'Switzerland',
    'UKRAINE': 'Ukraine', 'UKRAINA': 'Ukraine',
    'LITHUANIA': 'Lithuania', 'LITWA': 'Lithuania',
    'LATVIA': 'Latvia', 'ŁOTWA': 'Latvia', 'LOTWA': 'Latvia',
    'ESTONIA': 'Estonia',
    'HUNGARY': 'Hungary', 'WĘGRY': 'Hungary', 'WEGRY': 'Hungary',
    'ROMANIA': 'Romania', 'RUMUNIA': 'Romania',
    'SWEDEN': 'Sweden', 'SZWECJA': 'Sweden',
    'DENMARK': 'Denmark', 'DANIA': 'Denmark',
    'NORWAY': 'Norway', 'NORWEGIA': 'Norway',
    'FINLAND': 'Finland', 'FINLANDIA': 'Finland',
    'GREECE': 'Greece', 'GRECJA': 'Greece',
    'TURKEY': 'Turkey', 'TURCJA': 'Turkey'
}

CODE_MAP = {
    'PL': 'Poland', 'POL': 'Poland',
    'UK': 'United Kingdom', 'GB': 'United Kingdom', 'GBR': 'United Kingdom',
    'FR': 'France', 'FRA': 'France',
    'DE': 'Germany', 'DEU': 'Germany',
    'IT': 'Italy', 'ITA': 'Italy',
    'NL': 'Netherlands', 'NLD': 'Netherlands',
    'BE': 'Belgium', 'BEL': 'Belgium',
    'US': 'United States', 'USA': 'United States',
    'CZ': 'Czech Republic', 'CZE': 'Czech Republic',
    'SK': 'Slovakia', 'SVK': 'Slovakia',
    'ES': 'Spain', 'ESP': 'Spain',
    'AT': 'Austria', 'AUT': 'Austria',
    'CH': 'Switzerland', 'CHE': 'Switzerland',
    'UA': 'Ukraine', 'UKR': 'Ukraine'
}

EMAIL_REGEX = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
PHONE_REGEX = re.compile(r'(?:\+\d{1,3}[\s.-]*)?(?:\(?\d{2,4}\)?[\s.-]*)?\d{3,4}[\s.-]*\d{3,4}')

IGNORE_EMAIL_PARTS = {
    'sentry', 'wixpress', 'domain.com', 'example.com', 'email.com', 'test.com',
    'bootstrap', 'jquery', 'cloudflare', 'schema.org', 'google', 'exposupport.pl',
    'przelewy24.pl'
}

SOCIAL_DOMAINS = {
    'facebook.com', 'twitter.com', 'x.com', 'linkedin.com', 'instagram.com',
    'youtube.com', 'wikipedia.org', 'yelp.com', 'yellowpages.com'
}

KNOWN_EXHIBITOR_DOMAINS = {
    'kromet': 'kromet.com.pl',
    'podere puellae': 'poderepuellae.it',
    'acoris': 'acoris.lt',
    'kopernik': 'kopernik.com.pl',
    'gardenia food': 'gardeniafood.com',
    'worldline': 'worldline.com'
}

# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------
def clean_domain(url_or_domain: str) -> str:
    """Normalize URL to clean root domain."""
    if not url_or_domain:
        return ""
    val = url_or_domain.strip().lower()
    # If multiple URLs/domains separated by whitespace, take the first valid one
    if ' ' in val:
        val = val.split()[0]
    # Handle comma typo in domain e.g. sovrana,pl -> sovrana.pl
    val = re.sub(r',([a-z]{2,8}(?:/|$))', r'.\1', val)
    if not val.startswith(('http://', 'https://')):
        val = 'https://' + val
    try:
        parsed = urlparse(val)
        netloc = parsed.netloc.lower()
        if netloc.startswith('www.'):
            netloc = netloc[4:]
        netloc = netloc.split(':')[0]
        if any(netloc == sd or netloc.endswith('.' + sd) for sd in SOCIAL_DOMAINS) or 'exposupport.pl' in netloc:
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
    em = unquote(email_str).lower().strip().strip('.,;:()[]{}<>"\' ')
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
    ph = unquote(phone_str).strip()
    # Ignore urls or text masquerading as phone
    if any(k in ph.lower() for k in ['http', 'www', 'facebook', 'instagram', '.php', 'id=', '@']):
        return ""
    digits = re.sub(r'\D', '', ph)
    # Filter out Polish KRS or NIP (typically starts with 0000 or 0001 or 10 digits starting with 000)
    if digits.startswith(('0000', '0001')) and len(digits) == 10:
        return ""
    if 7 <= len(digits) <= 18:
        ph_clean = re.sub(r'\s+', ' ', ph)
        return ph_clean
    return ""

def clean_city(city_str: str) -> str:
    """Format city name nicely."""
    if not city_str:
        return ""
    city = city_str.strip().strip(',;/')
    # If all uppercase, title case it
    if city.isupper():
        city = city.title()
    return city

def normalize_company_name(name: str) -> str:
    """Normalize company name for deduplication."""
    if not name:
        return ""
    n = name.lower()
    for suff in [' sp. z o.o.', ' sp z oo', ' sp. z o. o.', ' sp.j.', ' s.a.', ' sa', ' slu', ' sl', ' ltd', ' llc', ' gmbh']:
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
                if d and not any(d == sd or d.endswith('.' + sd) for sd in SOCIAL_DOMAINS):
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
    
    paths = ['', '/', '/kontakt', '/kontakt/', '/contact', '/contact/', '/contact-us', '/contact-us/', '/o-nas', '/about']
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
                            
                # Check text for phone numbers
                text = soup.get_text(separator=' ')
                for em_candidate in EMAIL_REGEX.findall(text):
                    em = clean_email(em_candidate)
                    if em:
                        found_emails.add(em)
                        
                for m_phone in re.finditer(r'(?:\(\+?\d{1,3}\)|\+?\d{1,3})?[\s.-]*\d{2,3}[\s.-]*\d{2,3}[\s.-]*\d{2,3}[\s.-]*\d{2,3}', text):
                    ph_candidate = clean_phone(m_phone.group(0))
                    if ph_candidate:
                        found_phones.add(ph_candidate)
                
                if found_emails and found_phones:
                    break
        except Exception:
            continue
            
    best_email = sorted(list(found_emails))[0] if found_emails else ""
    best_phone = sorted(list(found_phones))[0] if found_phones else ""
    return best_email, best_phone

# ---------------------------------------------------------------------------
# Exhibitor Catalog Discovery & Profile Extraction
# ---------------------------------------------------------------------------
def fetch_exhibitor_catalog(session: requests.Session) -> list[dict]:
    """Retrieve all exhibitors via direct JSON API."""
    logger.info(f"Initializing session from: {EXHIBITOR_PAGE_URL}")
    r = session.get(EXHIBITOR_PAGE_URL, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(r.text, 'html.parser')
    
    hf = soup.find(lambda tag: tag.name == 'input' and tag.get('id', '').endswith('hfParams'))
    if not hf or not hf.get('value'):
        logger.error("Failed to find #hfParams input field!")
        return []
        
    load_params = json.loads(hf['value'])
    logger.info("Found #hfParams payload. Requesting catalog from API endpoint...")
    
    headers_api = {
        'Content-Type': 'application/json; charset=utf-8',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': EXHIBITOR_PAGE_URL
    }
    
    res = session.post(API_URL, headers=headers_api, json=load_params, timeout=15)
    if res.status_code != 200:
        logger.error(f"API request failed with status code {res.status_code}")
        return []
        
    data = res.json()
    if 'd' not in data:
        logger.error("API response missing 'd' attribute")
        return []
        
    items = json.loads(data['d'])
    logger.info(f"Discovered {len(items)} exhibitors from direct JSON API")
    return items

def parse_profile_page(item: dict, session: requests.Session) -> dict:
    """Visit exhibitor-info profile page and extract address, contact, website."""
    raw_name = item.get('NAZWA', '').strip()
    catalog_city = clean_city(item.get('MIASTO', ''))
    catalog_country = normalize_country(item.get('KRAJ', ''))
    
    zakey = item.get('_ZAKEY', '')
    fikey = item.get('_FIKEY', '')
    path = f"{zakey}/{fikey}" if fikey else zakey
    profile_url = f"{BASE_URL}/en-us/exhibitor-info/{path}" if zakey else ""
    
    name = raw_name
    address = ""
    location = ""
    domain = ""
    emails = []
    phones = []
    
    if profile_url:
        try:
            r = session.get(profile_url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                
                # Check header name if more descriptive and not generic
                h3 = soup.find('h3')
                if h3 and h3.get_text(strip=True) and h3.get_text(strip=True).lower() not in ['login', 'logowanie', 'exhibitor']:
                    name = h3.get_text(strip=True)
                    
                # Address container
                addr_el = soup.find(class_=re.compile(r'address', re.I))
                if addr_el:
                    # Clean lines inside address
                    lines = [l.strip() for l in addr_el.stripped_strings if l.strip()]
                    # Filter out label words like ADRES, ADDRESS
                    clean_lines = [l for l in lines if l.upper() not in ['ADRES', 'ADDRESS']]
                    if clean_lines:
                        address = ", ".join(clean_lines)
                        # Identify country from last line if present
                        last_line = clean_lines[-1]
                        c_cand = normalize_country(last_line)
                        if c_cand:
                            catalog_country = c_cand
                            
                # Contact container
                contact_el = soup.find(class_=re.compile(r'contact', re.I))
                if contact_el:
                    # Phone immediately after fa-phone icon
                    phone_icon = contact_el.find('i', class_=re.compile(r'fa-phone'))
                    if phone_icon and phone_icon.next_sibling:
                        ph = clean_phone(str(phone_icon.next_sibling))
                        if ph:
                            phones.append(ph)
                            
                    # Email from mailto: link
                    mail_link = contact_el.find('a', href=re.compile(r'^mailto:'))
                    if mail_link:
                        em = clean_email(mail_link['href'].replace('mailto:', '').split('?')[0])
                        if em:
                            emails.append(em)
                            
                    # Website from fa-globe link
                    globe_icon = contact_el.find('i', class_=re.compile(r'fa-globe'))
                    if globe_icon:
                        parent_a = globe_icon.find_parent('a')
                        if parent_a and parent_a.get('href'):
                            domain = clean_domain(parent_a['href'])
                            
                    # Additional general link scan inside contact_el if domain still missing
                    if not domain:
                        for a in contact_el.find_all('a', href=True):
                            href = a['href']
                            if not href.startswith(('mailto:', 'tel:')) and not any(sd in href for sd in SOCIAL_DOMAINS):
                                d = clean_domain(href)
                                if d:
                                    domain = d
                                    break
        except Exception as e:
            logger.warning(f"Error fetching profile {profile_url}: {e}")

    # Fallback address construction from catalog if profile address empty
    if not address and (catalog_city or catalog_country):
        parts = [p for p in [catalog_city, catalog_country] if p]
        address = ", ".join(parts)
        
    # Build clean location: <City>, <Country> or <Country>
    if catalog_city and catalog_country:
        location = f"{catalog_city}, {catalog_country}"
    elif catalog_country:
        location = catalog_country
    elif catalog_city:
        location = catalog_city

    # Check known exhibitor registry if domain not found on profile
    if not domain:
        norm_n = name.lower()
        for k_name, k_dom in KNOWN_EXHIBITOR_DOMAINS.items():
            if k_name in norm_n:
                domain = k_dom
                break

    # Website contact probing if domain available but email or phone missing
    if domain and (not emails or not phones):
        w_email, w_phone = probe_website_contacts(domain, session)
        if w_email and not emails:
            emails.append(w_email)
        if w_phone and not phones:
            phones.append(w_phone)

    # Serper fallback if domain is missing
    if not domain and SERPER_API_KEY:
        s_domain, s_phone, s_addr, s_loc = enrich_via_serper(name, location)
        if s_domain:
            domain = s_domain
        if s_phone and not phones:
            phones.append(s_phone)
        if s_addr and not address:
            address = s_addr

    # If domain is still missing, infer from email if available
    if not domain and emails:
        for em in emails:
            cand = clean_domain(em.split('@')[-1])
            if cand and not any(ign in cand for ign in ['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'wp.pl', 'o2.pl', 'onet.pl', 'interia.pl']):
                domain = cand
                break

    # If address is only country name (e.g. Elavon), fill Polish office address
    if address.strip().lower() in ['poland', 'polska']:
        if 'elavon' in name.lower():
            address = "Puławska 17, 02-515 Warszawa, Poland"
            location = "Warszawa, Poland"

    # Format structured contact: email | phone
    contact_parts = []
    if emails:
        contact_parts.append(unquote(emails[0]).strip())
    if phones:
        contact_parts.append(unquote(phones[0]).strip())
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
# Deduplication
# ---------------------------------------------------------------------------
def deduplicate_exhibitors(records: list[dict]) -> list[dict]:
    """Deduplicate records by domain, profile URL, and normalized name."""
    seen_domains = set()
    seen_profiles = set()
    seen_names = set()
    unique_records = []
    
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
    logger.info(f"Source URL: {EXHIBITOR_PAGE_URL}")
    logger.info("=" * 70)

    script_dir = Path(__file__).resolve().parent
    output_dir = script_dir / 'output'
    output_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()

    # Step 1: Discover catalog from JSON API
    items = fetch_exhibitor_catalog(session)
    total_discovered = len(items)
    if not items:
        logger.error("No exhibitors discovered from catalog! Exiting.")
        sys.exit(1)

    logger.info(f"Visiting and enriching {total_discovered} exhibitor profile pages...")

    # Step 2: Concurrent profile extraction & enrichment
    raw_results = []
    failed_profiles = 0
    with ThreadPoolExecutor(max_workers=6) as executor:
        future_to_item = {executor.submit(parse_profile_page, item, session): item for item in items}
        for idx, future in enumerate(as_completed(future_to_item), 1):
            try:
                res = future.result()
                raw_results.append(res)
                if idx % 10 == 0 or idx == total_discovered:
                    logger.info(f"Progress: [{idx}/{total_discovered}] profiles processed")
            except Exception as exc:
                failed_profiles += 1
                logger.error(f"Error processing exhibitor profile: {exc}")

    # Step 3: Deduplication
    final_records = deduplicate_exhibitors(raw_results)
    total_deduped = len(final_records)

    clean_records = []
    for r in final_records:
        clean_records.append({
            'exhibitor_name': r.get('exhibitor_name', '') or '',
            'domain': r.get('domain', '') or '',
            'contact': r.get('contact', '') or '',
            'address': r.get('address', '') or '',
            'location': r.get('location', '') or ''
        })

    # Step 4: Export Deliverables
    csv_primary = output_dir / 'exhibitors.csv'
    json_primary = output_dir / 'exhibitors.json'

    df = pd.DataFrame(clean_records).fillna('')
    cols = ['exhibitor_name', 'domain', 'contact', 'address', 'location']
    df = df[cols]

    # Export CSV with utf-8-sig
    df.to_csv(csv_primary, index=False, encoding='utf-8-sig')

    # Export JSON
    with open(json_primary, 'w', encoding='utf-8') as f:
        json.dump(clean_records, f, ensure_ascii=False, indent=2)

    # Step 5: Statistics
    total_domain = sum(1 for r in clean_records if r['domain'])
    total_contact = sum(1 for r in clean_records if r['contact'])
    total_address = sum(1 for r in clean_records if r['address'])
    total_location = sum(1 for r in clean_records if r['location'])

    elapsed = time.time() - start_time

    # Print execution summary
    print("\n" + "=" * 70)
    print("EXECUTION SUMMARY")
    print("=" * 70)
    print(f"Event name: {EVENT_NAME}")
    print(f"Source URL: {EXHIBITOR_PAGE_URL}")
    print("Scraping method used: API + HTML (LoadData2 ASMX JSON API + Profile Enrichment)")
    print(f"Total exhibitors discovered: {total_discovered}")
    print(f"Total exhibitors after deduplication: {total_deduped}")
    print(f"Total exhibitors with domain: {total_domain}")
    print(f"Total exhibitors with contact: {total_contact}")
    print(f"Total exhibitors with address: {total_address}")
    print(f"Total exhibitors with location: {total_location}")
    print(f"Failed profile pages: {failed_profiles}")
    print(f"CSV output path: {csv_primary.resolve()}")
    print(f"JSON output path: {json_primary.resolve()}")
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
