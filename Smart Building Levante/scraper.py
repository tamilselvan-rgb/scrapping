import csv
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT_YEAR = 2026
LISTING_URL = "https://www.smartbuildinglevante.it/it/espositori-2026/"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
OUTPUT.mkdir(exist_ok=True)
SESSION = requests.Session()
SESSION.headers.update(
    {"User-Agent": "Mozilla/5.0 (compatible; Smart-Building-Levante-2026/1.0)"}
)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def root_domain(url):
    host = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def fetch(url):
    try:
        response = SESSION.get(url, timeout=25)
        response.raise_for_status()
        return response.text
    except requests.RequestException:
        return ""


def phone_from(text):
    for value in re.findall(r"(?<!\w)(?:\+?\d[\d\s()./-]{7,}\d)(?!\w)", text or ""):
        value = clean(value)
        digits = re.sub(r"\D", "", value)
        if 8 <= len(digits) <= 16 and not re.fullmatch(r"\d{4}[-/]\d{2}[-/]\d{2}", value):
            return value
    return ""


def email_from(text):
    for value in re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text or ""):
        if not value.lower().endswith("@example.com"):
            return value.lower()
    return ""


def country_name(value):
    names = {
        "IT": "Italy", "ITALY": "Italy", "IT": "Italy",
        "DE": "Germany", "GERMANY": "Germany",
        "FR": "France", "FRANCE": "France",
        "ES": "Spain", "SPAIN": "Spain",
        "CH": "Switzerland", "SWITZERLAND": "Switzerland",
        "SE": "Sweden", "SWEDEN": "Sweden",
        "GB": "United Kingdom", "UK": "United Kingdom",
        "UNITED KINGDOM": "United Kingdom",
        "US": "United States", "USA": "United States",
        "UNITED STATES": "United States",
        "IN": "India", "INDIA": "India",
        "CN": "China", "CHINA": "China",
        "NL": "Netherlands", "NETHERLANDS": "Netherlands",
    }
    value = clean(value)
    return names.get(value.upper(), value if value else "")


def extract_address(soup):
    addresses = []
    for node in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(node.string or node.get_text())
        except (TypeError, ValueError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                if isinstance(item.get("@graph"), list):
                    stack.extend(item["@graph"])
                address = item.get("address")
                if isinstance(address, dict):
                    parts = [
                        address.get("streetAddress"),
                        address.get("postalCode"),
                        address.get("addressLocality"),
                        address.get("addressRegion"),
                        address.get("addressCountry"),
                    ]
                    value = clean(", ".join(clean(x) for x in parts if clean(x)))
                    if value:
                        return value, clean(address.get("addressLocality")), country_name(
                            address.get("addressCountry")
                        )
                elif isinstance(address, str) and clean(address):
                    addresses.append(clean(address))
    return (addresses[0] if addresses else ""), "", ""


def site_details(url, fallback_name):
    html = fetch(url)
    if not html:
        return fallback_name, "", "", "", "", "", "", ""
    soup = BeautifulSoup(html, "html.parser")
    title = clean(soup.title.get_text(" ", strip=True) if soup.title else "")
    site_name = ""
    og_name = soup.find("meta", attrs={"property": "og:site_name"})
    if og_name:
        site_name = clean(og_name.get("content"))
    name = site_name or re.split(r"\s+[|–—-]\s+", title)[0] or fallback_name
    desc_tag = soup.find("meta", attrs={"name": "description"})
    desc = clean(desc_tag.get("content")) if desc_tag else ""
    text = clean(soup.get_text(" ", strip=True))
    mail = email_from(" ".join(a.get("href", "") for a in soup.select('a[href^="mailto:"]')))
    mail = mail or email_from(text)
    phone = phone_from(" ".join(a.get("href", "") for a in soup.select('a[href^="tel:"]')))
    phone = phone or phone_from(text)
    address, city, country = extract_address(soup)
    linkedin = ""
    for link in soup.find_all("a", href=True):
        if "linkedin.com" in link["href"].lower():
            linkedin = link["href"]
            break
    return name, desc, mail, phone, address, city, country, linkedin


def extract_exhibitors(html):
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    exhibitors = []
    for link in soup.find_all("a", href=True):
        image = link.find("img")
        url = link["href"].strip()
        if not image or not url.startswith(("http://", "https://")):
            continue
        if "uploads" not in image.get("src", "") or "smartbuildinglevante.it" in urlparse(url).netloc:
            continue
        if url in seen:
            continue
        seen.add(url)
        filename = Path(urlparse(image.get("src", "")).path).stem
        fallback = clean(re.sub(r"[-_]+", " ", filename))
        exhibitors.append({"website": url, "fallback_name": fallback})
    return exhibitors


def main():
    listing_html = fetch(LISTING_URL)
    exhibitors = extract_exhibitors(listing_html)
    if len(exhibitors) != 76:
        raise RuntimeError(f"Expected 76 official 2026 exhibitors, found {len(exhibitors)}")
    records = []
    for item in exhibitors:
        name, desc, mail, phone, address, city, country, linkedin = site_details(
            item["website"], item["fallback_name"]
        )
        records.append(
            {
                "exhibitor_name": name,
                "domain": root_domain(item["website"]),
                "contact_number": phone,
                "mail": mail,
                "location": address,
                "country": country,
                "booth_no": "",
                "desc": desc,
                "email": mail,
                "phone": phone,
                "address": address,
                "city": city,
                "linkedin_url": linkedin,
                "event_year": EVENT_YEAR,
                "source_profile": LISTING_URL,
                "source_website": item["website"],
            }
        )
        time.sleep(0.1)

    base = "SMART_BUILDING_LEVANTE_2026_exhibitors"
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
