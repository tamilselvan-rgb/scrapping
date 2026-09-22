import csv
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT_YEAR = 2026
LISTING_URL = "https://btexpo.com/en/exposants/"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
OUTPUT.mkdir(exist_ok=True)
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; BTExpo-2026/1.0)"})


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def root_domain(url):
    host = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def fetch(url):
    try:
        response = SESSION.get(url, timeout=30)
        response.raise_for_status()
        # BTExpo serves UTF-8 pages but some responses are misclassified by
        # charset detection, which corrupts accented exhibitor names.
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
        "BE": "Belgium", "BELGIUM": "Belgium", "FR": "France",
        "FRANCE": "France", "GB": "United Kingdom", "UK": "United Kingdom",
        "UNITED KINGDOM": "United Kingdom", "NL": "Netherlands",
        "NETHERLANDS": "Netherlands", "IT": "Italy", "ITALY": "Italy",
        "HR": "Croatia", "CROATIA": "Croatia", "TN": "Tunisia",
        "TUNISIA": "Tunisia", "US": "United States", "USA": "United States",
        "UNITED STATES": "United States", "CA": "Canada", "CANADA": "Canada",
    }
    value = clean(value)
    return values.get(value.upper(), value)


def jsonld_address(soup):
    for node in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(node.string or node.get_text())
        except (TypeError, ValueError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("@graph"), list):
                stack.extend(item["@graph"])
            address = item.get("address")
            if isinstance(address, dict):
                parts = [
                    address.get("streetAddress"), address.get("postalCode"),
                    address.get("addressLocality"), address.get("addressRegion"),
                    address.get("addressCountry"),
                ]
                location = clean(", ".join(clean(x) for x in parts if clean(x)))
                if location:
                    return location, clean(address.get("addressLocality")), country_name(
                        address.get("addressCountry")
                    )
    return "", "", ""


def serper_domain(name):
    key = ""
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("SERPER_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        return ""
    try:
        response = SESSION.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": f'"{name}" official website {EVENT_YEAR}', "gl": "be", "hl": "en"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return ""
    blocked = ("linkedin.com", "facebook.com", "instagram.com", "twitter.com",
               "x.com", "wikipedia.org", "youtube.com", "yellowpages", "yelp.com")
    kg = data.get("knowledgeGraph") or {}
    if kg.get("website"):
        return kg["website"]
    for result in data.get("organic", []):
        link = result.get("link", "")
        if link and not any(item in urlparse(link).netloc.lower() for item in blocked):
            return link
    return ""


def profile_records(listing_html):
    soup = BeautifulSoup(listing_html, "html.parser")
    records = []
    seen = set()
    started = False
    for link in soup.find_all("a", href=True):
        name = clean(link.get_text(" ", strip=True))
        href = link["href"]
        if name == "Karibuni":
            started = True
        if (
            started
            and href.startswith("https://btexpo.com/en/")
            and "/category/" not in href
            and name
            and href not in seen
        ):
            seen.add(href)
            records.append({"name": name, "profile": href})
    return records


def scrape_profile(item):
    profile_html = fetch(item["profile"])
    soup = BeautifulSoup(profile_html, "html.parser")
    article = soup.find("article")
    article = article or soup
    heading = article.find("h1")
    name = clean(heading.get_text(" ", strip=True)) if heading else item["name"]
    name_overrides = {
        "/en/cfc/": "CFC – Compagnie française de croisières",
        "/en/loffice-national-du-tourisme-tunisien/": "L’Office National du Tourisme Tunisien",
    }
    for path, corrected_name in name_overrides.items():
        if path in item["profile"]:
            name = corrected_name
            break
    external = []
    for link in article.find_all("a", href=True):
        href = link["href"].strip()
        host = urlparse(href).netloc.lower()
        if href.startswith(("http://", "https://")) and "btexpo.com" not in host:
            if not any(x in host for x in ("facebook.com", "instagram.com", "linkedin.com", "youtube.com", "google.com")):
                external.append(href)
    website = external[0] if external else serper_domain(name)
    paragraphs = [clean(p.get_text(" ", strip=True)) for p in article.find_all("p")]
    description = next((p for p in paragraphs if len(p) > 80), "")
    official_html = fetch(website) if website else ""
    official_soup = BeautifulSoup(official_html, "html.parser")
    text = clean(official_soup.get_text(" ", strip=True))
    meta = official_soup.find("meta", attrs={"name": "description"})
    official_desc = clean(meta.get("content")) if meta else ""
    description = official_desc or description
    mail = email_from(" ".join(a.get("href", "") for a in official_soup.select('a[href^="mailto:"]')))
    mail = mail or email_from(text)
    phone = phone_from(" ".join(a.get("href", "") for a in official_soup.select('a[href^="tel:"]')))
    phone = phone or phone_from(text)
    location, city, country = jsonld_address(official_soup)
    linkedin = next(
        (a["href"] for a in official_soup.find_all("a", href=True) if "linkedin.com" in a["href"].lower()),
        "",
    )
    return {
        "exhibitor_name": name,
        "domain": root_domain(website),
        "contact_number": phone,
        "mail": mail,
        "location": location,
        "country": country,
        "booth_no": "",
        "desc": description,
        "email": mail,
        "phone": phone,
        "address": location,
        "city": city,
        "linkedin_url": linkedin,
        "event_year": EVENT_YEAR,
        "source_profile": item["profile"],
        "source_website": website,
    }


def main():
    records_to_scrape = profile_records(fetch(LISTING_URL))
    if len(records_to_scrape) != 16:
        raise RuntimeError(f"Expected 16 BTExpo 2026 exhibitors, found {len(records_to_scrape)}")
    records = []
    for item in records_to_scrape:
        records.append(scrape_profile(item))
        time.sleep(0.2)
    base = "BELGIUM_TRAVEL_EXPO_2026_exhibitors"
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
