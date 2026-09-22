"""Scrape the 2026 Aluminium exhibitor directory linked by the user."""

from __future__ import annotations

import csv
import html
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse

import requests
from dotenv import load_dotenv

EVENT_NAME = "Aluminium Arabia"
EVENT_YEAR = "2026"
SOURCE_URL = "https://www.aluminium-exhibition.com/germany/en-gb/exhibitor-directory.html"
DETAIL_BASE = "https://www.aluminium-exhibition.com/germany/en-gb/exhibitor-directory/exhibitor-details."
ALGOLIA_APP_ID = "XD0U5M6Y4R"
ALGOLIA_API_KEY = "d5cd7d4ec26134ff4a34d736a7f9ad47"
ALGOLIA_INDEX = "evt-0661a590-b09e-4155-9a86-835037084072-index"
EVENT_EDITION_ID = "eve-975e971e-6a3f-449d-b85a-a52ad4b63223"
CLIENT_ID = "uhQVcmxLwXAjVtVpTvoerERiZSsNz0om"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
CSV_PATH = OUTPUT / "ALUMINIUM_ARABIA_2026_exhibitors.csv"
JSON_PATH = OUTPUT / "ALUMINIUM_ARABIA_2026_exhibitors.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept-Language": "en-GB,en;q=0.9",
}
BLOCKED = {
    "aluminium-exhibition.com", "linkedin.com", "facebook.com", "instagram.com",
    "twitter.com", "x.com", "youtube.com", "wikipedia.org", "yellowpages.com",
    "yelp.com", "google.com",
}
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "booth_no", "name", "desc", "email", "phone", "address", "city",
    "linkedin_url", "profile_url", "source_year", "source_url",
]


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def normalize_domain(value: object) -> str:
    raw = clean(value).strip("<>")
    if not raw:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.I):
        raw = "https://" + raw
    host = urlparse(raw).netloc.lower().removeprefix("www.")
    if "." not in host:
        return ""
    if any(host == item or host.endswith("." + item) for item in BLOCKED):
        return ""
    return host


def country_name(country: str, code: str) -> str:
    if country:
        return country
    return {
        "ITA": "Italy", "DEU": "Germany", "USA": "United States",
        "GBR": "United Kingdom", "CHN": "China", "TUR": "Türkiye",
        "NLD": "Netherlands", "FRA": "France", "ESP": "Spain",
        "AUT": "Austria", "BEL": "Belgium", "CHE": "Switzerland",
    }.get(code.upper(), "")


def profile_url(name: str, organisation_id: str) -> str:
    slug = quote(name.casefold(), safe=" .-_")
    return f"{DETAIL_BASE}{slug}.{organisation_id}.html"


def empty_record(hit: dict) -> dict[str, str]:
    name = clean(hit.get("exhibitorName") or hit.get("companyName"))
    return {
        "exhibitor_name": name,
        "domain": normalize_domain(hit.get("website")),
        "contact_number": clean(hit.get("phone")),
        "mail": clean(hit.get("email")),
        "location": "",
        "country": clean(hit.get("countryName")),
        "booth_no": "",
        "name": name,
        "desc": clean(hit.get("exhibitorDescription")),
        "email": clean(hit.get("email")),
        "phone": clean(hit.get("phone")),
        "address": "",
        "city": "",
        "linkedin_url": "",
        "profile_url": profile_url(name, clean(hit.get("organisationGuid"))),
        "source_year": EVENT_YEAR,
        "source_url": SOURCE_URL,
        "_organisation_id": clean(hit.get("organisationGuid")),
    }


def fetch_index() -> list[dict]:
    endpoint = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/{ALGOLIA_INDEX}/query"
    headers = {
        "X-Algolia-Application-Id": ALGOLIA_APP_ID,
        "X-Algolia-API-Key": ALGOLIA_API_KEY,
        "Content-Type": "application/json",
    }
    hits = []
    for page in range(16):
        params = urlencode({"hitsPerPage": 1000, "page": page})
        response = requests.post(endpoint, headers=headers, json={"params": params}, timeout=45)
        response.raise_for_status()
        hits.extend(
            hit for hit in response.json().get("hits", [])
            if hit.get("eventEditionId") == EVENT_EDITION_ID and hit.get("locale") == "en-gb"
        )
        if len(hits) >= 164:
            break
    if len(hits) != 164:
        raise RuntimeError(f"Expected 164 Aluminium 2026 exhibitors, found {len(hits)}")
    return hits


