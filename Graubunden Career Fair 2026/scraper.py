import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup


EVENT = "GRAUBUNDEN_CAREER_FAIR_2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LIST_URL = "https://fiutscher.ch/berufsausstellung/ausstellung-2026/aussteller"
BASE_URL = "https://fiutscher.ch"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "fiutscher.ch", "facebook.com", "instagram.com", "linkedin.com",
    "twitter.com", "x.com", "youtube.com", "tiktok.com", "wikipedia.org",
    "google.com", "gmail.com", "hotmail.com", "yahoo.com",
}


def clean(value):
    value = html.unescape(str(value or "")).replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def root_domain(value):
    if not value:
        return ""
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    host = (urlparse(value).hostname or "").lower().removeprefix("www.")
    if not host or any(host == item or host.endswith("." + item) for item in BLOCKED):
        return ""
    return host


def extract_email(soup):
    for link in soup.select('a[href^="mailto:"]'):
        value = link["href"].split(":", 1)[1].split("?", 1)[0].strip()
        if "@" in value and root_domain(value.rsplit("@", 1)[1]):
            return value.lower()
    return ""


def extract_phone(soup):
    for link in soup.select('a[href^="tel:"]'):
        value = clean(link["href"].split(":", 1)[1])
        digits = re.sub(r"\D", "", value)
        if 8 <= len(digits) <= 16:
            return value
    return ""


def list_exhibitors():
    response = requests.get(LIST_URL, headers=HEADERS, timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    records = []
    seen = set()
    for link in soup.select('a[href^="/aussteller/"]'):
        href = link.get("href", "")
        if not link.get("title") or href in seen:
            continue
        seen.add(href)
        records.append({
            "exhibitor_name": clean(link.get("title") or link.get_text(" ", strip=True)),
            "profile_url": urljoin(BASE_URL, href),
            "country": "Switzerland",
            "booth_no": "",
        })
    return records


def parse_profile(record):
    try:
        response = requests.get(record["profile_url"], headers=HEADERS, timeout=60)
        response.raise_for_status()
    except requests.RequestException:
        record.update({"domain": "", "mail": "", "contact_number": "",
                       "location": "", "desc": "", "linkedin_url": ""})
        return record
    soup = BeautifulSoup(response.content, "html.parser")
    heading = soup.select_one("h1")
    if heading:
        record["exhibitor_name"] = clean(heading.get_text(" ", strip=True))
    header = soup.select_one(".m-header__inner-left")
    address = header.select_one("address") if header else None
    location = ""
    if address:
        location = clean(address.get_text(" ", strip=True))
        location = re.split(r"\bWebsite besuchen\b", location, flags=re.I)[0].strip()
    website = ""
    for link in (header or soup).select('a[href]'):
        label = clean(link.get_text(" ", strip=True)).lower()
        href = link.get("href", "")
        if "website" in label and href:
            website = href
            break
    record.update({
        "domain": root_domain(website),
        "mail": extract_email(header or soup),
        "contact_number": extract_phone(header or soup),
        "location": location,
        "desc": "",
        "linkedin_url": "",
    })
    # The profile footer always contains FIUTSCHER's contact details; do not
    # copy those organizer contacts into the exhibitor record.
    occupations = [clean(item.get_text(" ", strip=True))
                   for item in soup.select("h3.m-card__title")]
    if occupations:
        record["desc"] = "Training and career areas: " + "; ".join(occupations)
    return record


def serper_domain(name):
    env = ROOT.parent / ".env"
    key = ""
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("SERPER_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"\'')
    if not key:
        return ""
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": f'"{name}" official website FIUTSCHER 2026'},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        candidate = data.get("knowledgeGraph", {}).get("website", "")
        for result in data.get("organic", []):
            if not root_domain(candidate):
                candidate = result.get("link", "")
            if root_domain(candidate):
                break
        return root_domain(candidate)
    except requests.RequestException:
        return ""


def website_contacts(record):
    if not record["domain"]:
        return record
    try:
        response = requests.get("https://" + record["domain"], headers=HEADERS, timeout=25)
        soup = BeautifulSoup(response.content, "html.parser")
        if not record["mail"]:
            record["mail"] = extract_email(soup)
        if not record["contact_number"]:
            record["contact_number"] = extract_phone(soup)
        if not record["linkedin_url"]:
            for link in soup.select('a[href*="linkedin.com/"]'):
                record["linkedin_url"] = link["href"]
                break
    except requests.RequestException:
        pass
    return record


def enrich(record):
    if not record["domain"]:
        record["domain"] = serper_domain(record["exhibitor_name"])
    return website_contacts(record)


def main():
    OUT.mkdir(exist_ok=True)
    records = list_exhibitors()
    print(f"Found {len(records)} exhibitors")
    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(parse_profile, records))
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(enrich, records))
    records.sort(key=lambda item: item["exhibitor_name"].lower())
    fields = ["exhibitor_name", "domain", "contact_number", "mail", "location",
              "country", "booth_no", "desc", "linkedin_url", "profile_url"]
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
