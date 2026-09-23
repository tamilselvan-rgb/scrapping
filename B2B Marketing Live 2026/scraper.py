import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests


EVENT = "B2B_MARKETING_LIVE"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LIST_URL = "https://www.b2bmarketingexpo.co.uk/exhibitors-2026#/exhibitors"
CAMPAIGN = "b2b-marketing-live-london-2026"
ORGANISATION = "roar-b2b"
MODULE_ID = "exhibitors-2026"
API_BASE = (
    f"https://{ORGANISATION}.control.buzz/campaign/{CAMPAIGN}"
    f"/web-module/{MODULE_ID}"
)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ExhibitorResearch/1.0)"}
BLOCKED = {
    "facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com",
    "linkedin.com", "wikipedia.org", "yellowpages.com", "yelp.com",
    "google.com", "10times.com", "kompass.com", "b2bmarketingexpo.co.uk",
}
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location",
    "country", "booth_no", "desc", "linkedin_url", "city", "profile_url",
    "event_date", "event_venue", "source_url", "source_year",
]


def clean(value):
    value = html.unescape(str(value or "")).replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def root_domain(value):
    if not value:
        return ""
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value.strip()
    host = (urlparse(value).hostname or "").lower().removeprefix("www.")
    if not host or any(host == item or host.endswith("." + item) for item in BLOCKED):
        return ""
    return host


def country_name(value):
    names = {
        "GB": "United Kingdom", "UK": "United Kingdom",
        "US": "United States", "USA": "United States",
        "CA": "Canada", "AU": "Australia", "DE": "Germany",
        "FR": "France", "NL": "Netherlands", "IE": "Ireland",
        "EE": "Estonia",
    }
    value = clean(value)
    return names.get(value.upper(), value)


def valid_phone(value):
    digits = re.sub(r"\D", "", clean(value))
    return 7 <= len(digits) <= 16


def serper_key():
    env = ROOT.parent / ".env"
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"\'')
    return ""


def plausible_domain(name, domain):
    if not domain:
        return False
    generic = {
        "company", "group", "limited", "ltd", "the", "and", "marketing",
        "live", "b2b", "uk", "solutions", "services", "digital",
    }
    tokens = [
        token for token in re.findall(r"[a-z0-9]+", name.lower())
        if len(token) >= 4 and token not in generic
    ]
    return bool(tokens) and any(token in domain for token in tokens)


def address_fields(address):
    if not isinstance(address, dict):
        return "", "", ""
    location = address.get("full_address") or ", ".join(
        clean(value) for value in (
            address.get("line_1"), address.get("line_2"),
            address.get("line_3"), address.get("city"),
            address.get("county"), address.get("postcode"),
            country_name(address.get("country_name") or address.get("country")),
        ) if clean(value)
    )
    return clean(location), clean(address.get("city", "")), country_name(
        address.get("country_name") or address.get("country", "")
    )


def listing():
    settings = requests.get(
        f"{API_BASE}/settings", headers={**HEADERS, "Accept": "application/json"},
        timeout=60,
    )
    settings.raise_for_status()
    config = settings.json()
    algolia = config["algolia"]
    index = algolia["indexes"]["exhibitors"]
    response = requests.post(
        f"https://{algolia['application_id']}-dsn.algolia.net/1/indexes/{index}/query",
        headers={
            "X-Algolia-Application-Id": algolia["application_id"],
            "X-Algolia-API-Key": algolia["search_only_api_key"],
            "Content-Type": "application/json",
        },
        json={"params": "query=&hitsPerPage=100"},
        timeout=60,
    )
    response.raise_for_status()
    hits = response.json().get("hits", [])
    if not hits:
        raise RuntimeError("No 2026 B2B Marketing Live exhibitors found")
    records = []
    for hit in hits:
        identifier = hit.get("identifier", "")
        records.append({
            "exhibitor_name": clean(hit.get("name", "")),
            "domain": "",
            "contact_number": "",
            "mail": "",
            "location": "",
            "country": "",
            "booth_no": clean(", ".join(hit.get("stands") or [])),
            "desc": clean(hit.get("biography", "")),
            "linkedin_url": "",
            "city": "",
            "profile_url": f"{LIST_URL.split('#')[0]}#/exhibitors/{identifier}",
            "identifier": identifier,
            "event_date": "2026-11-18 to 2026-11-19",
            "event_venue": "Excel London, London, United Kingdom",
            "source_url": LIST_URL,
            "source_year": "2026",
        })
    return records


def profile(record):
    try:
        response = requests.get(
            f"{API_BASE}/exhibitors/{record['identifier']}",
            headers={**HEADERS, "Accept": "application/json"},
            timeout=45,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return record
    record["exhibitor_name"] = clean(data.get("name") or record["exhibitor_name"])
    record["domain"] = root_domain(data.get("website", ""))
    record["mail"] = clean(data.get("website_email", "")).lower()
    record["booth_no"] = clean(", ".join(data.get("stands") or [])) or record["booth_no"]
    record["desc"] = clean(data.get("biography") or data.get("details") or record["desc"])
    addresses = data.get("addresses") or []
    if addresses:
        record["location"], record["city"], record["country"] = address_fields(addresses[0])
    phones = data.get("phones") or []
    if phones:
        number = phones[0].get("number", "") if isinstance(phones[0], dict) else phones[0]
        if valid_phone(number):
            record["contact_number"] = clean(number)
    social = data.get("social_links") or []
    social = social.values() if isinstance(social, dict) else social
    for item in social:
        if isinstance(item, dict) and "linkedin.com/" in item.get("url", ""):
            record["linkedin_url"] = item["url"]
            break
    return record


def serper_enrich(record):
    if record["domain"]:
        return record
    key = serper_key()
    if not key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={
                "q": f'{record["exhibitor_name"]} official website 2026 UK'
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph", {})
        candidate = root_domain(graph.get("website", ""))
        if plausible_domain(record["exhibitor_name"], candidate):
            record["domain"] = candidate
        if not record["domain"]:
            for item in data.get("organic", []):
                candidate = root_domain(item.get("link", ""))
                if plausible_domain(record["exhibitor_name"], candidate):
                    record["domain"] = candidate
                    if not record["desc"]:
                        record["desc"] = clean(item.get("snippet", ""))
                    break
        if not record["contact_number"] and valid_phone(graph.get("phone", "")):
            record["contact_number"] = clean(graph["phone"])
        if not record["location"]:
            record["location"] = clean(graph.get("address", ""))
        if not record["desc"]:
            record["desc"] = clean(graph.get("description", ""))
        if not record["linkedin_url"]:
            for item in data.get("organic", []):
                link = item.get("link", "")
                if "linkedin.com/company/" in link:
                    record["linkedin_url"] = link
                    break
    except requests.RequestException:
        pass
    return record


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = listing()
    with ThreadPoolExecutor(max_workers=16) as pool:
        records = list(pool.map(profile, records))
        records = list(pool.map(serper_enrich, records))
    records.sort(key=lambda item: item["exhibitor_name"].casefold())
    for record in records:
        record.pop("identifier", None)
    base = OUT / f"{EVENT}_2026_exhibitors"
    with base.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    base.with_suffix(".json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Exported {len(records)} 2026 B2B Marketing Live exhibitors")
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
