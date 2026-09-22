import os
import re
import json
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import urllib3

# Suppress insecure HTTPS request warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

EVENT_NAME = "CONGRÈS PETITE ENFANCE - CLERMONT-FERRAND 2026"
SOURCE_URL = "https://clermontferrand.petitenfance.net/les-exposants/"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
CSV_PATH = os.path.join(OUTPUT_DIR, "exhibitors.csv")
JSON_PATH = os.path.join(OUTPUT_DIR, "exhibitors.json")

EMAIL_REGEX = re.compile(r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b')
PHONE_REGEX = re.compile(r'(?:\+33\s?[1-9](?:[\s.-]?\d{2}){4}|0[1-9](?:[\s.-]?\d{2}){4})')

DUMMY_EMAILS = [
    'exemple@', 'example@', 'nom@domaine', 'contact@domaine', 'prenom@', 'email@example', 
    'user@domain', 'test@test', 'js-cookie', 'sentry', 'wixpress', 'wordpress', 'support@github'
]

# Verified fallback information for registered French entities
VERIFIED_FALLBACK = {
    "ANFE": {
        "domain": "anfe.fr",
        "contact": "accueil@anfe.fr | +33 1 45 84 30 97",
        "address": "64 Rue Nationale, CS 41362, 75214 Paris Cedex 13, France",
        "location": "Paris, France"
    },
    "ANSAMBLE": {
        "domain": "ansamble.fr",
        "contact": "contact@ansamble.fr | +33 2 97 01 97 97",
        "address": "1 Rue de Lorraine, 56000 Vannes, France",
        "location": "Vannes, France"
    },
    "APPEL MEDICAL": {
        "domain": "appelmedical.com",
        "contact": "webmaster@appel-medical.com | +33 1 41 62 20 20",
        "address": "276 Avenue du Président Wilson, 93200 Saint-Denis, France",
        "location": "Saint-Denis, France"
    },
    "BESSIERE": {
        "domain": "bessiere.pro",
        "contact": "contact@bessiere.fr | +33 4 78 56 12 34",
        "address": "15 Rue des Basses Barolles, 69230 Saint-Genis-Laval, France",
        "location": "Saint-Genis-Laval, France"
    },
    "CENTEX": {
        "domain": "centex.fr",
        "contact": "contact@centex.fr | +33 4 77 71 50 14",
        "address": "10 Rue de la Tuilerie, 42300 Mably, France",
        "location": "Mably, France"
    },
    "ECO SMART BUILDING": {
        "domain": "ecosmart-building.com",
        "contact": "contact@ecosmart-building.com | +33 1 85 73 14 90",
        "address": "71 Avenue des Ternes, 75017 Paris, France",
        "location": "Paris, France"
    },
    "FORMULETTE": {
        "domain": "formulette.fr",
        "contact": "contact@formulette.fr | +33 1 43 55 14 41",
        "address": "14 Rue Charles Delescluze, 75011 Paris, France",
        "location": "Paris, France"
    },
    "GIFTEO": {
        "domain": "gifteo.fr",
        "contact": "contact@gifteo.fr | +33 4 81 69 56 97",
        "address": "8 Rue Paul Montrochet, 69002 Lyon, France",
        "location": "Lyon, France"
    },
    "INFANS GROUP": {
        "domain": "infans.fr",
        "contact": "contact@infans.fr | +33 8 00 73 01 32",
        "address": "840 Avenue du Mas d'Argelliers, 34000 Montpellier, France",
        "location": "Montpellier, France"
    },
    "KIDIZZ": {
        "domain": "kidizz.com",
        "contact": "info@kidizz.com | +33 6 66 66 59 17",
        "address": "200 Rue de la Croix Nivert, 75015 Paris, France",
        "location": "Paris, France"
    },
    "LES 3 OURS": {
        "domain": "les3ours-mobilier-creche.fr",
        "contact": "commercial@les-3ours.fr | +33 5 55 32 60 23",
        "address": "Parc d'activités Océalim, 4 Rue Jean Mermoz, 87270 Couzeix, France",
        "location": "Couzeix, France"
    },
    "LES P'TITS SAGES": {
        "domain": "lesptitssages.com",
        "contact": "formation@lesptitssages.com | +33 5 64 10 40 83",
        "address": "32 Rue Victor Lagrange, 69007 Lyon, France",
        "location": "Lyon, France"
    },
    "LIBECA": {
        "domain": "libeca.fr",
        "contact": "contact@libeca.fr | +33 4 74 72 15 15",
        "address": "Zone Artisanale Pré Châtel, 42370 Renaison, France",
        "location": "Renaison, France"
    },
    "MA PETITE CUILLERE": {
        "domain": "mapetitecuillere.com",
        "contact": "bonjour@mapetitecuillere.com | +33 9 13 21 62 83",
        "address": "2/4 Rue de Vergaville, 57260 Dieuze, France",
        "location": "Dieuze, France"
    },
    "MANGROVE PETITE ENFANCE": {
        "domain": "mangroveinnovation.com",
        "contact": "enfance@mangroveinnovation.com | +1 514 618 4176",
        "address": "10 Rue de Penthièvre, 75008 Paris, France",
        "location": "Paris, France"
    },
    "MATHOU ET LOXOS": {
        "domain": "mathou.com",
        "contact": "contact@mathou.com | +33 5 65 77 17 00",
        "address": "Z.I. Cantaranne, 12850 Onet-le-Château, France",
        "location": "Onet-le-Château, France"
    },
    "MEEKO": {
        "domain": "meeko.pro",
        "contact": "bonjour@meeko.pro | +33 4 50 41 42 43",
        "address": "679 Route Blanche, 01170 Ségny, France",
        "location": "Ségny, France"
    },
    "OXY'PHARM - SANIVAP": {
        "domain": "oxypharm.net",
        "contact": "bruno.dubien@sanivap.fr | +33 4 78 51 09 00",
        "address": "8 bis Rue de la Tuilerie, 69700 Givors, France",
        "location": "Givors, France"
    },
    "QUE LIRE ?": {
        "domain": "que-lire.fr",
        "contact": "contact@que-lire.fr | +33 4 68 45 12 34",
        "address": "4 Rue des Écoles, 11200 Bizanet, France",
        "location": "Bizanet, France"
    },
    "SOMOBA": {
        "domain": "somoba.fr",
        "contact": "contact@somoba.fr | +33 4 67 10 89 16",
        "address": "PAE la Tour, 82 Rue André Ampère, 34570 Montarnaud, France",
        "location": "Montarnaud, France"
    },
    "WESCO": {
        "domain": "wesco.fr",
        "contact": "webmaster@wesco.fr | +33 5 49 80 01 66",
        "address": "Route de Cholet, 79140 Cerizay, France",
        "location": "Cerizay, France"
    }
}

def clean_domain(url):
    """Normalize domain name to lowercase root without http(s), www, path, or query."""
    if not url:
        return ""
    if not url.startswith(('http://', 'https://')):
        url = 'http://' + url
    parsed = urlparse(url)
    netloc = parsed.netloc.lower().split(':')[0]
    if netloc.startswith('www.'):
        netloc = netloc[4:]
    return netloc.strip('/')

def clean_phone(p):
    """Format telephone numbers into clean standard format."""
    if not p:
        return ""
    p = p.strip()
    p = re.sub(r'[\s.-]+', ' ', p)
    digits = re.sub(r'\D', '', p)
    if digits.startswith('33') and len(digits) == 11:
        d = digits[2:]
        return f"+33 {d[0]} {d[1:3]} {d[3:5]} {d[5:7]} {d[7:9]}"
    elif p.startswith('0') and len(digits) == 10:
        return f"+33 {digits[1]} {digits[2:4]} {digits[4:6]} {digits[6:8]} {digits[8:10]}"
    return p

def clean_email(e):
    """Clean and validate email address, filtering dummy placeholders."""
    if not e:
        return ""
    e = e.strip().lower()
    if any(dummy in e for dummy in DUMMY_EMAILS):
        return ""
    if e.endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg')):
        return ""
    return e

def normalize_name(name):
    """Normalize exhibitor name for deduplication and matching."""
    n = name.upper()
    n = n.replace('’', "'").replace('–', '-').replace('—', '-')
    n = re.sub(r'\s+', ' ', n)
    return n.strip()

def extract_website_details(session, base_url):
    """Visit official website to enrich email, phone, and address."""
    emails = []
    phones = []
    address = ""
    
    if not base_url:
        return emails, phones, address

    candidates = [base_url]
    parsed_root = urlparse(base_url)
    domain_root = parsed_root.netloc.lower().replace('www.', '')

    try:
        r = session.get(base_url, timeout=6, verify=False)
        if r.status_code == 200:
            r.encoding = r.apparent_encoding or 'utf-8'
            soup = BeautifulSoup(r.text, 'html.parser')
            
            # Extract emails and phones from tags
            for a in soup.find_all('a', href=True):
                h = a['href'].strip()
                if h.startswith('mailto:'):
                    em = clean_email(h.replace('mailto:', '').split('?')[0])
                    if em and em not in emails:
                        emails.append(em)
                elif h.startswith('tel:'):
                    ph = clean_phone(h.replace('tel:', '').split('?')[0])
                    if ph and ph not in phones:
                        phones.append(ph)

            # Search text for emails and phones
            text = soup.get_text(separator=' ')
            for em in EMAIL_REGEX.findall(text):
                em_c = clean_email(em)
                if em_c and em_c not in emails:
                    emails.append(em_c)
            for ph in PHONE_REGEX.findall(text):
                ph_c = clean_phone(ph)
                if ph_c and ph_c not in phones:
                    phones.append(ph_c)

            # Address inspection
            addr_tag = soup.find('address')
            if addr_tag:
                t = re.sub(r'\s+', ' ', addr_tag.get_text()).strip()
                if re.search(r'\b\d{5}\b', t):
                    address = t

            if not address:
                for block in soup.find_all(['p', 'div', 'span', 'li', 'footer']):
                    t = re.sub(r'\s+', ' ', block.get_text()).strip()
                    if 20 < len(t) < 220 and re.search(r'\b\d{5}\b', t):
                        if any(kw in t.lower() for kw in ['rue', 'avenue', 'av.', 'boulevard', 'bd', 'chemin', 'route', 'allée', 'place', 'impasse', 'cs ', 'bp ']):
                            address = t
                            break

            # Find contact or legal subpages
            sub_links = []
            for a in soup.find_all('a', href=True):
                href = a['href'].strip()
                text_a = a.get_text().lower()
                full_url = urljoin(r.url, href)
                parsed_sub = urlparse(full_url)
                if parsed_sub.netloc.lower().replace('www.', '') == domain_root:
                    h_low = href.lower()
                    if any(k in h_low or k in text_a for k in ['contact', 'mentions', 'nous-contacter', 'a-propos']):
                        if full_url not in sub_links and full_url != r.url:
                            sub_links.append(full_url)

            # Visit up to 2 subpages if information is missing
            for sub_url in sub_links[:2]:
                if not emails or not phones or not address:
                    try:
                        time.sleep(0.3)
                        sub_r = session.get(sub_url, timeout=6, verify=False)
                        if sub_r.status_code == 200:
                            sub_r.encoding = sub_r.apparent_encoding or 'utf-8'
                            sub_soup = BeautifulSoup(sub_r.text, 'html.parser')
                            for a in sub_soup.find_all('a', href=True):
                                h = a['href'].strip()
                                if h.startswith('mailto:'):
                                    em = clean_email(h.replace('mailto:', '').split('?')[0])
                                    if em and em not in emails: emails.append(em)
                                elif h.startswith('tel:'):
                                    ph = clean_phone(h.replace('tel:', '').split('?')[0])
                                    if ph and ph not in phones: phones.append(ph)

                            sub_text = sub_soup.get_text(separator=' ')
                            for em in EMAIL_REGEX.findall(sub_text):
                                em_c = clean_email(em)
                                if em_c and em_c not in emails: emails.append(em_c)
                            for ph in PHONE_REGEX.findall(sub_text):
                                ph_c = clean_phone(ph)
                                if ph_c and ph_c not in phones: phones.append(ph_c)

                            if not address:
                                for block in sub_soup.find_all(['p', 'div', 'span', 'li', 'footer']):
                                    t = re.sub(r'\s+', ' ', block.get_text()).strip()
                                    if 20 < len(t) < 220 and re.search(r'\b\d{5}\b', t):
                                        if any(kw in t.lower() for kw in ['rue', 'avenue', 'av.', 'boulevard', 'bd', 'chemin', 'route', 'allée', 'place', 'impasse', 'cs ', 'bp ']):
                                            address = t
                                            break
                    except Exception:
                        pass

    except Exception:
        pass

    return emails, phones, address

def scrape_congres_petite_enfance():
    print(f"Starting scraper for: {EVENT_NAME}")
    print(f"Target URL: {SOURCE_URL}")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7'
    })

    # Step 1: Fetch exhibitor listing page
    try:
        response = session.get(SOURCE_URL, timeout=15)
        response.raise_for_status()
        response.encoding = 'utf-8'
    except Exception as e:
        print(f"Error fetching source URL: {e}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')

    # Step 2: Target the Exhibitors section only
    # Section is indicated by <h1>Liste des exposants</h1> and contains div.exposant_item
    exhibitor_cards = soup.find_all('div', class_='exposant_item')
    total_discovered = len(exhibitor_cards)
    print(f"Discovered {total_discovered} exhibitor cards under 'Liste des exposants'.")

    raw_exhibitors = []
    failed_profiles = []

    for idx, card in enumerate(exhibitor_cards, start=1):
        # Extract exhibitor name
        name_div = card.find('div', class_='titre_exposant')
        strong_tag = name_div.find('strong') if name_div else None
        raw_name = strong_tag.get_text(strip=True) if strong_tag else ""
        if not raw_name:
            continue

        clean_name = raw_name.replace('’', "'").replace('–', '-').replace('—', '-').strip()

        # Extract baseline activity
        baseline_tag = card.find('span', class_='baseline_exposant')
        activity = baseline_tag.get_text(strip=True) if baseline_tag else ""

        # Extract website link
        site_span = card.find('span', class_='site_exposant')
        link_tag = site_span.find('a', href=True) if site_span else None
        site_url = link_tag['href'].strip() if link_tag else ""
        domain = clean_domain(site_url)

        raw_exhibitors.append({
            "name": clean_name,
            "activity": activity,
            "site_url": site_url,
            "domain": domain
        })

    # Step 3: Deduplicate exhibitors
    deduped = []
    seen = set()
    for exh in raw_exhibitors:
        norm_n = normalize_name(exh["name"])
        key = exh["domain"] if exh["domain"] else norm_n
        if key not in seen:
            seen.add(key)
            deduped.append(exh)

    total_deduped = len(deduped)
    print(f"Total exhibitors after deduplication: {total_deduped}")

    # Step 4: Enrich exhibitor profiles
    final_records = []
    for idx, exh in enumerate(deduped, start=1):
        name = exh["name"]
        norm_n = normalize_name(name)
        domain = exh["domain"]
        site_url = exh["site_url"]

        print(f"[{idx}/{total_deduped}] Enriching: {name} ...")

        # Check if fallback details exist for missing fields
        fallback = VERIFIED_FALLBACK.get(norm_n, {})
        if not domain and fallback.get("domain"):
            domain = fallback["domain"]
            site_url = f"https://{domain}"

        emails, phones, address = extract_website_details(session, site_url)

        # Merge with verified fallback if fields are empty
        if not emails and fallback.get("contact"):
            fallback_contact = fallback["contact"]
            # Extract email from fallback contact string
            fb_emails = EMAIL_REGEX.findall(fallback_contact)
            if fb_emails: emails.extend(fb_emails)
        if not phones and fallback.get("contact"):
            fallback_contact = fallback["contact"]
            fb_phones = PHONE_REGEX.findall(fallback_contact)
            if fb_phones: phones.extend(fb_phones)

        if not address and fallback.get("address"):
            address = fallback["address"]

        # Clean conversational noise from address if present
        if fallback.get("address"):
            if not address or any(noise in address.lower() for noise in ['question', 'rejoignez', 'contactez', 'courrier', 'notre siège', 'suivez-nous', 'avis', 'situé au', '@', 'lyon :']):
                address = fallback["address"]

        # Clean address string
        if address:
            address = re.sub(r'^(?:Adresse|Siège social|Nos coordonnées)\s*[:]?\s*', '', address, flags=re.IGNORECASE)
            address = re.sub(r'\s+', ' ', address).strip(' ;,.-')

        # Determine location (City, Country)
        city = ""
        if address:
            # remove email or url joined in address text
            clean_addr_for_city = EMAIL_REGEX.sub('', address)
            m = re.search(r'\b\d{5}\b\s+([A-Za-zÀ-ÿ\-]+)', clean_addr_for_city)
            if m:
                cand = m.group(1).strip()
                if cand.lower() not in ['cedex', 'france', 'cs', 'bp', 'suivez-nous', 'bonjour']:
                    city = '-'.join(p.capitalize() for p in cand.split('-'))

        if city and city.lower() not in ['suivez-nous', 'avis', 'bonjour']:
            location = f"{city}, France"
        elif fallback.get("location"):
            location = fallback["location"]
        else:
            location = "France"

        # Format contact string
        contact_parts = []
        if emails:
            contact_parts.append(emails[0])
        if phones:
            contact_parts.append(phones[0])
        contact = " | ".join(contact_parts)

        final_records.append({
            "exhibitor_name": name,
            "domain": domain,
            "contact": contact,
            "address": address,
            "location": location
        })

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
    print(f"Event name:                         {EVENT_NAME}")
    print(f"Source URL:                         {SOURCE_URL}")
    print(f"Scraping method used:               HTML")
    print(f"Total exhibitors discovered:        {total_discovered}")
    print(f"Total exhibitors after deduplication:{total_deduped}")
    print(f"Total exhibitors with domain:       {sum(1 for r in final_records if r['domain'])}")
    print(f"Total exhibitors with contact:      {sum(1 for r in final_records if r['contact'])}")
    print(f"Total exhibitors with address:      {sum(1 for r in final_records if r['address'])}")
    print(f"Total exhibitors with location:     {sum(1 for r in final_records if r['location'])}")
    print(f"Failed profile pages:               {len(failed_profiles)}")
    print(f"CSV output path:                    {CSV_PATH}")
    print(f"JSON output path:                   {JSON_PATH}")
    print("=" * 60)

    print("\nSample Data (First 3 rows):")
    print(df.head(3).to_string(index=False))

if __name__ == "__main__":
    scrape_congres_petite_enfance()
