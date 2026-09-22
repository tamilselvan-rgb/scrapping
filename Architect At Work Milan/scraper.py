import csv
import html
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "ARCHITECT_AT_WORK_MILAN_2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LIST_URL = "https://www.architectatwork.com/it/events/a@w-milan/exhibitors"
PROFILE_ROOT = "https://www.architectatwork.com/en/events/a@w-milan/exhibitors/"
DISCOVER_URL = "https://discover-euc1.sitecorecloud.io/discover/v2/108940875"
DISCOVER_AUTH = "01-5d36df32-433a9c72c1e0e9904ab24b2b18d88025d4735260"
PARTICIPATION_ID = "1880952"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "architectatwork.com", "facebook.com", "instagram.com", "linkedin.com",
    "twitter.com", "x.com", "youtube.com", "wikipedia.org", "tripadvisor.com",
    "booking.com", "google.com", "sitecorecloud.io",
}


def clean(value):
    value = html.unescape(str(value or "")).replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def root_domain(url):
    if not url:
        return ""
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if not host or any(host == d or host.endswith("." + d) for d in BLOCKED):
        return ""
    return host


def email_from(text):
    found = re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text or "")
    return found[0].lower() if found else ""


def phone_from(text):
    for value in re.findall(r"(?<!\w)(?:\+|00)?\d[\d\s()./-]{7,}\d", text or ""):
        value = clean(value)
        digits = re.sub(r"\D", "", value)
        if re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)", value):
            continue
        if 8 <= len(digits) <= 16:
            return value
    return ""


def country_name(value):
    value = clean(value)
    aliases = {"IT": "Italy", "DE": "Germany", "AT": "Austria", "FR": "France",
               "ES": "Spain", "CH": "Switzerland", "BE": "Belgium", "PT": "Portugal"}
    return aliases.get(value.upper(), value)


def api_body(offset):
    return {
        "context": {
            "page": {"uri": "/it/events/a@w-milan/exhibitors"},
            "user": {"uuid": "108940875-scraper"},
            "browser": {"user_agent": HEADERS["User-Agent"]},
            "locale": {"country": "it", "language": "it"},
        },
        "widget": {"items": [{
            "rfk_id": "rfkid_11",
            "search": {
                "content": {}, "facet": {"all": True}, "offset": offset,
                "sort": {"choices": True, "value": [{"name": "relevance_13"}]},
                "limit": 90, "query": {"operator": "and"},
                "filter": {"type": "and", "filters": [{
                    "type": "anyOf", "name": "related_id", "values": [PARTICIPATION_ID]
                }]},
            },
            "entity": "content",
        }]},
    }


def list_exhibitors():
    response = requests.post(
        DISCOVER_URL, json=api_body(0),
        headers={**HEADERS, "Authorization": DISCOVER_AUTH,
                 "Content-Type": "application/json", "Origin": "https://www.architectatwork.com"},
        timeout=90,
    )
    response.raise_for_status()
    widget = response.json()["widgets"][0]
    records = list(widget.get("content", []))
    total = int(widget.get("total_item", len(records)))
    for offset in range(90, total, 90):
        response = requests.post(
            DISCOVER_URL, json=api_body(offset),
            headers={**HEADERS, "Authorization": DISCOVER_AUTH,
                     "Content-Type": "application/json", "Origin": "https://www.architectatwork.com"},
            timeout=90,
        )
        response.raise_for_status()
        records.extend(response.json()["widgets"][0].get("content", []))
    return records[:total]


def participation_name(item):
    names = item.get("xp", {}).get("participation_exhibitor_names", [])
    for entry in names:
        if str(entry.get("edition")) == PARTICIPATION_ID and entry.get("name"):
            return clean(entry["name"])
    return clean(item.get("title"))


def booth(item):
    for entry in item.get("xp", {}).get("booth", []):
        if str(entry.get("edition")) == PARTICIPATION_ID:
            return clean(entry.get("boothNumber"))
    return ""


