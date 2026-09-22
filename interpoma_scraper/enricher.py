import logging
import re
import urllib.parse
from typing import List, Dict, Any, Optional
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("interpoma_scraper.enricher")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Regex to detect Italian / European physical addresses
# Examples:
# Via Fiume, 11 Firenze (Firenze) - IT
# Via Farfusola 6, 37050 Bonavicina di S. Pietro di Morubio (VR)
# Max Valier Str. 7/a, LANA (Bolzano) - IT
# Gewerbezone 4, 39010 Lana BZ
ADDRESS_REGEXES = [
    re.compile(
        r'(?:(?:Via|Viale|Corso|Piazza|Piazzale|Strada|Localit[àa]|Loc\.|Frazione|Fraz\.|Gewerbezone|Handwerkerzone|Strasse|Stra[ßs]e|Str\.)\s+[^,\n\r<]{3,80},\s*(?:\d{5}\s+)?[A-Za-z\s\.\'-]+(?:\s*\([A-Z]{2}\))?(?:\s*-\s*[A-Z]{2})?)',
        re.I
    ),
    re.compile(
        r'(?:(?:Via|Viale|Corso|Piazza|Strada|Strasse|Stra[ßs]e)\s+[^,\n\r<]{3,60}\s+\d+[a-zA-Z]?(?:,\s*|\s+)\d{5}\s+[^,\n\r<]{3,50})',
        re.I
    ),
    re.compile(
        r'(\d{5}\s+[A-Za-z\s\'-]+(?:\s*\([A-Z]{2}\))?(?:,\s*(?:Italy|Italia|Germany|Deutschland|Austria|Österreich))?)',
        re.I
    ),
]

# Well-known brands and domains mapping if detail page had empty fields
KNOWN_BRAND_DOMAINS = {
    "JOHN DEERE": "https://www.deere.com",
    "NEW HOLLAND": "https://agriculture.newholland.com",
    "FENDT": "https://www.fendt.com",
    "STEYR": "https://www.steyr-traktoren.com",
    "ANTONIO CARRARO": "https://www.antoniocarraro.it",
    "ANTONIO CARRARO SPA": "https://www.antoniocarraro.it",
    "SDF SPA": "https://www.sdfgroup.com",
    "SYNGENTA ITALIA SPA": "https://www.syngenta.it",
    "BLUEBERRY ITALIA": "https://www.gruber-genetti.it",
    "SCHNIGA GMBH": "https://www.schniga.com",
    "CBC EUROPE": "https://www.cbceurope.it",
    "CARTONPACK GROUP": "https://www.cartonpack.com",
    "Agriges Srl": "https://www.agriges.com",
    "AGRINOVA II SRL": "https://www.agrinova2.it",
    "Evelina": "https://www.evelina-apple.com",
    "Goldoni Keestrack srl": "https://www.goldoni.com",
    "Ilmer Maschinenbau GMBH": "https://www.ilmer.info",
    "Plantvoice": "https://www.plantvoice.it",
    "SALVI VIVAI": "https://www.salvivivai.it",
    "SOLARELLI": "https://www.solarelli.it",
    "Soleon GmbH": "https://www.soleon.it",
    "MAR-TECH SRL": "https://www.mar-tech.it",
    "TECNOFRUIT SRL": "https://www.tecnofruit.it",
    "NBLOSI": "https://www.nblosi.com",
    "CESARI SRL": "https://www.cesarisrl.it",
    "FILAR": "https://www.mazzolenitrafilerie.it",
    "FRUIARA": "https://www.vogproducts.it",
    "INDOFIL AGROWIN": "https://www.indofilcc.com",
    "Steiner Sprayers": "https://www.meland.it",
    "Gruppo Selini": "https://www.cemiat.it",
    "Blueberry Europe": "https://www.gruber-genetti.it",
    "Baumschule Werth Karl": "https://www.feno.it",
    "Baumschule Werth Lukas": "https://www.feno.it",
    "Baumschule Curti Ernst": "https://www.feno.it",
    "Baumschule Oberhofer B.": "https://www.feno.it",
    "Paul Rautscher": "https://www.feno.it",
    "BCS SANY": "https://www.tiefenthaler.it",
    "LOCHMANN, BERTI, ARRIZZA, KUHN, CAMPAGNOLA, MEISTER": "https://www.tiefenthaler.it",
    "GRIPPLE": "https://www.gripple.com",
    "KNUPPEN HERBERT NEUE OBSTSORTEN UND BERATUNG": "https://www.obstbau-beratung.de",
    "RAYMO": "https://raymoelectric.com",
    "STAR EXPORT": "https://www.star-export.com",
    "XAG": "https://www.xa.com",
    "AGROFROST": "https://www.agrofrost.eu",
    "ANGLOAMERICAN": "https://www.anglo-american.com",
    "Atech Innovations": "https://www.atech-innovations.com",
    "Butzbach GmbH Industrietore": "https://www.butzbach.com",
    "BOVI": "https://www.bovi.com",
    "DAYMSA": "https://www.daymsa.com",
    "EFAFLEX Tor- und Sicherheitssysteme GmbH & Co. KG": "https://www.efaflex.com",
    "FAIRPLANT": "https://www.fairplant.nl",
    "Fresh Forward Breeding BV.": "https://www.fresh-forward.nl",
    "JISA ADVANCED AGRO": "https://www.jisaagro.com",
    "KUBOTA EUROPE SAS": "https://www.kubota-eu.com",
    "MAF AGROBOTIC": "https://www.maf-roda.com",
    "Massey Ferguson": "https://www.masseyferguson.com",
    "Massey Fergusson": "https://www.masseyferguson.com",
    "Munckhof": "https://www.munckhof.org",
    "OvinAlp Haute Fertilisation": "https://www.ovinalp.fr",
    "Optiflux NV": "https://www.optiflux.world",
    "Okanagan Specialty Fruits": "https://osfruits.com",
    "NEWTEC A/S": "https://www.newtec.com",
    "Rink Spezialmaschinen": "https://www.mueller-mietpark.de",
    "Van Wamel Perfect": "https://www.vanwamel.nl",
    "VOEN Vöhringer GmbH & Co. KG": "https://www.voen.de",
}

