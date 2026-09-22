import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "PARIS_PHOTO_2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LIST_URL = "https://www.parisphoto.com/fr-fr/exposant/exposants-2026.html"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "google.com", "parisphoto.com",
    "yellowpages.com", "yelp.com",
}
CITY_COUNTRIES = {
    "paris": "France", "lille": "France", "arles": "France", "marseille": "France",
    "séville": "Spain", "madrid": "Spain", "barcelone": "Spain",
    "zurich": "Switzerland", "genève": "Switzerland", "lausanne": "Switzerland",
    "berlin": "Germany", "cologne": "Germany", "francfort": "Germany",
    "londres": "United Kingdom", "bruxelles": "Belgium", "anvers": "Belgium",
    "amsterdam": "Netherlands", "milan": "Italy", "rome": "Italy",
    "new york": "United States", "san francisco": "United States",
    "los angeles": "United States", "toronto": "Canada", "vancouver": "Canada",
    "santa monica": "United States", "montréal": "Canada", "montreal": "Canada",
    "tokyo": "Japan", "osaka": "Japan", "kyoto": "Japan", "séoul": "South Korea",
    "seoul": "South Korea", "varsovie": "Poland", "warsovie": "Poland",
    "timisoara": "Romania", "bucarest": "Romania", "kaunas": "Lithuania",
    "gent": "Belgium", "andorre": "Andorra", "melbourne": "Australia",
    "johannesbourg": "South Africa", "lisbonne": "Portugal", "caracas": "Venezuela",
    "vienne": "Austria", "bologne": "Italy", "miami": "United States",
    "nouvelle-angleterre": "United States", "taipei": "Taiwan", "budapest": "Hungary",
    "london": "United Kingdom", "ankara": "Turkey", "palma": "Spain",
    "beyrouth": "Lebanon", "mexico": "Mexico", "stuttgart": "Germany",
    "cambridge": "United Kingdom", "malaga": "Spain", "atlanta": "United States",
    "buenos aires": "Argentina", "heidelberg": "Germany", "tartu": "Estonia",
    "gand": "Belgium", "bogota": "Colombia", "são paulo": "Brazil",
    "sao paulo": "Brazil", "pékin": "China", "pekin": "China",
    "casablanca": "Morocco", "copenhague": "Denmark", "oslo": "Norway",
    "dubai": "United Arab Emirates", "a coruña": "Spain", "istanbul": "Turkey",
    "thornbury": "United Kingdom", "glasgow": "United Kingdom", "sante fe": "United States",
    "makati": "Philippines", "le cap": "South Africa", "leipzig": "Germany",
    "wrocław": "Poland", "wroclaw": "Poland", "bressia": "Italy",
    "brescia": "Italy", "naples": "Italy", "treviso": "Italy", "baden": "Switzerland",
    "grosrouve": "France", "oakland": "United States", "breda": "Netherlands",
    "le caire": "Egypt", "cairo": "Egypt", "hsinchu": "Taiwan",
    "athènes": "Greece", "athens": "Greece", "turin": "Italy",
}
TLD_COUNTRIES = {
    ".fr": "France", ".ch": "Switzerland", ".de": "Germany", ".be": "Belgium",
    ".uk": "United Kingdom", ".co.uk": "United Kingdom", ".it": "Italy",
    ".es": "Spain", ".nl": "Netherlands", ".ca": "Canada", ".us": "United States",
    ".jp": "Japan", ".pl": "Poland", ".lt": "Lithuania", ".ro": "Romania",
}


def clean(value):
    value = html.unescape(str(value or "")).replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def root_domain(value):
    if not value:
        return ""
    value = clean(value)
    if value.lower().startswith(("mailto:", "tel:")) or "@" in value:
        return ""
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    host = (urlparse(value).hostname or "").lower().removeprefix("www.")
    if not host or any(host == item or host.endswith("." + item) for item in BLOCKED):
        return ""
    return host


def email_from_text(text):
    match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text or "")
    return match.group(0).lower() if match else ""


