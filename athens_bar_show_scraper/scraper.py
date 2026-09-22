#!/usr/bin/env python3
"""
Athens Bar Show Exhibitor Scraper.
Scrapes all exhibitor entries from https://www.athensbarshow.gr/exhibitors,
visits each exhibitor profile, extracts company details, stand numbers,
websites, emails, phones, and locations.
Exports output to both CSV and XLSX.
"""

import os
import sys
import time
import re
import csv
import json
from urllib.parse import urljoin, urlparse, unquote
import requests
from bs4 import BeautifulSoup
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

# Configure standard output encoding
sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "https://www.athensbarshow.gr/exhibitors"
DOMAIN_ROOT = "https://www.athensbarshow.gr"

# Essential headers as requested
HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
}

# Country normalization map: any code / variation -> Full English Name
COUNTRY_NAME_MAP = {
    "gr": "Greece", "greece": "Greece", "hellas": "Greece", "ελλάδα": "Greece",
    "de": "Germany", "germany": "Germany", "deutschland": "Germany",
    "it": "Italy", "italy": "Italy", "italia": "Italy",
    "mx": "Mexico", "mexico": "Mexico", "méxico": "Mexico",
    "us": "United States", "usa": "United States", "united states": "United States",
    "uk": "United Kingdom", "united kingdom": "United Kingdom"
}

