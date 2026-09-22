import csv
import html
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "FASHIONEX_2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LIST_URL = "https://fashionex.it/en/espositori/"
BASE_URL = "https://fashionex.it"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED_DOMAINS = {
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com",
    "google.com", "fashionex.it", "ti.to", "sibforms.com", "tradefairdates.com",
    "pixelstorming.com",
    "voce.it", "wotol.com", "deviantart.com", "quasar-shisha.com",
    "cdc.gov", "apps.apple.com", "online.suny.edu",
}


def clean(value):
    value = html.unescape(str(value or "")).replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def root_domain(value):
    if not value:
        return ""
    value = value.strip()
    if value.lower().startswith(("mailto:", "tel:")) or "@" in value:
        return ""
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    host = (urlparse(value).hostname or "").lower().removeprefix("www.")
    if not host or any(host == item or host.endswith("." + item) for item in BLOCKED_DOMAINS):
        return ""
    return host


def email_from_soup(soup):
    for link in soup.select('a[href^="mailto:"]'):
        address = link.get("href", "").split(":", 1)[1].split("?", 1)[0].strip()
        if "@" in address:
            return address.lower()
    match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", soup.get_text(" ", strip=True))
    return match.group(0).lower() if match else ""


def phone_from_text(text):
    for value in re.findall(r"(?<!\w)(?:\+|00)?\d[\d\s()./-]{7,}\d", text or ""):
        value = clean(value)
        digits = re.sub(r"\D", "", value)
        if 8 <= len(digits) <= 16 and not re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)", value):
            return value
    return ""


def label_value(soup, label):
    node = next(
        (tag for tag in soup.find_all(["p", "dt", "span", "div"])
         if clean(tag.get_text(" ", strip=True)).lower() == label.lower()),
        None,
    )
    if not node:
        return ""
    sibling = node.find_next(["p", "dd"])
    if sibling and sibling is not node:
        value = clean(sibling.get_text(" ", strip=True))
        if value.lower() != label.lower():
            return value
    parent_text = clean(node.parent.get_text(" ", strip=True))
    return clean(re.sub(re.escape(label), "", parent_text, flags=re.I))


def split_address(address):
    address = clean(address)
    if not address:
        return "", ""
    # FashionEx currently publishes Italian addresses as "street City (province)".
    city_match = re.search(r"([A-ZÀ-Ý][A-Za-zÀ-ÿ' -]+)\s*\([A-Z]{2}\)\s*$", address)
    if city_match:
        city = clean(city_match.group(1))
        city = re.sub(r"^[A-Z]/\s*", "", city)
        return clean(address[:city_match.start()]), city
    parts = [clean(part) for part in re.split(r",|\t", address) if clean(part)]
    if len(parts) > 1:
        return address, parts[-1]
    words = address.split()
    return address, words[-1] if len(words) > 1 else ""


def listing():
    response = requests.get(LIST_URL, headers=HEADERS, timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    records = []
    seen = set()
    for link in soup.select('a[href*="/en/espositori/"]'):
        href = urljoin(BASE_URL, link.get("href", ""))
        parsed = urlparse(href)
        if parsed.path.rstrip("/") in ("/en/espositori", "/en/espositori/"):
            continue
        if href in seen:
            continue
        seen.add(href)
        name = clean(link.select_one("img").get("alt", "") if link.select_one("img") else link.get_text(" ", strip=True))
        name = re.sub(r"\s+FashionEx\s*$", "", name, flags=re.I).strip()
        if name:
            records.append({
                "exhibitor_name": name,
                "domain": "",
                "contact_number": "",
                "mail": "",
                "location": "",
                "country": "Italy",
                "booth_no": "",
                "desc": "",
                "linkedin_url": "",
                "profile_url": href,
            })
    return records


def parse_profile(record):
    try:
        response = requests.get(record["profile_url"], headers=HEADERS, timeout=60)
        response.raise_for_status()
    except requests.RequestException:
        return record
    soup = BeautifulSoup(response.content, "html.parser")
    heading = soup.select_one("main h1, h1")
    if heading:
        record["exhibitor_name"] = clean(heading.get_text(" ", strip=True))
    paragraphs = [clean(p.get_text(" ", strip=True)) for p in soup.select("main p")]
    for label_node in soup.find_all(["h3", "dt", "strong"]):
        label = clean(label_node.get_text(" ", strip=True)).lower()
        value_node = label_node.find_next_sibling(["p", "dd"])
        value = clean(value_node.get_text(" ", strip=True)) if value_node else ""
        if label == "email":
            record["mail"] = value.lower()
        elif label == "phone":
            record["contact_number"] = value
        elif label == "website":
            record["domain"] = root_domain(value)
        elif label == "address":
            record["location"] = value
    website_link = next(
        (a for a in soup.select('a[href^="http"]') if root_domain(a.get("href", ""))),
        None,
    )
    if website_link:
        record["domain"] = root_domain(website_link.get("href", ""))
    record["mail"] = record["mail"] or email_from_soup(soup)
    if not record["contact_number"]:
        record["contact_number"] = phone_from_text(soup.get_text(" ", strip=True))
    # The first prose paragraph after the product heading is the English description.
    product_heading = next(
        (p for p in soup.find_all(["p", "h2", "h3"])
         if clean(p.get_text(" ", strip=True)).lower() == "type of product"),
        None,
    )
    if product_heading:
        for node in product_heading.find_all_next(["p"], limit=4):
            text = clean(node.get_text(" ", strip=True))
            if text and text.lower() not in {"email", "phone", "website", "address"}:
                if len(text) > 35:
                    record["desc"] = text
                    break
    linkedin = soup.select_one('a[href*="linkedin.com/"]')
    if linkedin:
        record["linkedin_url"] = linkedin.get("href", "")
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
            json={"q": f'"{record["exhibitor_name"]}" official website 2026'},
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
        # Organic results are used only when they clearly resolve to the
        # exhibitor's own site; unrelated directory matches are left blank.
    except requests.RequestException:
        pass
    return record


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = listing()
    print(f"Found {len(records)} official 2026 exhibitor profiles")
    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(parse_profile, records))
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(enrich_missing, records))
    for record in records:
        record["location"], city = split_address(record["location"])
        record["city"] = city
        record["country"] = record["country"] or "Italy"
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