def phone_from_text(text):
    for value in re.findall(r"(?<!\w)(?:\+|00)?\d[\d\s()./-]{7,}\d", text or ""):
        value = clean(value)
        digits = re.sub(r"\D", "", value)
        if re.search(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b", value):
            continue
        if re.search(r"\b(?:19|20)\d{2}\b", value) or "978-" in value:
            continue
        if 8 <= len(digits) <= 16:
            return value
    return ""


def country_for(city, domain):
    city_key = city.lower().strip()
    country_text = {
        "france": "France", "the netherlands": "Netherlands", "netherlands": "Netherlands",
        "portugal": "Portugal", "germany": "Germany", "switzerland": "Switzerland",
        "united kingdom": "United Kingdom", "belgium": "Belgium", "italy": "Italy",
        "spain": "Spain", "united states": "United States", "canada": "Canada",
        "south africa": "South Africa", "australia": "Australia",
    }
    for key, country in country_text.items():
        if key in city_key:
            return country
    for key, country in CITY_COUNTRIES.items():
        if key in city_key:
            return country
    for suffix, country in TLD_COUNTRIES.items():
        if domain.endswith(suffix):
            return country
    return ""


def city_from_location(location):
    parts = [clean(part) for part in location.split(",") if clean(part)]
    if len(parts) >= 2:
        candidate = parts[-2] if parts[-1].lower() in {
            "france", "the netherlands", "netherlands", "germany", "switzerland",
            "united kingdom", "belgium", "italy", "spain", "united states",
        } else parts[-1]
        return clean(candidate)
    return ""


def parse_name_city(text):
    text = clean(text).rstrip("*").strip()
    if "," in text:
        name, city = text.rsplit(",", 1)
        return clean(name), clean(city)
    return text, ""


def parse_listing():
    response = requests.get(LIST_URL, headers=HEADERS, timeout=60)
    response.encoding = response.apparent_encoding or "utf-8"
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    records = {}
    for table in soup.find_all("table"):
        section_node = table.find_previous(["h1", "h2", "h3"])
        section = clean(section_node.get_text(" ", strip=True)) if section_node else ""
        for link in table.select("a[href]"):
            label = clean(link.get_text(" ", strip=True))
            href = link.get("href", "")
            if not label or not href or href.startswith("#"):
                continue
            name, city = parse_name_city(label)
            domain = root_domain(href)
            if name == "Grégory Leroy-Nuevo Impulso":
                city = "Madrid"
            elif name == "AUTOMATA":
                city = "Berlin"
            elif name == "A" and domain == "homecoming.gallery":
                continue
            elif name == "Homecoming" and not city:
                city = "Amsterdam"
            if not name:
                continue
            key = (name.casefold(), domain)
            if key not in records:
                records[key] = {
                    "exhibitor_name": name,
                    "domain": domain,
                    "contact_number": "",
                    "mail": "",
                    "location": city,
                    "country": country_for(city, domain),
                    "booth_no": "",
                    "desc": section,
                    "linkedin_url": "",
                    "city": city,
                    "profile_url": href,
                    "sections": section,
                }
            elif section and section not in records[key]["sections"]:
                records[key]["sections"] += f"; {section}"
                records[key]["desc"] = records[key]["sections"]
    return list(records.values())


def parse_json_ld(soup):
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        objects = data if isinstance(data, list) else [data]
        for item in objects:
            if not isinstance(item, dict):
                continue
            address = item.get("address", {})
            if isinstance(address, dict):
                location = ", ".join(
                    clean(address.get(key, "")) for key in
                    ("streetAddress", "postalCode", "addressLocality", "addressRegion", "addressCountry")
                    if clean(address.get(key, ""))
                )
            else:
                location = clean(address)
            yield location, clean(item.get("telephone", "")), clean(item.get("email", ""))


def enrich_website(record):
    if not record["domain"]:
        return record
    try:
        response = requests.get("https://" + record["domain"], headers=HEADERS, timeout=25)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for location, phone, email in parse_json_ld(soup):
            record["location"] = record["location"] or location
            record["contact_number"] = record["contact_number"] or phone
            record["mail"] = record["mail"] or email
        text = soup.get_text(" ", strip=True)
        record["mail"] = record["mail"] or email_from_text(text)
        record["contact_number"] = record["contact_number"] or phone_from_text(text)
        description = soup.select_one('meta[name="description"], meta[property="og:description"]')
        if description and description.get("content"):
            record["desc"] = clean(description["content"])
        linkedin = soup.select_one('a[href*="linkedin.com/"]')
        if linkedin:
            record["linkedin_url"] = linkedin.get("href", "")
    except requests.RequestException:
        pass
    return record


def serper_key():
    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"\'')
    return ""


def enrich_domain(record):
    if record["domain"] and record["country"] and record["location"]:
        return record
    key = serper_key()
    if not key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website Paris Photo 2026'},
            timeout=30,
        )
        response.raise_for_status()
        graph = response.json().get("knowledgeGraph", {})
        record["domain"] = root_domain(graph.get("website", ""))
        record["location"] = clean(graph.get("address", "")) or record["location"]
        record["contact_number"] = clean(graph.get("phone", "")) or record["contact_number"]
        record["country"] = record["country"] or country_for(record["location"], record["domain"])
    except requests.RequestException:
        pass
    return record


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = parse_listing()
    print(f"Found {len(records)} unique official 2026 exhibitors")
    with ThreadPoolExecutor(max_workers=20) as pool:
        records = list(pool.map(enrich_website, records))
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(enrich_domain, records))
    for record in records:
        record.pop("sections", None)
        if not record["city"] and record["location"]:
            record["city"] = city_from_location(record["location"])
        record["country"] = record["country"] or country_for(record["city"], record["domain"])
    records.sort(key=lambda item: item["exhibitor_name"].lower())
    fields = [
        "exhibitor_name", "domain", "contact_number", "mail", "location",
        "country", "booth_no", "desc", "linkedin_url", "city", "profile_url",
    ]
    base = OUT / f"{EVENT}_exhibitors"
    with base.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    base.with_suffix(".json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Scraped {len(records)} exhibitors")
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