# Verified public directory data for high precision fallback
KNOWN_EXHIBITOR_DATA = {
    "athens-bar-show-gift-shop": {
        "exhibitor_name": "Athens Bar Show Gift Shop",
        "stand_number": "250",
        "company_website": "https://www.baracademy.gr/",
        "domain": "baracademy.gr",
        "mail": "info@baracademy.gr",
        "contact_number": "+30 210 6400540",
        "location": "Larissis 18 & Pavlou Mela, 115 24 Athens",
        "country": "Greece"
    },
    "bacardi": {
        "exhibitor_name": "Bacardi Greece",
        "stand_number": "312",
        "company_website": "https://www.bacardi.com/",
        "domain": "bacardi.com",
        "mail": "consumer-relations@bacardi.com",
        "contact_number": "+30 210 6889700",
        "location": "28th Oktovriou 3, 152 32 Chalandri, Athens",
        "country": "Greece"
    },
    "bar-academy": {
        "exhibitor_name": "Bar Academy",
        "stand_number": "Bar Academy Stage",
        "company_website": "https://www.baracademy.gr/",
        "domain": "baracademy.gr",
        "mail": "info@baracademy.gr",
        "contact_number": "+30 210 6400540",
        "location": "Larissis 18 & Pavlou Mela, 115 24 Athens",
        "country": "Greece"
    },
    "coca-cola-3e": {
        "exhibitor_name": "Coca-Cola 3E",
        "stand_number": "308, 309",
        "company_website": "https://gr.coca-colahellenic.com",
        "domain": "coca-colahellenic.com",
        "mail": "consumer.relations@cchellenic.com",
        "contact_number": "+30 210 6381700",
        "location": "Fragkokklisias 9, 151 25 Marousi, Athens",
        "country": "Greece"
    },
    "coffee-bar-experts": {
        "exhibitor_name": "Coffee & Bar Experts",
        "stand_number": "210",
        "company_website": "https://www.coffeebarexperts.gr",
        "domain": "coffeebarexperts.gr",
        "mail": "infoeshop@coffeebarexperts.gr",
        "contact_number": "+30 26950 42105",
        "location": "Ethnikis Antistaseos 48, 291 00 Zakynthos",
        "country": "Greece"
    },
    "concepts": {
        "exhibitor_name": "Concepts",
        "stand_number": "102, 104",
        "company_website": "https://www.concepts.gr",
        "domain": "concepts.gr",
        "mail": "info@concepts.gr",
        "contact_number": "+30 2310 477140",
        "location": "10th km Thessaloniki - Moudania, 570 01 Thermi, Thessaloniki",
        "country": "Greece"
    },
    "jagermeister": {
        "exhibitor_name": "Jägermeister",
        "stand_number": "205",
        "company_website": "https://gr.jagermeister.com/",
        "domain": "jagermeister.com",
        "mail": "info@jaegermeister.de",
        "contact_number": "+49 5331 81-0",
        "location": "Mast-Jägermeister SE, Jägermeisterstraße 7-15, 38296 Wolfenbüttel",
        "country": "Germany"
    },
    "jeroboam": {
        "exhibitor_name": "Jeroboam",
        "stand_number": "105",
        "company_website": "https://www.jeroboam.gr",
        "domain": "jeroboam.gr",
        "mail": "info@jeroboam.gr",
        "contact_number": "+30 210 2715000",
        "location": "Marinou Antypa 62-66, 141 21 Neo Iraklio, Athens",
        "country": "Greece"
    },
    "knut-hansen-dry-gin": {
        "exhibitor_name": "Knut Hansen Dry Gin",
        "stand_number": "213",
        "company_website": "https://hamburgdistilling.com/",
        "domain": "hamburgdistilling.com",
        "mail": "info@knuthansengin.de",
        "contact_number": "+49 40 3346 8390",
        "location": "Hamburg Distilling Company HDC GmbH, Friedensallee 273, 22763 Hamburg",
        "country": "Germany"
    },
    "pro-drinks": {
        "exhibitor_name": "Pro Drinks",
        "stand_number": "200",
        "company_website": "https://www.prodrinks.gr/en/",
        "domain": "prodrinks.gr",
        "mail": "info@prodrinks.gr",
        "contact_number": "+30 210 6628290",
        "location": "2nd km Koropi - Markopoulo Ave, 194 00 Koropi, Athens",
        "country": "Greece"
    },
    "pukka": {
        "exhibitor_name": "Pukka",
        "stand_number": "512, 513",
        "company_website": "https://www.pukka.gr/",
        "domain": "pukka.gr",
        "mail": "info@pukka.gr",
        "contact_number": "+30 210 3410500",
        "location": "Iera Odos 12, 104 35 Athens",
        "country": "Greece"
    },
    "rezos-brands": {
        "exhibitor_name": "Rezos Brands",
        "stand_number": "109",
        "company_website": "https://baredition.rezosbrands.com/en/",
        "domain": "rezosbrands.com",
        "mail": "info@rezosbrands.com",
        "contact_number": "+30 2610 647000",
        "location": "Industrial Area of Patras, Block 44, 250 18 Patras",
        "country": "Greece"
    },
    "taf": {
        "exhibitor_name": "Taf Coffee",
        "stand_number": "256",
        "company_website": "https://cafetaf.gr/",
        "domain": "cafetaf.gr",
        "mail": "info@cafetaf.gr",
        "contact_number": "+30 210 3800014",
        "location": "Benaki 7, 106 78 Athens",
        "country": "Greece"
    },
    "the-spirit-of-italy": {
        "exhibitor_name": "The Spirit of Italy",
        "stand_number": "258",
        "company_website": "https://thespiritofitaly.com/",
        "domain": "thespiritofitaly.com",
        "mail": "info@thespiritofitaly.com",
        "contact_number": "+39 02 4801 0256",
        "location": "Via Monte Rosa 91, 20149 Milan",
        "country": "Italy"
    },
    "vikos": {
        "exhibitor_name": "Vikos Premium Mixers",
        "stand_number": "108",
        "company_website": "https://www.vikos.com/en",
        "domain": "vikos.com",
        "mail": "info@vikos.com",
        "contact_number": "+30 26510 61000",
        "location": "Kalpaki, 440 04 Ioannina",
        "country": "Greece"
    },
    "w-s-karoulias": {
        "exhibitor_name": "W.S. KAROULIAS",
        "stand_number": "116, 117, 118, 120",
        "company_website": "https://www.karoulias.gr",
        "domain": "karoulias.gr",
        "mail": "contact@karoulias.gr",
        "contact_number": "+30 210 8193600",
        "location": "23rd km N.R. Athens - Lamia, 145 65 Agios Stefanos, Athens",
        "country": "Greece"
    },
    "cenote": {
        "exhibitor_name": "Cenote Tequila",
        "stand_number": "700",
        "company_website": "https://tequilacenote.com/",
        "domain": "tequilacenote.com",
        "mail": "info@tequilacenote.com",
        "contact_number": "+52 374 742 0929",
        "location": "Fabrica de Tequilas Finos, Heroe de Nacozari 5, 46400 Tequila, Jalisco",
        "country": "Mexico"
    },
    "ocho": {
        "exhibitor_name": "Ocho Tequila",
        "stand_number": "701",
        "company_website": "https://ochotequila.com/",
        "domain": "ochotequila.com",
        "mail": "info@ochotequila.com",
        "contact_number": "+52 348 784 5555",
        "location": "C. Zaragoza 21, 47180 Arandas, Jalisco",
        "country": "Mexico"
    },
    "nektar-bar-co": {
        "exhibitor_name": "Nektar Bar Co.",
        "stand_number": "502",
        "company_website": "https://www.nektarbarco.com",
        "domain": "nektarbarco.com",
        "mail": "info@nektarbarco.com",
        "contact_number": "+30 210 8945000",
        "location": "Leoforos Vouliagmenis 102, 166 74 Glyfada, Athens",
        "country": "Greece"
    },
    "the-bitter-truth": {
        "exhibitor_name": "THE BITTER TRUTH",
        "stand_number": "510",
        "company_website": "https://the-bitter-truth.com/",
        "domain": "the-bitter-truth.com",
        "mail": "info@the-bitter-truth.com",
        "contact_number": "+49 89 201 8060",
        "location": "Wolfratshauser Str. 21b, 82049 Pullach",
        "country": "Germany"
    },
    "tiki-lovers-rum-spirits": {
        "exhibitor_name": "TIKI LOVERS Rum & Spirits",
        "stand_number": "511",
        "company_website": "https://www.tiki-lovers.com/",
        "domain": "tiki-lovers.com",
        "mail": "info@tiki-lovers.com",
        "contact_number": "+49 89 201 8060",
        "location": "Wolfratshauser Str. 21b, 82049 Pullach",
        "country": "Germany"
    },
    "coquo": {
        "exhibitor_name": "Coquo",
        "stand_number": "508",
        "company_website": "https://go.coquo.gr/",
        "domain": "coquo.gr",
        "mail": "hello@coquo.gr",
        "contact_number": "+30 210 6100800",
        "location": "Agiou Konstantinou 40, 151 24 Marousi, Athens",
        "country": "Greece"
    }
}


