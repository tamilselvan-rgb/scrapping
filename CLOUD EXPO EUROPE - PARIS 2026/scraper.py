import csv
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


EVENT_YEAR = 2026
BASE_URL = "https://www.techshowparis.fr/en/"
LIST_URL = "https://www.techshowparis.fr/en/liste-de-nos-exposants"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
OUTPUT.mkdir(exist_ok=True)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "").replace("\ufffd", "")).strip()


def root_domain(url):
    host = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def fetch(url):
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Cloud-Expo-Paris-2026/1.0)"},
            timeout=35,
        )
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.text
    except requests.RequestException:
        return ""


def email_from(text):
    return next(iter(re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text or "")), "")


def phone_from(text):
    for value in re.findall(r"(?<!\w)(?:\+?\d[\d\s()./-]{7,}\d)(?!\w)", text or ""):
        value = clean(value)
        digits = re.sub(r"\D", "", value)
        if 8 <= len(digits) <= 16 and not re.fullmatch(r"\d{4}[-/]\d{2}[-/]\d{2}", value):
            return value
    return ""


def country_name(value):
    values = {
        "FR": "France", "FRANCE": "France", "BE": "Belgium", "BELGIUM": "Belgium",
        "DE": "Germany", "GERMANY": "Germany", "ES": "Spain", "SPAIN": "Spain",
        "IT": "Italy", "ITALY": "Italy", "GB": "United Kingdom", "UK": "United Kingdom",
        "UNITED KINGDOM": "United Kingdom", "NL": "Netherlands", "NETHERLANDS": "Netherlands",
        "SE": "Sweden", "SWEDEN": "Sweden", "CH": "Switzerland", "SWITZERLAND": "Switzerland",
        "US": "United States", "USA": "United States", "UNITED STATES": "United States",
        "CA": "Canada", "CANADA": "Canada", "CN": "China", "CHINA": "China",
        "IN": "India", "INDIA": "India", "IE": "Ireland", "IRELAND": "Ireland",
        "LU": "Luxembourg", "LUXEMBOURG": "Luxembourg", "AT": "Austria", "AUSTRIA": "Austria",
        "DK": "Denmark", "DENMARK": "Denmark", "FI": "Finland", "FINLAND": "Finland",
        "NO": "Norway", "NORWAY": "Norway", "PL": "Poland", "POLAND": "Poland",
        "PT": "Portugal", "PORTUGAL": "Portugal", "RO": "Romania", "ROMANIA": "Romania",
        "TR": "Turkey", "TURKEY": "Turkey", "AE": "United Arab Emirates",
        "UNITED ARAB EMIRATES": "United Arab Emirates",
    }
    value = clean(value)
    return values.get(value.upper(), value)


def extract_cards(html):
    soup = BeautifulSoup(html, "html.parser")
    cards = {}
    for card in soup.select("li.js-library-item"):
        title = card.select_one("h2")
        link = card.get("data-href") or (
            card.select_one("a.js-librarylink-entry").get("href")
            if card.select_one("a.js-librarylink-entry")
            else ""
        )
        if not title or not link:
            continue
        name = clean(title.get_text(" ", strip=True))
        stand_node = card.select_one('[class*="stand"]')
        stand = clean(stand_node.get_text(" ", strip=True) if stand_node else "")
        stand = re.sub(r"^Stand:\s*", "", stand, flags=re.I)
        profile = urljoin(BASE_URL, link)
        cards[profile] = {"name": name, "booth_no": stand, "profile": profile}
    return list(cards.values())


def parse_address(node):
    if not node:
        return "", "", ""
    lines = [clean(x) for x in node.stripped_strings]
    if lines and lines[0].lower() == "address":
        lines = lines[1:]
    lines = [x for x in lines if x]
    if not lines:
        return "", "", ""
    country = country_name(lines[-1])
    city = lines[1] if len(lines) >= 3 else ""
    return ", ".join(lines), city, country


def profile_data(card):
    html = fetch(card["profile"])
    soup = BeautifulSoup(html, "html.parser")
    title = soup.select_one(".m-exhibitor-entry__item__header__infos__title")
    name = clean(title.get_text(" ", strip=True)) if title else card["name"]
    description_node = soup.select_one(".m-exhibitor-entry__item__body__description")
    desc = clean(description_node.get_text(" ", strip=True) if description_node else "")
    address_node = soup.select_one(".m-exhibitor-entry__item__body__contacts__address")
    location, city, country = parse_address(address_node)
    contacts = soup.select_one(".m-exhibitor-entry__item__body__contacts")
    website = ""
    linkedin = ""
    if contacts:
        for link in contacts.find_all("a", href=True):
            href = link["href"].strip()
            if "linkedin.com" in href.lower():
                linkedin = href
            elif href.startswith(("http://", "https://")) and "techshowparis.fr" not in urlparse(href).netloc:
                website = href
    if not website:
        for link in soup.find_all("a", href=True):
            href = link["href"].strip()
            host = urlparse(href).netloc.lower()
            if (
                href.startswith(("http://", "https://"))
                and host
                and "techshowparis.fr" not in host
                and not any(x in host for x in ("facebook.com", "instagram.com", "youtube.com", "google.com"))
            ):
                website = href
                break
    official_html = fetch(website) if website else ""
    official = BeautifulSoup(official_html, "html.parser")
    official_text = clean(official.get_text(" ", strip=True))
    mail = email_from(" ".join(a.get("href", "") for a in official.select('a[href^="mailto:"]')))
    mail = mail or email_from(official_text)
    phone = phone_from(" ".join(a.get("href", "") for a in official.select('a[href^="tel:"]')))
    phone = phone or phone_from(official_text)
    if not location:
        address_node = official.find("address")
        location, city, country = parse_address(address_node)
    if not linkedin:
        linkedin = next(
            (a["href"] for a in official.find_all("a", href=True) if "linkedin.com" in a["href"].lower()),
            "",
        )
    return {
        "exhibitor_name": name,
        "domain": root_domain(website),
        "contact_number": phone,
        "mail": mail,
        "location": location,
        "country": country,
        "booth_no": card["booth_no"],
        "desc": desc,
        "email": mail,
        "phone": phone,
        "address": location,
        "city": city,
        "linkedin_url": linkedin,
        "event_year": EVENT_YEAR,
        "source_profile": card["profile"],
        "source_website": website,
    }


def main():
    page_one = fetch(LIST_URL)
    soup = BeautifulSoup(page_one, "html.parser")
    pages = [LIST_URL]
    next_link = soup.select_one('a[data-page="2"]')
    if next_link:
        # The site emits unescaped ampersands inside the filter value; the
        # page number alone returns the same official 2026 result set.
        pages.append(f"{LIST_URL}?page=2")
    cards = {}
    for page in pages:
        for card in extract_cards(fetch(page)):
            cards[card["profile"]] = card
    cards = list(cards.values())
    if len(cards) < 300:
        raise RuntimeError(f"Expected the two-page 2026 directory, found {len(cards)} profiles")
    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(profile_data, cards))
    base = "CLOUD_EXPO_EUROPE_PARIS_2026_exhibitors"
    (OUTPUT / f"{base}.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    columns = [
        "exhibitor_name", "domain", "contact_number", "mail", "location",
        "country", "booth_no", "desc", "email", "phone", "address", "city",
        "linkedin_url", "event_year", "source_profile", "source_website",
    ]
    with (OUTPUT / f"{base}.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(records)
    print(f"Exported {len(records)} exhibitors")


if __name__ == "__main__":
    main()
