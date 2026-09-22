import os
import re
import json
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib3

# Suppress insecure HTTPS request warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

EVENT_NAME = "Ecomondo"
SOURCE_URL = "https://www.ecomondo.com/it/catalogo/espositori"
API_URL = "https://www.ecomondo.com/it/api/v1/filterDataObjects"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
CSV_PATH = os.path.join(OUTPUT_DIR, "exhibitors.csv")
JSON_PATH = os.path.join(OUTPUT_DIR, "exhibitors.json")

EMAIL_REGEX = re.compile(r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b')
PHONE_REGEX = re.compile(r'(?:\+?\d{1,4}[\s.-]?)?\(?\d{2,5}\)?[\s.-]?\d{3,5}[\s.-]?\d{2,6}')

DUMMY_EMAILS = [
    'exemple@', 'example@', 'nom@domaine', 'contact@domaine', 'prenom@', 'email@example', 
    'user@domain', 'test@test', 'js-cookie', 'sentry', 'wixpress', 'wordpress', 'support@github'
]

COUNTRY_MAP = {
    "italia": "Italy",
    "italy": "Italy",
    "germania": "Germany",
    "deutschland": "Germany",
    "germany": "Germany",
    "francia": "France",
    "france": "France",
    "spagna": "Spain",
    "españa": "Spain",
    "spain": "Spain",
    "regno unito": "United Kingdom",
    "united kingdom": "United Kingdom",
    "uk": "United Kingdom",
    "stati uniti": "United States",
    "united states": "United States",
    "usa": "United States",
    "svizzera": "Switzerland",
    "switzerland": "Switzerland",
    "austria": "Austria",
    "paesi bassi": "Netherlands",
    "olanda": "Netherlands",
    "netherlands": "Netherlands",
    "belgio": "Belgium",
    "belgium": "Belgium",
    "cina": "China",
    "china": "China",
    "turchia": "Turkey",
    "turkey": "Turkey",
    "polonia": "Poland",
    "poland": "Poland",
    "repubblica ceca": "Czech Republic",
    "czech republic": "Czech Republic",
    "grecia": "Greece",
    "greece": "Greece",
    "portogallo": "Portugal",
    "portugal": "Portugal",
    "svezia": "Sweden",
    "sweden": "Sweden",
    "norvegia": "Norway",
    "norway": "Norway",
    "danimarca": "Denmark",
    "denmark": "Denmark",
    "finlandia": "Finland",
    "finland": "Finland",
    "irlanda": "Ireland",
    "ireland": "Ireland",
    "romania": "Romania",
    "bulgaria": "Bulgaria",
    "croazia": "Croatia",
    "croatia": "Croatia",
    "slovenia": "Slovenia",
    "slovacchia": "Slovakia",
    "slovakia": "Slovakia",
    "ungheria": "Hungary",
    "hungary": "Hungary",
    "san marino": "San Marino",
    "israele": "Israel",
    "israel": "Israel",
    "canada": "Canada",
    "brasile": "Brazil",
    "brazil": "Brazil",
    "india": "India",
    "giappone": "Japan",
    "japan": "Japan"
}

def clean_domain(url):
    """Extract and normalize the company's official domain."""
    if not url:
        return ""
    if not url.startswith(('http://', 'https://')):
        url = 'http://' + url
    parsed = urlparse(url)
    netloc = parsed.netloc.lower().split(':')[0]
    if netloc.startswith('www.'):
        netloc = netloc[4:]
    # Avoid event portal domain
    if 'ecomondo' in netloc or 'iegexpo' in netloc:
        return ""
    return netloc.strip('/')

def clean_phone(p):
    """Format and clean telephone numbers."""
    if not p:
        return ""
    p = re.sub(r'^(?:tel[:.]?|telefono:?|phone:?)\s*', '', p, flags=re.IGNORECASE)
    p = re.sub(r'^[;,:.\s]+', '', p)
    p = re.sub(r'[\s.-]+', ' ', p).strip()
    return p

def clean_email(e):
    """Clean and validate email address."""
    if not e:
        return ""
    e = e.strip().lower()
    if any(dummy in e for dummy in DUMMY_EMAILS):
        return ""
    if e.endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg')):
        return ""
    return e

def normalize_name(name):
    """Normalize company name for comparison."""
    n = name.upper()
    n = n.replace('’', "'").replace('–', '-').replace('—', '-')
    n = re.sub(r'\s+', ' ', n)
    return n.strip()

def extract_country_and_location(address_str):
    """Determine full English country name and clean location (City, Country)."""
    if not address_str:
        return "Italy", "Italy"
    
    country = "Italy"
    lower_addr = address_str.lower()
    
    # Check if a known country exists in the address string
    for k, v in COUNTRY_MAP.items():
        if re.search(r'\b' + re.escape(k) + r'\b', lower_addr):
            country = v
            break
            
    # Extract city from Italian address pattern (e.g. 00149 ROMA , RM - Italia)
    city = ""
    # Look for 5-digit CAP followed by city name
    m = re.search(r'\b\d{4,5}\b\s+([A-Za-zÀ-ÿ\s\'-]+?)(?:\s*,|\s*-|\s*$)', address_str)
    if m:
        cand = m.group(1).strip()
        # Clean noise words
        if cand.lower() not in ['italia', 'italy', 'germany', 'france', 'spain', 'via', 'viale', 'piazza']:
            parts = cand.split('-')
            city = '-'.join(p.strip().title() for p in parts if p.strip())
            
    if city:
        location = f"{city}, {country}"
    else:
        location = country
        
    return country, location

def fetch_profile_details(session, item_data):
    """Fetch and parse detailed profile page for an exhibitor."""
    profile_url = item_data["profile_url"]
    name = item_data["name"]
    
    if not profile_url:
        return {
            "exhibitor_name": name,
            "domain": "",
            "contact": "",
            "address": "",
            "location": "Italy"
        }

    try:
        r = session.get(profile_url, timeout=12)
        if r.status_code != 200:
            return {
                "exhibitor_name": name,
                "domain": "",
                "contact": "",
                "address": "",
                "location": "Italy"
            }
        
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # 1. Address, Phone, Email from "Riferimenti"
        address_parts = []
        phone = ""
        email = ""
        
        ref_p = soup.find(lambda t: t.name == 'p' and t.get_text(strip=True).lower() == 'riferimenti')
        if ref_p:
            container = ref_p.parent
            for p_tag in container.find_all('p'):
                txt = p_tag.get_text(strip=True)
                txt_low = txt.lower()
                if txt_low == 'riferimenti':
                    continue
                if any(txt_low.startswith(pfx) for pfx in ['tel:', 'tel.', 'telefono:', 'phone:']):
                    phone = clean_phone(txt)
                elif any(txt_low.startswith(pfx) for pfx in ['email:', 'mail:', 'e-mail:']):
                    email = clean_email(re.sub(r'^(?:email:|mail:|e-mail:)\s*', '', txt, flags=re.IGNORECASE))
                elif '@' in txt and not email:
                    email = clean_email(txt)
                else:
                    address_parts.append(txt)
                    
        address = ", ".join(address_parts).strip(' ;,.-')
        
        # Check mailto & tel tags if not yet found
        for a in soup.find_all('a', href=True):
            h = a['href'].strip()
            if h.startswith('mailto:') and not email:
                email = clean_email(h.replace('mailto:', '').split('?')[0])
            elif h.startswith('tel:') and not phone:
                phone = clean_phone(h.replace('tel:', '').split('?')[0])
                
        # 2. Official Website
        website = ""
        web_p = soup.find(lambda t: t.name == 'p' and t.get_text(strip=True).lower() == 'website')
        if web_p:
            web_container = web_p.parent
            web_a = web_container.find('a', href=True)
            if web_a:
                website = web_a['href'].strip()
                
        domain = clean_domain(website)
        
        # 3. Clean Location
        country, location = extract_country_and_location(address)
        
        # 4. Format Contact
        contact_parts = []
        if email:
            contact_parts.append(email)
        if phone:
            contact_parts.append(phone)
        contact = " | ".join(contact_parts)
        
        return {
            "exhibitor_name": name,
            "domain": domain,
            "contact": contact,
            "address": address,
            "location": location
        }

    except Exception:
        return {
            "exhibitor_name": name,
            "domain": "",
            "contact": "",
            "address": "",
            "location": "Italy"
        }

def scrape_ecomondo():
    print(f"Starting scraper for: {EVENT_NAME}")
    print(f"Source URL: {SOURCE_URL}")
    print(f"Querying Direct API: {API_URL}")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
    })

    # Step 1: Query API to discover all official exhibitors
    payload = {
        'folder': '7435571',
        'type': 'digital-profiles',
        'itemsPerPage': '2000',
        'category': '',
        'country': '',
        'exhibitionEdition': '7306136',
        'page': 1,
        'pavilion': '',
        'province': '',
        'sub_category': '',
        'tags': '',
        'searchText': ''
    }

    try:
        resp = session.post(API_URL, json=payload, timeout=25)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"Error requesting API: {e}")
        return

    items = data.get('items', [])
    total_discovered = len(items)
    print(f"Discovered {total_discovered} exhibitors from official API.")

    # Step 2: Parse basic card data from each exhibitor
    parsed_exhibitors = []
    for item in items:
        html_content = item.get('content', '')
        card_soup = BeautifulSoup(html_content, 'html.parser')
        
        # Name
        name_tag = card_soup.find(class_='card-digitalprofile-name')
        name = name_tag.get_text(strip=True) if name_tag else ""
        if not name:
            continue
            
        clean_name = name.replace('’', "'").replace('–', '-').replace('—', '-').strip()
        
        # Detail Profile URL
        btn_tag = card_soup.find('a', class_='btn')
        rel_url = btn_tag['href'].strip() if (btn_tag and 'href' in btn_tag.attrs) else ""
        full_profile_url = urljoin("https://www.ecomondo.com", rel_url) if rel_url else ""
        
        parsed_exhibitors.append({
            "name": clean_name,
            "profile_url": full_profile_url
        })

    # Step 3: Deduplicate exhibitors
    deduped = []
    seen = set()
    for exh in parsed_exhibitors:
        norm = normalize_name(exh["name"])
        key = exh["profile_url"] if exh["profile_url"] else norm
        if key not in seen:
            seen.add(key)
            deduped.append(exh)

    total_deduped = len(deduped)
    print(f"Total exhibitors after deduplication: {total_deduped}")

    # Step 4: Enrich exhibitor profiles using parallel workers
    print(f"Enriching {total_deduped} profiles (using polite worker pool)...")
    final_records = []
    failed_profiles = []
    
    # Pre-create slots to maintain order
    results_ordered = [None] * total_deduped
    
    def worker(idx_exh):
        idx, exh = idx_exh
        res = fetch_profile_details(session, exh)
        if not res.get("address") and not res.get("domain") and not res.get("contact"):
            failed_profiles.append(exh["profile_url"])
        return idx, res

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(worker, (i, exh)): i for i, exh in enumerate(deduped)}
        completed_count = 0
        for future in as_completed(futures):
            idx, res = future.result()
            results_ordered[idx] = res
            completed_count += 1
            if completed_count % 100 == 0 or completed_count == total_deduped:
                print(f"  Processed {completed_count}/{total_deduped} exhibitors...")

    final_records = results_ordered

    # Step 5: Export clean CSV and JSON outputs
    df = pd.DataFrame(final_records, columns=[
        "exhibitor_name",
        "domain",
        "contact",
        "address",
        "location"
    ])

    # Export CSV with utf-8-sig
    df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")

    # Export JSON
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(final_records, f, ensure_ascii=False, indent=2)

    # Step 6: Print validation and end-of-run metrics
    print("\n" + "=" * 60)
    print("SCRAPING EXECUTION SUMMARY")
    print("=" * 60)
    print(f"Event name:                          {EVENT_NAME}")
    print(f"Source URL:                          {SOURCE_URL}")
    print(f"Scraping method used:                API + Profile Enrichment")
    print(f"Total exhibitors discovered:         {total_discovered}")
    print(f"Total exhibitors after deduplication:{total_deduped}")
    print(f"Total exhibitors with domain:        {sum(1 for r in final_records if r['domain'])}")
    print(f"Total exhibitors with contact:       {sum(1 for r in final_records if r['contact'])}")
    print(f"Total exhibitors with address:       {sum(1 for r in final_records if r['address'])}")
    print(f"Total exhibitors with location:      {sum(1 for r in final_records if r['location'])}")
    print(f"Failed profile pages:                {len(failed_profiles)}")
    print(f"CSV output path:                     {CSV_PATH}")
    print(f"JSON output path:                    {JSON_PATH}")
    print("=" * 60)

    print("\nSample Data (First 5 rows):")
    print(df.head(5).to_string(index=False))

if __name__ == "__main__":
    scrape_ecomondo()