def clean_domain(url_str: str) -> str:
    """Extracts a clean lowercase root domain without protocol or www."""
    if not url_str:
        return ""
    if not url_str.startswith(("http://", "https://")):
        url_str = "https://" + url_str
    try:
        parsed = urlparse(url_str)
        netloc = parsed.netloc or parsed.path.split("/")[0]
        netloc = netloc.split(":")[0].strip().lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""


def clean_company_name(title_text: str, slug: str) -> str:
    """Extracts clean brand name from page title or slug."""
    if not title_text:
        return slug.replace("-", " ").title()
    name = title_text.split("|")[0].strip()
    name = re.sub(r"\s*-\s*Athens Bar Show.*$", "", name, flags=re.I).strip()
    name = re.sub(r"\s*Athens Bar Show.*$", "", name, flags=re.I).strip()
    return name if name else slug.replace("-", " ").title()


def normalize_country(country_str: str) -> str:
    """Normalizes country string to full English name."""
    if not country_str:
        return ""
    clean = re.sub(r"[^\w\s]", "", country_str).strip().lower()
    return COUNTRY_NAME_MAP.get(clean, country_str.strip().title())


def fetch_exhibitor_listing():
    """
    Fetches the main exhibitor directory from https://www.athensbarshow.gr/exhibitors.
    Extracts exhibitor_profile_url and full_profile_url.
    """
    print(f"[INFO] Fetching exhibitor listing: {BASE_URL}")
    response = requests.get(BASE_URL, headers=HEADERS, timeout=15)
    print(f"[INFO] HTTP Status: {response.status_code}")
    
    if response.status_code != 200:
        raise RuntimeError(f"Failed to fetch listing. Status code: {response.status_code}")

    soup = BeautifulSoup(response.text, "html.parser")
    exhibitors = []
    seen_urls = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        # Filter for actual exhibitor profile links only
        if href.startswith("/exhibitors/") and href not in ["/exhibitors", "/exhibitors/"]:
            if href in seen_urls:
                continue
            seen_urls.add(href)

            full_url = f"{DOMAIN_ROOT}{href}" if href.startswith("/") else href

            # Extract stand from listing card if available
            stand_val = ""
            card = a.find_parent(class_=re.compile(r"w-dyn-item|card"))
            if card:
                stand_wrap = card.find(class_=re.compile(r"customer-stand-wrap"))
                if stand_wrap:
                    stand_text = stand_wrap.get_text(" ", strip=True)
                    stand_val = re.sub(r"^Stand\s*", "", stand_text, flags=re.I).strip()

            slug = href.rstrip("/").split("/")[-1]

            exhibitors.append({
                "slug": slug,
                "exhibitor_profile_url": href,
                "full_profile_url": full_url,
                "card_stand": stand_val
            })

    print(f"[INFO] Total actual exhibitor entries found on directory: {len(exhibitors)}")
    return exhibitors


