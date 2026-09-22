import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "HOME_BUILDING_AND_RENOVATING_SHOW_SOMERSET_2026"
LIST_URL = "https://somerset.homebuildingshow.co.uk/exhibitor-list"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
VENUE = "Bath & West Showground, Shepton Mallet, Somerset, BA4 6QN, United Kingdom"
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "homebuildingshow.co.uk", "asp.events",
    "eventdata.uk", "homebuilding.co.uk",
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
    for card in soup.select("article.m-exhibitors-list__list__items__item"):
        link = card.select_one("h2 a[href]")
        name_node = card.select_one("h2")
        stand_node = card.select_one("[class*='__meta__stand']")
        if not link or not name_node:
            continue
        profile_url = urljoin(LIST_URL, link.get("href", ""))
        name = clean(name_node.get_text(" ", strip=True))
        stand = clean(stand_node.get_text(" ", strip=True)) if stand_node else ""
        records[profile_url] = {
            "exhibitor_name": name,
            "domain": "",
            "contact_number": "",
            "mail": "",
            "location": VENUE,
            "country": "United Kingdom",
            "booth_no": stand.removeprefix("Stand:").strip(),
            "desc": "",
            "linkedin_url": "",
            "city": "Shepton Mallet",
            "profile_url": profile_url,
            "event_source": LIST_URL,
        }
    return list(records.values())


def parse_profile(record):
    try:
        response = requests.get(record["profile_url"], headers=HEADERS, timeout=45)
        response.encoding = response.apparent_encoding or "utf-8"
        response.raise_for_status()
    except requests.RequestException:
        return record
    soup = BeautifulSoup(response.text, "html.parser")
    schema = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.string or script.get_text())
            schema.extend(value if isinstance(value, list) else [value])
        except (ValueError, TypeError):
            continue
    for item in schema:
        if not isinstance(item, dict):
            continue
        entity = item.get("mainEntity", item)
        if not isinstance(entity, dict):
            continue
        record["domain"] = record["domain"] or root_domain(entity.get("url", ""))
        record["desc"] = record["desc"] or clean(entity.get("description", ""))
    email = soup.select_one('a[href^="mailto:"]')
    phone = soup.select_one('a[href^="tel:"]')
    linkedin = soup.select_one('a[href*="linkedin.com/"]')
    if email:
        record["mail"] = email.get("href", "").split(":", 1)[-1].split("?", 1)[0]
    if phone:
        record["contact_number"] = clean(phone.get("href", "").split(":", 1)[-1])
    if linkedin and "sharing/share-offsite" not in linkedin.get("href", ""):
        record["linkedin_url"] = linkedin.get("href", "")
    for link in soup.select("a[href]"):
        candidate = root_domain(link.get("href", ""))
        if candidate:
            record["domain"] = record["domain"] or candidate
            break
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
    tokens = [token for token in re.findall(r"[a-z0-9]{4,}", name.casefold())]
    return any(token in title or token in host for token in tokens)


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
            json={"q": f'"{record["exhibitor_name"]}" official website Somerset 2026'},
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
    print(f"Found {len(records)} unique 2026 exhibitor profiles")
    with ThreadPoolExecutor(max_workers=16) as pool:
        records = list(pool.map(parse_profile, records))
    records = list({record["exhibitor_name"].casefold(): record for record in records}.values())
    with ThreadPoolExecutor(max_workers=10) as pool:
        records = list(pool.map(enrich_domain, records))
    records.sort(key=lambda item: item["exhibitor_name"].casefold())
    OUT.mkdir(parents=True, exist_ok=True)
    fields = [
        "exhibitor_name", "domain", "contact_number", "mail", "location",
        "country", "booth_no", "desc", "linkedin_url", "city",
        "profile_url", "event_source",
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