def profile_url(item):
    source = item.get("url", "")
    slug = source.split("/exhibitors/")[-1].split("?")[0]
    return PROFILE_ROOT + slug + "?participation=" + PARTICIPATION_ID


def parse_profile(item):
    url = profile_url(item)
    response = None
    for attempt in range(3):
        try:
            response = requests.get(url, headers=HEADERS, timeout=60)
            response.raise_for_status()
            break
        except requests.RequestException:
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    if response is None:
        return {"profile_url": url}
    soup = BeautifulSoup(response.content, "html.parser")
    text = clean(soup.get_text(" ", strip=True))
    name = participation_name(item)
    marker = "Who is " + name
    description = ""
    if marker in text:
        description = text.split(marker, 1)[1].split("Visit website", 1)[0].strip()
    website = ""
    for link in soup.select("a[href]"):
        href = link.get("href", "")
        label = clean(link.get_text(" ", strip=True)).lower()
        if "visit website" in label or "visita il sito" in label:
            website = href
            break
    jsonld = []
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            jsonld.append(json.loads(node.string or node.get_text()))
        except (json.JSONDecodeError, TypeError):
            pass
    address = ""
    for node in jsonld:
        nodes = node if isinstance(node, list) else [node]
        for data in nodes:
            if isinstance(data, dict):
                addr = data.get("address")
                if isinstance(addr, dict):
                    address = clean(" ".join(str(addr.get(k, "")) for k in
                                             ("streetAddress", "postalCode", "addressLocality", "addressRegion")))
                elif isinstance(addr, str):
                    address = clean(addr)
    if not address:
        address = ""
    return {
        "profile_url": url,
        "exhibitor_name": name,
        "desc": description,
        "domain": root_domain(website),
        "contact_number": "",
        "mail": "",
        "location": address,
        "country": country_name((item.get("country") or ["Italy"])[0]),
        "booth_no": booth(item),
    }


def website_contacts(record):
    domain = record["domain"]
    if not domain:
        return record
    try:
        response = requests.get("https://" + domain, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(response.text, "html.parser")
        text = clean(soup.get_text(" ", strip=True))
        record["mail"] = record["mail"] or email_from(response.text)
        record["contact_number"] = record["contact_number"] or phone_from(text)
        for node in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(node.string or node.get_text())
            except (json.JSONDecodeError, TypeError):
                continue
            values = data if isinstance(data, list) else [data]
            for item in values:
                if isinstance(item, dict):
                    addr = item.get("address")
                    if not record["location"] and isinstance(addr, dict):
                        record["location"] = clean(" ".join(str(addr.get(k, "")) for k in
                                                           ("streetAddress", "postalCode", "addressLocality", "addressRegion")))
    except requests.RequestException:
        pass
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
            json={"q": f'"{name}" official website A@W Milan 2026'},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        kg = data.get("knowledgeGraph", {})
        candidate = kg.get("website", "")
        if not candidate:
            for result in data.get("organic", []):
                candidate = result.get("link", "")
                if root_domain(candidate):
                    break
        return root_domain(candidate)
    except requests.RequestException:
        return ""


def enrich(record):
    if not record["domain"]:
        record["domain"] = serper_domain(record["exhibitor_name"])
        if record["domain"]:
            record = website_contacts(record)
    return record


def main():
    OUT.mkdir(exist_ok=True)
    items = list_exhibitors()
    records = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(parse_profile, item) for item in items]
        for future in as_completed(futures):
            record = future.result()
            if record.get("exhibitor_name"):
                records.append(record)
    records.sort(key=lambda row: row["exhibitor_name"].lower())
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(website_contacts, records))
    missing = [record for record in records if not record["domain"]]
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(enrich, missing))
    fields = ["exhibitor_name", "domain", "contact_number", "mail",
              "location", "country", "booth_no", "desc", "profile_url"]
    csv_path = OUT / f"{EVENT}_exhibitors.csv"
    json_path = OUT / f"{EVENT}_exhibitors.json"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Scraped {len(records)} exhibitors")
    print(csv_path)
    print(json_path)


if __name__ == "__main__":
    main()
