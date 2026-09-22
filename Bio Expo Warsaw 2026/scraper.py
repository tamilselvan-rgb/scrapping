import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests


EVENT = "BIO_EXPO_WARSAW_2026"
SOURCE_URL = "https://bioexpo.pl/"
CATALOG_URL = "https://bioexpo.pl/katalog-wystawcow/"
DATA_URL = "https://bioexpo.pl/wp-content/uploads/exhibitor-catalogs/pwe-exhibitors.json"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
EVENT_LOCATION = "Ptak Warsaw Expo, Al. Katowicka 62, 05-830 Nadarzyn, Poland"
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "tiktok.com", "bioexpo.pl", "ptakwarsawexpo.com",
    "wikipedia.org", "yellowpages.com", "yelp.com",
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


def record_from_item(item):
    info = item.get("companyInfo") or {}
    exhibitor = item.get("exhibitor") or {}
    stand = item.get("stand") or {}
    address = clean(exhibitor.get("address", ""))
    postal = clean(exhibitor.get("postalCode", ""))
    city = clean(exhibitor.get("city", ""))
    location = clean(" ".join(part for part in [address, postal, city, "Poland"] if part))
    description = clean(info.get("description", ""))
    products = item.get("products") or []
    product_names = []
    for product in products:
        if isinstance(product, dict):
            value = product.get("name") or product.get("title") or ""
        else:
            value = product
        if clean(value):
            product_names.append(clean(value))
    if product_names:
        description = clean(" ".join([description, "Products: " + ", ".join(product_names)]))
    return {
        "exhibitor_name": clean(info.get("displayName") or info.get("name", "")),
        "domain": root_domain(info.get("website", "")),
        "contact_number": clean(info.get("contactPhone", "")),
        "mail": clean(info.get("contactEmail", "")),
        "location": location,
        "country": "Poland",
        "booth_no": clean(" / ".join(part for part in [stand.get("hallName", ""), stand.get("standNumber", "")] if part)),
        "desc": description,
        "linkedin_url": clean(info.get("linkedin", "")),
        "city": city,
        "event_location": EVENT_LOCATION,
        "profile_url": "",
        "event_source": CATALOG_URL,
    }


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
            json={"q": f'"{record["exhibitor_name"]}" official website BIOEXPO Warsaw 2026'},
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
    response = requests.get(DATA_URL, headers=HEADERS, timeout=60)
    response.raise_for_status()
    items = [item for item in response.json() if item.get("catalog_id") == 162]
    records = [record_from_item(item) for item in items]
    records = list({record["exhibitor_name"].casefold(): record for record in records}.values())
    print(f"Found {len(records)} BIOEXPO Warsaw 2026 exhibitors")
    with ThreadPoolExecutor(max_workers=10) as pool:
        records = list(pool.map(enrich_domain, records))
    records.sort(key=lambda item: item["exhibitor_name"].casefold())
    OUT.mkdir(parents=True, exist_ok=True)
    fields = [
        "exhibitor_name", "domain", "contact_number", "mail", "location",
        "country", "booth_no", "desc", "linkedin_url", "city",
        "event_location", "profile_url", "event_source",
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