# Known headquarters addresses for international brands
KNOWN_HEADQUARTERS = {
    "AGROFROST": "Beveren-Kalsijde 5B, 8647 Diksmuide, Belgium",
    "ANGLOAMERICAN": "Via Cremona 27, 46100 Mantova (MN) - IT",
    "Atech Innovations": "Gladbeck, North Rhine-Westphalia, Germany",
    "Butzbach GmbH Industrietore": "Weiherstraße 16, 89257 Illertissen, Germany",
    "BOVI": "Partida La Plana, s/n, 25180 Alcarràs, Lleida, Spain",
    "DAYMSA": "C/ Juan Bautista Labaña 4-5, 50007 Zaragoza, Spain",
    "EFAFLEX Tor- und Sicherheitssysteme GmbH & Co. KG": "Fliederstraße 14, 84079 Bruckberg, Germany",
    "FAIRPLANT": "Rietweg 15, 8311 PA Espel, Netherlands",
    "Fresh Forward Breeding BV.": "Wielseweg 38a, 4032 NX Eck en Wiel, Netherlands",
    "GRIPPLE": "The Old West Gun Works, Savile St E, Sheffield S4 7UQ, United Kingdom",
    "JISA ADVANCED AGRO": "Ctra. Albalat - Riola, km 1, 46687 Albalat de la Ribera, Valencia, Spain",
    "KUBOTA EUROPE SAS": "19-25 Rue Jules Vercruysse, 95101 Argenteuil, France",
    "MAF AGROBOTIC": "Impasse d'Athènes, 82000 Montauban, France",
    "Massey Ferguson": "Avenue Blaise Pascal, 60000 Beauvais, France",
    "Massey Fergusson": "Avenue Blaise Pascal, 60000 Beauvais, France",
    "Munckhof": "Handelsstraat 12, 5961 PV Horst, Netherlands",
    "OvinAlp Haute Fertilisation": "Le Plan d'Eau, 05300 Ribiers, France",
    "Optiflux NV": "Ambachtenlaan 21D, 3001 Leuven, Belgium",
    "Okanagan Specialty Fruits": "Summerland, BC V0H 1Z0, Canada",
    "NEWTEC A/S": "Staermosegaardsvej 18, 5230 Odense M, Denmark",
    "RAYMO": "Lubno 34, 739 11 Frydlant nad Ostravici, Czech Republic",
    "Rink Spezialmaschinen": "Eisenbahnstraße 17, 88279 Amtzell, Germany",
    "Van Wamel Perfect": "Energieweg 1, 6658 AE Beneden-Leeuwen, Netherlands",
    "VOEN Vöhringer GmbH & Co. KG": "Schlossstr. 31, 88214 Ravensburg, Germany",
    "XAG": "No. 115, Gaopu Road, Tianhe District, Guangzhou, China",
}

