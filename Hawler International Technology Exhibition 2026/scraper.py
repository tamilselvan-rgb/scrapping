import csv
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests


EVENT = "HAWLER_INTERNATIONAL_TECHNOLOGY_EXHIBITION_2026"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
BASE_URL = "https://hitex.tech"
LIST_URL = f"{BASE_URL}/api/public/organizations"
DETAIL_URL = f"{BASE_URL}/api/public/organizations/{{organization_id}}"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ExhibitorResearch/1.0)"}
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location",
    "country", "company_name", "booth", "description", "city", "linkedin_url",
]
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com", "hitex.tech",
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
            "ltd", "llc", "inc", "co", "company", "group", "technology",
            "technologies", "limited",
        }
    }
    return domain if host and tokens and any(
        token in host or host in token for token in tokens
    ) else ""


def fetch(method, url, **kwargs):
    for attempt in range(4):
        try:
            response = requests.request(method, url, headers=HEADERS, timeout=60, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


def api_page(page):
    response = fetch(
        "GET", LIST_URL,
        params={"type": "exhibitor", "is_active": "true", "page": page, "limit": 100},
    )
    return response.json()["data"]


def listing():
    first = api_page(1)
    records = first["records"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for data in pool.map(api_page, range(2, first["meta"]["total_pages"] + 1)):
            records.extend(data["records"])
    return [
        record for record in records
        if 2026 in (record.get("years") or [])
    ]


def detail(record):
    try:
        data = fetch("GET", DETAIL_URL.format(organization_id=record["id"])).json()["data"]
    except (requests.RequestException, KeyError, TypeError):
        data = record
    name = clean((data.get("name") or {}).get("en") or (record.get("name") or {}).get("en"))
    country = clean(((data.get("country") or {}).get("name") or {}).get("en"))
    website = domain_url(data.get("website_url") or record.get("website_url"))
    return {
        "exhibitor_name": name,
        "domain": matching_domain(name, website),
        "contact_number": "",
        "mail": "",
        "location": "",
        "country": country,
        "company_name": name,
        "booth": clean(data.get("booth_number") or record.get("booth_number")),
        "description": clean(((data.get("description") or {}).get("en"))),
        "city": "Erbil",
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
    key = serper_key()
    if not key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={
                "q": f'"{record["exhibitor_name"]}" official website {record["location"] or "Iraq"}',
                "gl": "iq", "hl": "en", "num": 10,
            },
            timeout=45,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph") or {}
        candidates = [graph.get("website", "")]
        candidates.extend(item.get("link", "") for item in data.get("organic", []))
        if not record["domain"]:
            for candidate in candidates:
                domain = matching_domain(record["exhibitor_name"], domain_url(candidate))
                if domain:
                    record["domain"] = domain
                    break
        if not record["contact_number"]:
            record["contact_number"] = clean(graph.get("phone"))
        if not record["location"]:
            record["location"] = clean(graph.get("address"))
        if not record["mail"]:
            record["mail"] = clean(graph.get("email")).lower()
    except requests.RequestException:
        pass
    return record


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source_records = listing()
    print(f"Found {len(source_records)} exhibitors marked for 2026")
    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(detail, source_records))
    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(serper_enrich, records))
    unique = {}
    for record in records:
        unique.setdefault(record["exhibitor_name"].casefold(), record)
    records = sorted(unique.values(), key=lambda item: item["exhibitor_name"].casefold())
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
