import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "INTERPAEDAGOGICA_2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LIST_URL = "https://interpaedagogica.at/aussteller/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "google.com", "interpaedagogica.at",
    "yellowpages.com", "yelp.com", "tripadvisor.com",
}
COUNTRY_BY_TLD = {".de": "Germany", ".ch": "Switzerland", ".at": "Austria"}


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


def country_from_text(text, domain=""):
    lower = clean(text).lower()
    countries = {
        "austria": "Austria", "österreich": "Austria",
        "germany": "Germany", "deutschland": "Germany",
        "switzerland": "Switzerland", "schweiz": "Switzerland",
        "italy": "Italy", "italien": "Italy",
    }
    for key, country in countries.items():
        if key in lower:
            return country
    for suffix, country in COUNTRY_BY_TLD.items():
        if domain.endswith(suffix):
            return country
    return "Austria"


def email_from_text(text):
    match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text or "")
    return match.group(0).lower() if match else ""


def phone_from_text(text):
    for value in re.findall(r"(?<!\w)(?:\+|00)?\d[\d\s()./-]{7,}\d", text or ""):
        value = clean(value)
        digits = re.sub(r"\D", "", value)
        if re.fullmatch(r"\d{1,2}[./-]\d{1,2}[./-]20\d{2}", value):
            continue
        if re.search(r"(?<!\d)20\d{2}(?!\d)", value) and not re.search(r"^\s*(?:\+|00)", value):
            continue
        if 8 <= len(digits) <= 16:
            return value
    return ""


def split_address(address, country):
    address = clean(address)
    if not address:
        return "", ""
    city = ""
    parts = [clean(part) for part in re.split(r",|\n", address) if clean(part)]
    if len(parts) > 1:
        city = parts[-1]
    else:
        match = re.search(r"\b\d{4,5}\s+([A-ZÀ-Ý][A-Za-zÀ-ÿ' -]+)$", address)
        if match:
            city = clean(match.group(1))
    return address, city


def parse_listing():
    response = requests.get(LIST_URL, headers=HEADERS, timeout=60)
    response.encoding = response.apparent_encoding or "utf-8"
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    rows = soup.select("#tablepress-1 tbody tr")
    records = []
    for row in rows:
        cells = row.select("td")
        if len(cells) < 7:
            continue
        values = [clean(cell.get_text(" ", strip=True)) for cell in cells]
        name, brands, product_area, website, facebook, instagram, linkedin = values[:7]
        domain = root_domain(website)
        records.append({
            "exhibitor_name": name,
            "domain": domain,
            "contact_number": "",
            "mail": "",
            "location": "",
            "country": country_from_text("", domain),
            "booth_no": "",
            "desc": clean(
                f"Brands and description: {brands}. Product areas: {product_area}"
                if brands and product_area else brands or product_area
            ),
            "linkedin_url": linkedin if "linkedin.com/" in linkedin else "",
            "facebook_url": facebook if "facebook.com/" in facebook else "",
            "instagram_url": instagram if "instagram.com/" in instagram else "",
            "profile_url": LIST_URL,
        })
    return records


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
                text = ", ".join(
                    clean(address.get(key, "")) for key in
                    ("streetAddress", "postalCode", "addressLocality", "addressRegion", "addressCountry")
                    if clean(address.get(key, ""))
                )
            else:
                text = clean(address)
            yield text, clean(item.get("telephone", "")), clean(item.get("email", ""))


def website_contacts(record):
    if not record["domain"]:
        return record
    root = "https://" + record["domain"]
    urls = [root]
    try:
        response = requests.get(root, headers=HEADERS, timeout=25)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for address, phone, email in parse_json_ld(soup):
            record["location"] = record["location"] or address
            record["contact_number"] = record["contact_number"] or phone
            record["mail"] = record["mail"] or email
        text = soup.get_text(" ", strip=True)
        record["mail"] = record["mail"] or email_from_text(text)
        record["contact_number"] = record["contact_number"] or phone_from_text(text)
        for link in soup.select("a[href]"):
            label = clean(link.get_text(" ", strip=True) + " " + link.get("href", "")).lower()
            if any(word in label for word in ("contact", "kontakt", "impressum", "about")):
                candidate = urljoin(root, link.get("href", ""))
                if urlparse(candidate).hostname == urlparse(root).hostname:
                    urls.append(candidate)
        for url in urls[1:3]:
            try:
                page = requests.get(url, headers=HEADERS, timeout=20)
                page.raise_for_status()
                detail = BeautifulSoup(page.text, "html.parser")
                for address, phone, email in parse_json_ld(detail):
                    record["location"] = record["location"] or address
                    record["contact_number"] = record["contact_number"] or phone
                    record["mail"] = record["mail"] or email
                text = detail.get_text(" ", strip=True)
                record["mail"] = record["mail"] or email_from_text(text)
                record["contact_number"] = record["contact_number"] or phone_from_text(text)
                if record["mail"] and record["contact_number"] and record["location"]:
                    break
            except requests.RequestException:
                continue
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


def enrich_missing(record):
    if record["domain"] and record["location"] and record["contact_number"]:
        return record
    key = serper_key()
    if not key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website Interpaedagogica 2026'},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph", {})
        if not record["domain"]:
            record["domain"] = root_domain(graph.get("website", ""))
        if not record["location"]:
            record["location"] = clean(graph.get("address", ""))
        if not record["contact_number"]:
            record["contact_number"] = clean(graph.get("phone", ""))
        if not record["mail"]:
            record["mail"] = clean(graph.get("email", ""))
        record["country"] = country_from_text(record["location"], record["domain"])
    except requests.RequestException:
        pass
    return record


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = parse_listing()
    print(f"Found {len(records)} official 2026 exhibitors")
    with ThreadPoolExecutor(max_workers=16) as pool:
        records = list(pool.map(website_contacts, records))
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(enrich_missing, records))
    for record in records:
        record["location"], record["city"] = split_address(
            record["location"], record["country"]
        )
        record["country"] = country_from_text(record["location"], record["domain"])
    records.sort(key=lambda item: item["exhibitor_name"].lower())
    fields = [
        "exhibitor_name", "domain", "contact_number", "mail", "location",
        "country", "booth_no", "desc", "linkedin_url", "city",
        "facebook_url", "instagram_url", "profile_url",
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
