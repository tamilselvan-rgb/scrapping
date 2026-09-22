import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "FORUM_FRANCHISE_COTE_DAZUR_2026"
LIST_URL = "https://www.forum-franchise-region-sud.com/ExhibitorList/1835?view=cards"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "forum-franchise-region-sud.com", "wikipedia.org",
    "yellowpages.com", "yelp.com",
}


def clean(value):
    value = html.unescape(str(value or "")).replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def root_domain(value):
    value = clean(value)
    if not value or value.lower().startswith(("mailto:", "tel:")):
        return ""
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    host = (urlparse(value).hostname or "").lower().removeprefix("www.")
    if not host or "." not in host or any(host == x or host.endswith("." + x) for x in BLOCKED):
        return ""
    return host


def parse_listing():
    response = requests.get(LIST_URL, headers=HEADERS, timeout=60)
    response.encoding = response.apparent_encoding or "utf-8"
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    records = {}
    for panel in soup.select(".ExhibitorPanel"):
        link = panel.select_one("a.ExhibitorLink[href]")
        name = panel.select_one("[itemprop='legalName'] b")
        if not link or not name:
            continue
        record = {
            "exhibitor_name": clean(name.get_text(" ", strip=True)),
            "domain": "",
            "contact_number": "",
            "mail": "",
            "location": "",
            "country": "France",
            "booth_no": "",
            "desc": "",
            "linkedin_url": "",
            "city": "",
            "represented_by": "",
            "profile_url": urljoin(LIST_URL, link.get("href", "")),
            "event_source": LIST_URL,
        }
        brand = panel.select_one("[itemprop='brand'] a")
        if brand:
            record["represented_by"] = clean(brand.get_text(" ", strip=True))
        records[record["profile_url"]] = record
    return list(records.values())


def parse_profile(record):
    try:
        response = requests.get(record["profile_url"], headers=HEADERS, timeout=45)
        response.encoding = response.apparent_encoding or "utf-8"
        response.raise_for_status()
    except requests.RequestException:
        return record
    soup = BeautifulSoup(response.text, "html.parser")
    value = lambda selector: clean(soup.select_one(selector).get_text(" ", strip=True)) if soup.select_one(selector) else ""
    record["exhibitor_name"] = value("#CompanyNameLabel") or record["exhibitor_name"]
    street = value("#StreetLabel")
    postal = value("#ZipCodeLabel")
    city = value("#CityLabel")
    country = value("#CountryLabel")
    record["location"] = clean(" ".join(part for part in [street, postal, city, country] if part))
    record["city"] = city
    record["country"] = country or "France"
    record["domain"] = root_domain(soup.select_one("#WebSiteLink").get("href", "") if soup.select_one("#WebSiteLink") else "")
    record["booth_no"] = value("#boothPanel").removeprefix("Stand n°:").strip()
    business = value("#BusinessLabel")
    presentation = value("#PresentationLabel")
    record["desc"] = clean(" ".join(part for part in [business, presentation] if part))
    linkedin = soup.select_one('a[href*="linkedin.com/"]')
    if linkedin:
        record["linkedin_url"] = linkedin.get("href", "")
    return record


def serper_key():
    env = Path(__file__).resolve().parents[1] / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"\'')
    return ""


def relevant(result, name):
    title = clean(result.get("title", "")).casefold()
    host = (urlparse(result.get("link", "")).hostname or "").lower()
    normalized_name = re.sub(r"[^a-z0-9]", "", name.casefold())
    normalized_title = re.sub(r"[^a-z0-9]", "", title)
    normalized_host = re.sub(r"[^a-z0-9]", "", host)
    if normalized_name and normalized_name in normalized_title:
        return True
    tokens = [token for token in re.findall(r"[a-z0-9]{4,}", name.casefold())]
    return len(tokens) >= 2 and all(token in normalized_host for token in tokens[:2])


def enrich_domain(record):
    if record["domain"]:
        return record
    key = serper_key()
    if not key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website Forum Franchise Region Sud 2026'},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        record["domain"] = root_domain(data.get("knowledgeGraph", {}).get("website", ""))
        if not record["domain"]:
            for result in data.get("organic", []):
                candidate = root_domain(result.get("link", ""))
                if candidate and relevant(result, record["exhibitor_name"]):
                    record["domain"] = candidate
                    break
    except requests.RequestException:
        pass
    return record


def main():
    records = parse_listing()
    print(f"Found {len(records)} official 2026 exhibitor profiles")
    with ThreadPoolExecutor(max_workers=16) as pool:
        records = list(pool.map(parse_profile, records))
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(enrich_domain, records))
    records.sort(key=lambda item: item["exhibitor_name"].casefold())
    OUT.mkdir(parents=True, exist_ok=True)
    fields = [
        "exhibitor_name", "domain", "contact_number", "mail", "location",
        "country", "booth_no", "desc", "linkedin_url", "city",
        "represented_by", "profile_url", "event_source",
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


if __name__ == "__main__":
    main()
