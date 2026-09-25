import csv
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "ALLPRINT_INDONESIA_2026"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
BASE_URL = "https://allprint.co.id"
API_URL = f"{BASE_URL}/api/ajax"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ExhibitorResearch/1.0)"}
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location",
    "country", "company_name", "booth", "description", "city", "linkedin_url",
]
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com", "allprint.co.id",
    "kristaonline.com",
}


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def domain_url(value):
    value = clean(value)
    if not value:
        return ""
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    host = (urlparse(value).hostname or "").lower().removeprefix("www.")
    if not host or "." not in host:
        return ""
    if any(host == item or host.endswith("." + item) for item in BLOCKED):
        return ""
    return host


def matching_domain(name, domain):
    if not domain:
        return ""
    host = re.sub(r"[^a-z0-9]", "", domain.split(".")[0].casefold())
    tokens = {
        token for token in re.findall(r"[a-z0-9]+", name.casefold())
        if len(token) >= 3 and token not in {
            "ltd", "llc", "inc", "pt", "co", "company", "the", "and",
        }
    }
    return domain if host and tokens and any(
        token in host or host in token for token in tokens
    ) else ""


def fetch(url, **kwargs):
    for attempt in range(4):
        try:
            response = requests.get(url, headers=HEADERS, timeout=60, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


def listing_page(page):
    response = fetch(API_URL, params={"type": "search", "page": page})
    payload = response.json()
    return BeautifulSoup(payload.get("html", ""), "html.parser")


def listing():
    records = []
    for page in range(1, 13):
        soup = listing_page(page)
        cards = soup.select("textarea.data-item")
        if not cards:
            break
        for card in cards:
            try:
                data = json.loads(card.text)
            except json.JSONDecodeError:
                continue
            exhibitor_id = data.get("exhibitor_exhibition_id")
            if not exhibitor_id:
                continue
            records.append({
                "id": str(exhibitor_id),
                "exhibitor_name": clean(data.get("exhibitor_name")),
                "country": clean(data.get("country")),
                "booth": clean(data.get("booth_number") or data.get("stand_name")),
                "profile_url": f"{BASE_URL}/detail-exhibitor/{exhibitor_id}",
            })
    unique = {}
    for record in records:
        unique.setdefault(record["id"], record)
    return list(unique.values())


def profile(record):
    try:
        soup = BeautifulSoup(fetch(record["profile_url"]).content, "html.parser")
        detail = json.loads(soup.select_one("textarea.data-item").text)
    except (requests.RequestException, AttributeError, json.JSONDecodeError, TypeError):
        detail = {}
    profiles = detail.get("company_profile") or []
    company = profiles[0] if profiles else {}
    city = (company.get("city") or {}).get("name", "")
    province = (company.get("province") or {}).get("name", "")
    address = clean(company.get("full_address") or company.get("address"))
    if address and province and province not in address:
        address = f"{address}, {province}"
    name = clean(detail.get("exhibitor_name") or record["exhibitor_name"])
    country = clean(detail.get("country") or record["country"])
    return {
        "exhibitor_name": name,
        "domain": matching_domain(name, domain_url(company.get("website"))),
        "contact_number": clean(company.get("official_phone")),
        "mail": clean(company.get("email")).lower(),
        "location": address,
        "country": country,
        "company_name": name,
        "booth": clean(detail.get("booth_number") or record["booth"]),
        "description": clean(detail.get("line_of_business")),
        "city": clean(city),
        "linkedin_url": "",
    }


def serper_key():
    env = ROOT.parent / ".env"
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip().strip("\"'")
    return ""


def serper_enrich(record):
    if record["domain"] or not serper_key():
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": serper_key(), "Content-Type": "application/json"},
            json={
                "q": f'"{record["exhibitor_name"]}" official website {record["location"] or record["country"]}',
                "gl": "id", "hl": "en", "num": 10,
            },
            timeout=45,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph") or {}
        candidates = [graph.get("website", "")]
        candidates.extend(item.get("link", "") for item in data.get("organic", []))
        for candidate in candidates:
            domain = matching_domain(record["exhibitor_name"], domain_url(candidate))
            if domain:
                record["domain"] = domain
                break
        if not record["contact_number"]:
            record["contact_number"] = clean(graph.get("phone"))
        if not record["location"]:
            record["location"] = clean(graph.get("address"))
    except requests.RequestException:
        pass
    return record


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source_records = listing()
    print(f"Found {len(source_records)} 2026 exhibitors")
    with ThreadPoolExecutor(max_workers=16) as pool:
        records = list(pool.map(profile, source_records))
        records = list(pool.map(serper_enrich, records))
    records.sort(key=lambda item: item["exhibitor_name"].casefold())
    normalized = [{field: record.get(field, "") for field in FIELDS} for record in records]
    base = OUTPUT / f"{EVENT}_exhibitors"
    with base.with_suffix(".csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(normalized)
    base.with_suffix(".json").write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Domains found: {sum(bool(row['domain']) for row in normalized)}/{len(normalized)}")
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