def enrich_profile(record: dict[str, str], session: requests.Session) -> dict[str, str]:
    org_id = record["_organisation_id"]
    query = f"""
    {{
      exhibitingOrganisation(
        eventEditionId: "{EVENT_EDITION_ID}",
        organisationId: "{org_id}"
      ) {{
        organisationId companyName contactEmail website phone
        socialMedia {{ url name }}
        multilingual {{
          locale displayName description addressLine1 addressLine2
          stateProvince city countryCode postcode country
        }}
        stands {{ name }}
      }}
    }}
    """
    response = session.post(
        "https://api.reedexpo.com/graphql",
        headers={"x-clientid": CLIENT_ID, "Content-Type": "application/json"},
        json={"query": query},
        timeout=45,
    )
    response.raise_for_status()
    data = response.json().get("data", {}).get("exhibitingOrganisation") or {}
    multilingual = next(
        (item for item in data.get("multilingual", []) if item.get("locale") == "en-gb"),
        data.get("multilingual", [{}])[0] if data.get("multilingual") else {},
    )
    record["exhibitor_name"] = record["name"] = clean(
        multilingual.get("displayName") or data.get("companyName") or record["name"]
    )
    record["domain"] = normalize_domain(data.get("website")) or record["domain"]
    record["mail"] = clean(data.get("contactEmail")) or record["mail"]
    record["contact_number"] = clean(data.get("phone")) or record["contact_number"]
    record["desc"] = clean(multilingual.get("description")) or record["desc"]
    record["booth_no"] = ", ".join(
        clean(stand.get("name")) for stand in data.get("stands", []) if clean(stand.get("name"))
    )
    parts = [
        clean(multilingual.get("addressLine1")),
        clean(multilingual.get("addressLine2")),
        clean(multilingual.get("stateProvince")),
        clean(multilingual.get("postcode")),
    ]
    record["address"] = ", ".join(part for part in parts if part)
    record["city"] = clean(multilingual.get("city"))
    record["country"] = country_name(
        clean(multilingual.get("country")), clean(multilingual.get("countryCode"))
    ) or record["country"]
    record["location"] = ", ".join(
        part for part in (record["address"], record["city"], record["country"]) if part
    )
    record["linkedin_url"] = next(
        (
            clean(item.get("url")).split("?")[0]
            for item in data.get("socialMedia", [])
            if "linkedin.com/" in clean(item.get("url")).lower()
        ),
        record["linkedin_url"],
    )
    record["email"] = record["mail"]
    record["phone"] = record["contact_number"]
    return record


def serper_fallback(record: dict[str, str], api_key: str, session: requests.Session) -> None:
    if record["domain"] or not api_key:
        return
    try:
        response = session.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website {EVENT_YEAR}', "num": 8},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return
    knowledge = data.get("knowledgeGraph") or {}
    record["domain"] = normalize_domain(knowledge.get("website"))
    if not record["domain"]:
        for result in data.get("organic", []):
            candidate = normalize_domain(result.get("link"))
            if candidate:
                record["domain"] = candidate
                break
    if not record["desc"]:
        record["desc"] = clean(knowledge.get("description"))
    if not record["linkedin_url"]:
        record["linkedin_url"] = next(
            (clean(item.get("link")).split("?")[0] for item in data.get("organic", [])
             if "linkedin.com/" in clean(item.get("link")).lower()),
            "",
        )


def scrape() -> list[dict[str, str]]:
    load_dotenv(ROOT.parent / ".env")
    hits = fetch_index()
    records = [empty_record(hit) for hit in hits]

    def enrich(record: dict[str, str]) -> dict[str, str]:
        with requests.Session() as session:
            session.headers.update(HEADERS)
            return enrich_profile(record, session)

    with ThreadPoolExecutor(max_workers=12) as executor:
        records = [job.result() for job in as_completed([executor.submit(enrich, item) for item in records])]

    api_key = os.getenv("SERPER_API_KEY", "")
    with ThreadPoolExecutor(max_workers=8) as executor:
        jobs = []
        for record in records:
            if not record["domain"]:
                session = requests.Session()
                session.headers.update(HEADERS)
                jobs.append(executor.submit(serper_fallback, record, api_key, session))
        for job in jobs:
            job.result()
    return sorted(records, key=lambda item: item["exhibitor_name"].casefold())


def write_outputs(records: list[dict[str, str]]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "event": EVENT_NAME, "year": EVENT_YEAR, "source": SOURCE_URL,
        "scraped_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(records), "exhibitors": records,
    }
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


if __name__ == "__main__":
    rows = scrape()
    write_outputs(rows)
    print(f"Saved {len(rows)} exhibitors")
    print(CSV_PATH)
    print(JSON_PATH)