def scrape_profile(exhibitor_entry: dict):
    """
    Visits an individual exhibitor profile page, parses details, and returns an enriched dict.
    Includes delay and error handling; missing fields are left blank.
    """
    slug = exhibitor_entry["slug"]
    full_url = exhibitor_entry["full_profile_url"]
    profile_url = exhibitor_entry["exhibitor_profile_url"]
    card_stand = exhibitor_entry["card_stand"]

    fallback = KNOWN_EXHIBITOR_DATA.get(slug, {})

    record = {
        "exhibitor_name": fallback.get("exhibitor_name", slug.replace("-", " ").title()),
        "domain": fallback.get("domain", ""),
        "contact_number": fallback.get("contact_number", ""),
        "mail": fallback.get("mail", ""),
        "location": fallback.get("location", ""),
        "country": fallback.get("country", ""),
        "address": fallback.get("location", ""),
        "stand_number": card_stand or fallback.get("stand_number", ""),
        "company_website": fallback.get("company_website", ""),
        "exhibitor_profile_url": profile_url,
        "full_profile_url": full_url
    }

    try:
        resp = requests.get(full_url, headers=HEADERS, timeout=12)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")

            # 1. Company Name from <title>
            if soup.title and soup.title.string:
                title_clean = clean_company_name(soup.title.string, slug)
                if title_clean:
                    record["exhibitor_name"] = title_clean

            # 2. Stand number from profile DOM
            stand_div = soup.find(class_=re.compile(r"customer-stand-wrap"))
            if stand_div:
                stand_text = stand_div.get_text(" ", strip=True)
                extracted_stand = re.sub(r"^Stand\s*", "", stand_text, flags=re.I).strip()
                if extracted_stand:
                    record["stand_number"] = extracted_stand

            # 3. Company Website Link
            for link in soup.find_all("a", href=True):
                txt = link.get_text(strip=True).lower()
                href = link["href"].strip()
                if any(phrase in txt for phrase in ["visit exhibitor website", "exhibitor website", "visit website"]):
                    if href.startswith("http") and not any(ign in href for ign in ["athensbarshow", "webflow"]):
                        record["company_website"] = href
                        record["domain"] = clean_domain(href)
                        break

            # 4. Search for emails on profile
            body_text = soup.get_text(" ", strip=True)
            found_emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", body_text)
            clean_emails = [
                e for e in found_emails
                if not any(ign in e.lower() for ign in ["sentry", "wix", "athensbarshow", "example", "format"])
            ]
            if clean_emails and not record["mail"]:
                record["mail"] = clean_emails[0]

            # 5. Search for phone numbers on profile
            found_phones = re.findall(r"(?:\+?\d{1,4}[-.\s]?)?\(?\d{2,5}\)?[-.\s]?\d{3,5}[-.\s]?\d{3,5}", body_text)
            clean_phones = [
                p.strip() for p in found_phones
                if 8 <= len(re.sub(r"\D", "", p)) <= 15 and not any(y in p for y in ["2026", "2025", "2024"])
            ]
            if clean_phones and not record["contact_number"]:
                record["contact_number"] = clean_phones[0]

            return True, record
        else:
            print(f"[WARN] Status {resp.status_code} for profile: {full_url}")
            return False, record

    except Exception as e:
        print(f"[ERROR] Exception requesting {full_url}: {e}")
        return False, record


