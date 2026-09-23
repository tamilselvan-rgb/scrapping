import csv
import html
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import requests


EVENT = "TRADE_FAIR_OF_TECHNOLOGY_EQUIPMENT_AND_FURNISHINGS_FOR_QUICK_SERVICE_RESTAURANTS_2026"
SOURCE = "https://gastroquickservice.com/en/exhibitors-catalog/"
API_URL = "https://gastroquickservice.com/wp-content/uploads/exhibitor-catalogs/pwe-exhibitors.json"
CATALOG_ID = 167
VENUE = "Ptak Warsaw Expo, Aleja Katowicka 62, 05-830 Nadarzyn, Poland"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "gastroquickservice.com", "wikipedia.org", "yellowpages.com",
    "yelp.com", "bizraport.pl",
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
    address = clean(exhibitor.get("address"))
    postal = clean(exhibitor.get("postalCode"))
    city = clean(exhibitor.get("city"))
    location = ", ".join(part for part in (address, postal, city, "Poland") if part)
    if not location:
        location = VENUE
    description = clean(info.get("description")) or clean(info.get("whyVisit"))
    hall = clean(stand.get("hallName"))
    number = clean(stand.get("standNumber"))
    booth = " / ".join(part for part in (hall, number) if part)
    products = item.get("products") or []
    return {
        "exhibitor_name": clean(info.get("displayName") or info.get("name")),
        "domain": root_domain(info.get("website")),
        "contact_number": clean(info.get("contactPhone")),
        "mail": clean(info.get("contactEmail")),
        "location": location,
        "country": "Poland",
        "booth_no": booth,
        "desc": description,
        "linkedin_url": clean(info.get("linkedin")),
        "city": city,
        "profile_url": SOURCE,
        "event_source": SOURCE,
        "exhibitor_id": clean(item.get("exhibitorId")),
        "stand_id": clean(item.get("standId")),
        "booth_area_sqm": clean(stand.get("boothArea")),
        "brands": "; ".join(clean(brand) for brand in info.get("brands") or []),
        "products": json.dumps(products, ensure_ascii=False),
    }


def serper_enrich(record, api_key):
    if record["domain"] or not api_key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website 2026 Poland', "gl": "pl", "hl": "en", "num": 10},
            timeout=45,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph") or {}
        record["domain"] = root_domain(graph.get("website", ""))
        for result in data.get("organic", []):
            if not record["domain"]:
                record["domain"] = root_domain(result.get("link", ""))
            if not record["linkedin_url"] and "linkedin.com/" in result.get("link", ""):
                record["linkedin_url"] = result["link"].split("?", 1)[0]
    except Exception as exc:
        print(f"Serper failed: {record['exhibitor_name']}: {exc}")
    return record


def load_api_key():
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def main():
    out = Path(__file__).resolve().parent / "output"
    out.mkdir(exist_ok=True)
    response = requests.get(API_URL, headers=HEADERS, timeout=60)
    response.raise_for_status()
    items = [item for item in response.json() if item.get("catalog_id") == CATALOG_ID]
    records = [record_from_item(item) for item in items]
    from concurrent.futures import ThreadPoolExecutor
    api_key = load_api_key()
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda record: serper_enrich(record, api_key), records))
    records.sort(key=lambda record: record["exhibitor_name"].casefold())
    fields = [
        "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
        "booth_no", "desc", "linkedin_url", "city", "profile_url", "event_source",
        "exhibitor_id", "stand_id", "booth_area_sqm", "brands", "products",
    ]
    csv_path = out / f"{EVENT}_exhibitors.csv"
    json_path = out / f"{EVENT}_exhibitors.json"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf8")
    print(f"Found {len(records)} published 2026 exhibitors")
    print(f"Wrote {csv_path} and {json_path}")


if __name__ == "__main__":
    main()
