import csv
import html
import json
import os
import re
import time
import unicodedata
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "SALON_INDUSTRIES_DU_FUTUR_TRADE_SHOW_2026"
BASE_URL = "https://www.euroindustries.eu/fr/content/les-exposants-2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
VENUE = "Parc Expo de Mulhouse, 120 Rue Lefebure, 68100 Mulhouse, France"
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "euroindustries.eu", "wikipedia.org", "yellowpages.com",
    "yelp.com",
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


def extract_state(text):
    marker = 'INITIAL_STATE = JSON.parse(decodeURIComponent("'
    start = text.index(marker) + len(marker)
    end = text.index('"));', start)
    return json.loads(urllib.parse.unquote(text[start:end]))


def slugify(value):
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return value


def find_entity(value, expected_name=""):
    if isinstance(value, dict):
        if value.get("name") and (not expected_name or clean(value["name"]).casefold() == clean(expected_name).casefold()):
            if any(k in value for k in ("website", "description", "linkedin", "email", "phone")):
                return value
        for child in value.values():
            found = find_entity(child, expected_name)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_entity(child, expected_name)
            if found:
                return found
    return {}


def profile_record(item, session):
    name = clean(item.get("name"))
    profile_url = f"https://www.euroindustries.eu/fr/partner/{item['id']}/{slugify(name)}"
    record = {
        "exhibitor_name": name,
        "domain": "",
        "contact_number": "",
        "mail": "",
        "location": VENUE,
        "country": "France",
        "booth_no": "",
        "desc": "",
        "linkedin_url": "",
        "city": "Mulhouse",
        "profile_url": profile_url,
        "event_source": BASE_URL,
    }
    try:
        response = session.get(profile_url, headers=HEADERS, timeout=60)
        response.raise_for_status()
        state = extract_state(response.text)
        entity = find_entity(state, name)
        description = entity.get("description", "")
        if isinstance(description, dict):
            description = description.get("en") or description.get("fr") or ""
        record["desc"] = clean(description)
        record["domain"] = root_domain(entity.get("website", ""))
        record["linkedin_url"] = clean(entity.get("linkedin", ""))
        soup = BeautifulSoup(response.text, "html.parser")
        for link in soup.select('a[href^="mailto:"]'):
            record["mail"] = link["href"].split(":", 1)[1].split("?", 1)[0].strip()
            break
        for link in soup.select('a[href^="tel:"]'):
            record["contact_number"] = clean(link["href"].split(":", 1)[1])
            break
        if not record["contact_number"]:
            record["contact_number"] = phone_from_text(soup.get_text(" ", strip=True))
    except Exception as exc:
        print(f"profile failed: {name}: {exc}")
    return record


def phone_from_text(text):
    match = re.search(r"(?<!\d)(?:\+?\d[\d\s()./-]{7,}\d)(?!\d)", text)
    return clean(match.group(0)) if match else ""


def serper_enrich(record, api_key, session):
    if not api_key:
        return record
    query = f'"{record["exhibitor_name"]}" official website {record["city"]} France 2026'
    try:
        response = session.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "gl": "fr", "hl": "en", "num": 10},
            timeout=45,
        )
        response.raise_for_status()
        data = response.json()
        kg = data.get("knowledgeGraph") or {}
        if not record["domain"]:
            record["domain"] = root_domain(kg.get("website", ""))
        if not record["contact_number"]:
            record["contact_number"] = clean(kg.get("phone", ""))
        if record["location"] == VENUE and kg.get("address"):
            record["location"] = clean(kg["address"])
        for result in data.get("organic", []):
            link = result.get("link", "")
            domain = root_domain(link)
            if not record["domain"] and domain:
                record["domain"] = domain
            if not record["linkedin_url"] and "linkedin.com/company/" in link:
                record["linkedin_url"] = link.split("?", 1)[0]
            if not record["desc"] and result.get("snippet"):
                record["desc"] = clean(result["snippet"])
    except Exception as exc:
        print(f"Serper failed: {record['exhibitor_name']}: {exc}")
    return record


def listing(session):
    items = []
    for page in range(1, 5):
        response = session.get(f"{BASE_URL}?page={page}", headers=HEADERS, timeout=60)
        response.raise_for_status()
        state = extract_state(response.text)
        page_data = state["pages"]["companion.contentpage.les-exposants-2026"]["data"]
        collection = next(v for v in page_data.values() if isinstance(v, dict) and "items" in v)
        items.extend(collection["items"])
    unique = {}
    for item in items:
        if item.get("name") and item.get("id"):
            unique[item["name"].casefold()] = item
    return list(unique.values())


def main():
    OUT.mkdir(exist_ok=True)
    session = requests.Session()
    items = listing(session)
    print(f"Found {len(items)} 2026 exhibitors")
    with ThreadPoolExecutor(max_workers=10) as pool:
        records = list(pool.map(lambda item: profile_record(item, requests.Session()), items))
    api_key = ""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf8").splitlines():
            if line.startswith("SERPER_API_KEY="):
                api_key = line.split("=", 1)[1].strip()
                break
    missing = [r for r in records if not r["domain"] or not r["contact_number"] or r["location"] == VENUE]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda record: serper_enrich(record, api_key, requests.Session()), missing))
    records.sort(key=lambda r: r["exhibitor_name"].casefold())
    fields = [
        "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
        "booth_no", "desc", "linkedin_url", "city", "profile_url", "event_source",
    ]
    csv_path = OUT / f"{EVENT}_exhibitors.csv"
    json_path = OUT / f"{EVENT}_exhibitors.json"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf8")
    print(f"Wrote {len(records)} records to {csv_path} and {json_path}")


if __name__ == "__main__":
    main()