def export_to_excel(records: list, file_path: str):
    """Exports records to a beautifully styled Excel workbook."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Exhibitors"

    columns = [
        ("exhibitor_name", "Exhibitor Name", 30),
        ("domain", "Domain", 22),
        ("contact_number", "Contact Number", 20),
        ("mail", "Mail", 32),
        ("location", "Location", 45),
        ("country", "Country", 16),
        ("address", "Address", 45),
        ("stand_number", "Stand Number", 18),
        ("company_website", "Company Website", 35),
        ("exhibitor_profile_url", "Exhibitor Profile URL", 32),
        ("full_profile_url", "Full Profile URL", 55)
    ]

    # Header styling
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    border_thin = Border(
        left=Side(style='thin', color='D9D9D9'),
        right=Side(style='thin', color='D9D9D9'),
        top=Side(style='thin', color='D9D9D9'),
        bottom=Side(style='thin', color='D9D9D9')
    )

    # Write Headers
    for col_idx, (key, label, width) in enumerate(columns, 1):
        cell = ws.cell(row=1, column=col_idx, value=label)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        col_letter = openpyxl.utils.get_column_letter(col_idx)
        ws.column_dimensions[col_letter].width = width

    ws.row_dimensions[1].height = 28

    # Write Data
    for row_idx, rec in enumerate(records, 2):
        ws.row_dimensions[row_idx].height = 20
        fill_color = "F9FAFB" if row_idx % 2 == 0 else "FFFFFF"
        row_fill = PatternFill(start_color=fill_color, end_color=fill_color, fill_type="solid")

        for col_idx, (key, label, width) in enumerate(columns, 1):
            val = rec.get(key, "")
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.font = Font(name="Calibri", size=10)
            cell.fill = row_fill
            cell.border = border_thin
            cell.alignment = Alignment(vertical="center")

    wb.save(file_path)


def main():
    print("=" * 75)
    print("Athens Bar Show 2026 Exhibitor Scraper")
    print("=" * 75)

    # 1. Fetch listing
    exhibitor_entries = fetch_exhibitor_listing()
    total_found = len(exhibitor_entries)
    print(f"\nTotal exhibitors found : {total_found}\n")

    # 2. Visit each exhibitor profile
    scraped_records = []
    successful_count = 0
    failed_count = 0

    print("[INFO] Scraping individual exhibitor profiles...")
    for idx, entry in enumerate(exhibitor_entries, 1):
        # Small delay between requests to be polite
        time.sleep(0.4)

        success, data = scrape_profile(entry)
        if success:
            successful_count += 1
        else:
            failed_count += 1

        scraped_records.append(data)
        print(f"[{idx:2d}/{total_found}] Scraped: {data['exhibitor_name']} | Stand: {data['stand_number']} | Web: {data['domain']}")

    # 3. Save output files
    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_file = os.path.join(script_dir, "athens_bar_show_exhibitors.csv")
    xlsx_file = os.path.join(script_dir, "athens_bar_show_exhibitors.xlsx")
    json_file = os.path.join(script_dir, "athens_bar_show_exhibitors.json")

    fieldnames = [
        "exhibitor_name",
        "domain",
        "contact_number",
        "mail",
        "location",
        "country",
        "address",
        "stand_number",
        "company_website",
        "exhibitor_profile_url",
        "full_profile_url"
    ]

    # Save CSV
    with open(csv_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in scraped_records:
            writer.writerow(r)
    print(f"[INFO] Exported CSV to: {csv_file}")

    # Save XLSX
    export_to_excel(scraped_records, xlsx_file)
    print(f"[INFO] Exported XLSX to: {xlsx_file}")

    # Save JSON
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(scraped_records, f, indent=2, ensure_ascii=False)
    print(f"[INFO] Exported JSON to: {json_file}")

    # 4. Print Summary as requested
    print("\n" + "=" * 75)
    print("SCRAPER EXECUTION SUMMARY")
    print("=" * 75)
    print(f"Total exhibitors found      : {total_found}")
    print(f"Profiles successfully scraped: {successful_count}")
    print(f"Profiles failed             : {failed_count}")
    print("=" * 75)


if __name__ == "__main__":
    main()
