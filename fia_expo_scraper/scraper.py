#!/usr/bin/env python3
"""
Scraper module for FIA Futures & Options Expo 2026.
Extracts all exhibitors listed under the 'Exhibitor' category on the FIA Expo page.
"""

import os
import re
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

FIA_EXPO_URL = "https://www.fia.org/fia/events/futures-options-expo?utm_source=FIAWeb&utm_medium=Top"

HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
    "cache-control": "max-age=0",
    "referer": "https://www.fia.org/",
    "sec-ch-ua": '"Google Chrome";v="153", "Not_A Brand";v="8", "Chromium";v="153"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
}

# Known brand name normalizations for clarity
KNOWN_BRAND_NAMES = {
    "abaxx": "Abaxx Exchange",
    "algo-logic": "Algo-Logic Systems",
    "b3": "B3 (Brasil, Bolsa, Balcão)",
    "baha": "QuantHouse",
    "barchart": "Barchart",
    "borsa istanbul": "Borsa Istanbul",
    "cqg": "CQG / Broadridge",
    "bse": "BSE India (Bombay Stock Exchange)",
    "btg": "BTG Pactual",
    "cboe": "Cboe Global Markets",
    "clear street": "Clear Street",
    "cme group": "CME Group",
    "copp clark": "Copp Clark",
    "cumulus": "Cumulus9",
    "d4 solutions": "D4 Solutions",
    "dexexperts": "Devexperts",
    "eurex": "Eurex",
    "exa": "Exa Infrastructure",
    "edi": "Exchange Data International",
    "fma": "FIA Markets Academy",
    "fis": "FIS Global",
    "hkex": "Hong Kong Exchanges and Clearing (HKEX)",
    "hautai": "Huatai Financial Holdings",
    "illinois tech": "Illinois Tech (Stuart School of Business)",
    "ice": "Intercontinental Exchange (ICE)",
    "itrs": "ITRS Group",
    "krx": "Korea Exchange (KRX)",
    "magmio": "Magmio",
    "mckay": "McKay Brothers",
    "mexder": "MexDer (Mercado Mexicano de Derivados)",
    "miax": "MIAX Exchange Group",
    "nanhua": "Nanhua USA",
    "nfa": "National Futures Association (NFA)",
    "jpx": "Japan Exchange Group (JPX)",
    "osttra": "OSTTRA",
    "pico": "Pico Quantitative Trading",
    "quod": "Quod Financial",
    "ragnerock": "Ragnarok Systems",
    "scila": "Scila",
    "shengli": "Shengli Technologies",
    "solidus": "Solidus Labs",
    "stellar": "Stellar Trading Systems",
    "take profit": "Take Profit Trader",
    "tmx": "Montréal Exchange (TMX Group)",
    "tt": "Trading Technologies (TT)",
    "tsimagine": "TS Imagine",
    "webull": "Webull",
    "zayo": "Zayo Group",
    "zhengzou": "Zhengzhou Commodity Exchange (CZCE)"
}


def clean_domain(url_str: str) -> str:
    """Extracts a clean, lowercase domain without protocol, www, or trailing slashes."""
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


def clean_company_name(alt_text: str, img_src: str) -> str:
    """Derives a proper company name from alt text, image file name, or known mappings."""
    base_name = alt_text.strip()
    if base_name.lower().endswith(" logo"):
        base_name = base_name[:-5].strip()

    lookup_key = base_name.lower().strip()
    if lookup_key in KNOWN_BRAND_NAMES:
        return KNOWN_BRAND_NAMES[lookup_key]

    # Fallback to image filename if alt is obscure
    if not base_name and img_src:
        filename = os.path.basename(img_src).split("?")[0].split(".")[0]
        clean_fn = re.sub(r"_\d+x\d+.*", "", filename).replace("_", " ")
        return clean_fn.title()

    return base_name.title()


def scrape_fia_exhibitors():
    """
    Downloads the FIA Expo page and extracts all exhibitors strictly under
    the 'Exhibitor' category.
    """
    print(f"Fetching FIA Expo page: {FIA_EXPO_URL}...")
    response = requests.get(FIA_EXPO_URL, headers=HEADERS, timeout=20)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    grid = soup.find("div", class_=re.compile(r"content-grid"))
    if not grid:
        raise ValueError("Could not locate .content-grid in FIA Expo page")

    rows = grid.find_all("div", class_=re.compile(r"paragraph-grid-row"))
    exhibitors = []

    for r in rows:
        h = r.find(["h2", "h3", "h4"])
        cat = h.get_text(strip=True) if h else ""
        if "exhibitor" not in cat.lower():
            continue

        items = r.find_all("div", class_=re.compile(r"content-grid-item"))
        for it in items:
            a = it.find("a")
            img = it.find("img")

            href = a.get("href", "").strip() if a else ""
            alt = img.get("alt", "").strip() if img else ""
            src = img.get("src", "").strip() if img else ""

            # Handle Broadridge / CQG specific pairing
            if "cqg" in alt.lower() and "broadridge.com" in href:
                name = "CQG / Broadridge"
            else:
                name = clean_company_name(alt, src)

            domain = clean_domain(href)

            exhibitors.append({
                "exhibitor_name": name,
                "url": href,
                "domain": domain,
                "raw_alt": alt,
                "img_src": src
            })

    print(f"Successfully parsed {len(exhibitors)} exhibitors under 'Exhibitor' section.")
    return exhibitors


if __name__ == "__main__":
    exhibitors = scrape_fia_exhibitors()
    for idx, e in enumerate(exhibitors, 1):
        print(f"{idx:2d}. {e['exhibitor_name']} | Domain: {e['domain']} | URL: {e['url']}")