class ExhibitorEnricher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def extract_address_from_text(self, text: str) -> str:
        """Extracts standard physical address patterns from HTML text or footers."""
        for rx in ADDRESS_REGEXES:
            m = rx.search(text)
            if m:
                found = m.group(0).strip()
                # Clean up excess whitespace or trailing punctuation
                found = re.sub(r"\s+", " ", found)
                if len(found) > 10 and not any(bad in found.lower() for bad in ["javascript", "cookie", "copyright", "rights"]):
                    return found
        return ""

    def extract_contacts_from_site(self, website_url: str) -> Dict[str, str]:
        """
        Visits the company website and scans homepage + /contact /contatti for:
        address, phone, email.
        """
        info = {"address": "", "number": "", "mail": ""}
        if not website_url:
            return info

        if not website_url.startswith("http://") and not website_url.startswith("https://"):
            website_url = "https://" + website_url

        try:
            r = self.session.get(website_url, timeout=10, allow_redirects=True)
            if r.status_code == 200:
                s = BeautifulSoup(r.text, "html.parser")
                footer = s.find(["footer", "div", "section"], class_=re.compile(r"footer|bottom|contact", re.I))
                footer_text = footer.get_text(" ", strip=True) if footer else s.get_text(" ", strip=True)

                # 1. Address
                addr = self.extract_address_from_text(footer_text)
                if addr:
                    info["address"] = addr

                # 2. Email
                emails = set(re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', r.text))
                valid_emails = [
                    e for e in emails 
                    if not any(x in e.lower() for x in [".png", ".jpg", ".webp", "sentry", "wixpress", "example", "schema", "domain"])
                ]
                if valid_emails:
                    # Prefer info@, contact@, sales@
                    best_mail = next((e for e in valid_emails if any(p in e.lower() for p in ["info@", "contact@", "commerciale@", "sales@"])), valid_emails[0])
                    info["mail"] = best_mail

                # 3. Phone
                phones = re.findall(r'(?:\+39|\+49|\+43|\+33|\+34|\+41|\+32)?[\s.-]?(?:0\d{1,4}|\d{2,4})[\s.-]?\d{4,8}', footer_text)
                clean_phones = [p.strip() for p in phones if len(re.sub(r'\D', '', p)) >= 8]
                if clean_phones:
                    info["number"] = clean_phones[0]

        except Exception as e:
            logger.debug(f"Site extraction error for {website_url}: {e}")

        return info

    def enrich_records(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Executes multi-tier enrichment across all records.
        """
        logger.info(f"Starting enrichment process across {len(records)} records...")

        # Build lookup table by route, id, and slug
        parent_map: Dict[str, Dict[str, Any]] = {}
        for r in records:
            slug = r["detail_url"].rstrip("/").split("/")[-1]
            parent_map[slug] = r
            if r.get("id_odoo"):
                parent_map[str(r["id_odoo"])] = r
            if r.get("exhibitor_name"):
                parent_map[r["exhibitor_name"].strip().lower()] = r

        enriched_count = 0
        for r in records:
            source = "detail_page"
            ex_name = r["exhibitor_name"].strip()

            # Tier 1: Known Brand Registry Fallback for website
            if not r["domain"] and ex_name in KNOWN_BRAND_DOMAINS:
                brand_url = KNOWN_BRAND_DOMAINS[ex_name]
                r["website_url"] = brand_url
                netloc = urllib.parse.urlparse(brand_url).netloc.lower()
                r["domain"] = netloc.replace("www.", "")
                source = "brand_directory"

            # Tier 1.5: Known headquarters addresses for international brands
            if (not r["address"] or len(r["address"]) < 10) and ex_name in KNOWN_HEADQUARTERS:
                r["address"] = KNOWN_HEADQUARTERS[ex_name]
                if source == "detail_page":
                    source = "headquarters_directory"

            # Tier 2: Parent Exhibitor Linkage for Co-exhibitors / Brands
            p_slug = r.get("parent_slug")
            p_name = r.get("parent_name")
            parent = parent_map.get(p_slug) or (parent_map.get(p_name.strip().lower()) if p_name else None)

            if parent:
                # If current exhibitor is missing address or contact, inherit from host exhibitor stand
                if not r["address"] and parent.get("address"):
                    r["address"] = f"{parent['address']} (c/o {parent['exhibitor_name']})"
                    source = "parent_exhibitor"
                if not r["fair_stand"] and parent.get("fair_stand"):
                    r["fair_stand"] = parent["fair_stand"]
                if not r["fair_hall"] and parent.get("fair_hall"):
                    r["fair_hall"] = parent["fair_hall"]
                if not r["number"] and parent.get("number"):
                    r["number"] = parent["number"]
                if not r["mail"] and parent.get("mail"):
                    r["mail"] = parent["mail"]

            # Tier 3: Deduce domain from corporate email if still missing
            if not r["domain"] and r.get("mail"):
                mail_parts = re.findall(r'@([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', r["mail"])
                for mp in mail_parts:
                    mp_clean = mp.lower().strip()
                    # Filter out generic email hosts
                    if not any(gen in mp_clean for gen in ["gmail", "orange", "live.", "hotmail", "yahoo", "outlook", "pec.it"]):
                        r["domain"] = mp_clean
                        if not r["website_url"]:
                            r["website_url"] = f"https://{mp_clean}"
                        if source == "detail_page":
                            source = "email_domain"
                        break

            # Tier 4: Website contact scraping if address or contact is still missing
            if r.get("website_url") and (not r.get("address") or not r.get("number") or not r.get("mail")):
                site_info = self.extract_contacts_from_site(r["website_url"])
                if site_info.get("address") and not r.get("address"):
                    r["address"] = site_info["address"]
                    source = "website_footer"
                if site_info.get("number") and not r.get("number"):
                    r["number"] = site_info["number"]
                if site_info.get("mail") and not r.get("mail"):
                    r["mail"] = site_info["mail"]

            # Set enrichment source attribute
            r["enrichment_source"] = source
            if source != "detail_page":
                enriched_count += 1

        logger.info(f"Enrichment completed. Enriched {enriched_count} records with supplementary data.")
        return records
