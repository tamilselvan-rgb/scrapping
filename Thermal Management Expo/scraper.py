"""Scrape named exhibitors and booth numbers from the supplied 2026 floor plan."""

from __future__ import annotations

import csv
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

BASE = "https://abeteefoameurope26.mapyourshow.com"
INDEX_URL = f"{BASE}/8_0/exhview/index.cfm"
BOOTH_URL = f"{BASE}/8_0/exhview/02/exh-remote-proxy.cfm?action=GetBoothByHall&hallID=A"
INFO_URL = f"{BASE}/8_0/exhview/02/exh-remote-proxy.cfm?action=getExhibitorInfo&exhID="
EVENT_NAME = "Thermal Management Expo"
YEAR = "2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
CSV_PATH = OUT / "THERMAL_MANAGEMENT_EXPO_2026_exhibitors.csv"
JSON_PATH = OUT / "THERMAL_MANAGEMENT_EXPO_2026_exhibitors.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Referer": INDEX_URL,
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json",
}
BLOCKED = (
    "mapyourshow.com", "abeteefoameurope26", "linkedin.com", "facebook.com",
    "instagram.com", "twitter.com", "x.com", "youtube.com", "wikipedia.org",
    "yellowpages.com", "yelp.com", "foam-expo-europe.com",
    "adhesivesandbondingexpo-europe.com", "thermalmanagementexpo-europe.com",
    "foam-expo.com", "rocketreach.co", "volza.com", "productiq.ulprospector.com",
    "recyclinginside.com", "marketscreener.com", "tube-tradefair.com",
    "find-and-update.company-information.service.gov.uk",
    "scribd.com", "adhesivesandbondingexpo.com", "film-expo.com",
)
COUNTRIES = {
    "germany": "Germany", "deutschland": "Germany", "france": "France",
    "frankreich": "France", "italy": "Italy", "italia": "Italy",
    "spain": "Spain", "netherlands": "Netherlands", "switzerland": "Switzerland",
    "austria": "Austria", "united states": "United States", "china": "China",
    "turkey": "Turkey", "belgium": "Belgium", "poland": "Poland",
}
TLD_COUNTRIES = {
    "de": "Germany", "fr": "France", "it": "Italy", "es": "Spain",
    "nl": "Netherlands", "ch": "Switzerland", "at": "Austria", "be": "Belgium",
    "pl": "Poland", "tr": "Turkey", "cn": "China", "uk": "United Kingdom",
    "co.uk": "United Kingdom", "us": "United States", "ca": "Canada",
}
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "booth_no", "name", "desc", "email", "phone", "address", "city",
    "linkedin_url", "profile_url", "source_year",
]


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\ufffd", "")).strip()


def normalize_domain(value: str) -> str:
    value = clean(value)
    if not value or value.casefold().startswith(("mailto:", "tel:")):
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", value, re.I):
        value = "https://" + value.lstrip("/")
    host = urlparse(value).netloc.lower().removeprefix("www.")
    return host if "." in host and not any(item in host for item in BLOCKED) else ""


def guess_country(location: str, domain: str, fallback: str = "") -> str:
    low = location.casefold()
    for key, country in COUNTRIES.items():
        if key in low:
            return country
    suffix = ".".join(domain.rsplit(".", 2)[-2:]) if "." in domain else ""
    return TLD_COUNTRIES.get(suffix, TLD_COUNTRIES.get(domain.rsplit(".", 1)[-1], fallback))


def valid_phone(value: str) -> bool:
    return len(re.sub(r"\D", "", value or "")) >= 7 and not re.search(
        r"\b\d{1,2}[.-]\d{1,2}[.-]\d{4}\b", value or ""
    )


def list_booths(session: requests.Session) -> list[dict[str, str]]:
    session.get(INDEX_URL, timeout=60).raise_for_status()
    response = session.get(BOOTH_URL, timeout=60)
    response.raise_for_status()
    payload = response.json()
    columns = payload["COLUMNS"]
    records = {}
    for values in payload["DATA"]:
        row = dict(zip(columns, values))
        if row.get("OBJECTTYPE") != "booth" or not clean(row.get("EXHNAME", "")):
            continue
        key = row.get("EXHID") or f"{row['EXHNAME']}|{row['BOOTHDISPLAY']}"
        records[key] = {
            "exhibitor_name": clean(row["EXHNAME"]),
            "booth_no": clean(row.get("BOOTHDISPLAY") or row.get("BOOTH", "")),
            "exh_id": clean(row.get("EXHID", "")),
        }
    print(f"Found {len(records)} named exhibitors on the supplied floor plan", flush=True)
    return list(records.values())


def fetch_profile(record: dict[str, str]) -> dict[str, str]:
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        session.get(INDEX_URL, timeout=60)
        response = session.get(INFO_URL + record["exh_id"], timeout=60)
        response.raise_for_status()
        data = response.json()
        item = data[0] if isinstance(data, list) and data else {}
    except (requests.RequestException, ValueError, IndexError):
        item = {}
    record["domain"] = normalize_domain(item.get("url", ""))
    record["mail"] = clean(item.get("email", ""))
    record["contact_number"] = clean(item.get("phone") or item.get("phone2", ""))
    if not valid_phone(record["contact_number"]):
        record["contact_number"] = ""
    record["address"] = clean(", ".join(filter(None, [
        item.get("address1", ""), item.get("address2", ""), item.get("address3", ""),
        item.get("zip", ""),
    ])))
    record["city"] = clean(item.get("city", ""))
    record["location"] = ", ".join(filter(None, [
        record["address"], record["city"], clean(item.get("state", "")),
    ]))
    record["country"] = clean(item.get("country", ""))
    record["desc"] = clean(item.get("description", ""))
    record["linkedin_url"] = clean(item.get("linkedin", ""))
    record["profile_url"] = f"{BASE}/8_0/exhview/index.cfm?exhID={record['exh_id']}"
    return record


def serper_enrich(record: dict[str, str], api_key: str) -> dict[str, str]:
    if record.get("domain") or not api_key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website {YEAR}', "num": 10},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return record
    knowledge = data.get("knowledgeGraph") or {}
    domain = normalize_domain(knowledge.get("website", ""))
    if not domain:
        for result in data.get("organic", []):
            domain = normalize_domain(result.get("link", ""))
            if domain:
                break
    record["domain"] = domain
    if not record.get("address") and knowledge.get("address"):
        record["location"] = record["address"] = clean(knowledge["address"])
    if not record.get("contact_number") and knowledge.get("phone"):
        record["contact_number"] = clean(knowledge["phone"])
    return record


def finalize(record: dict[str, str]) -> dict[str, str]:
    for key in ("domain", "mail", "contact_number", "location", "country", "booth_no",
                "desc", "address", "city", "linkedin_url", "profile_url"):
        record.setdefault(key, "")
    record["name"] = record["exhibitor_name"]
    record["email"] = record["mail"]
    record["phone"] = record["contact_number"]
    record["country"] = guess_country(record["location"], record["domain"], record["country"])
    record["source_year"] = YEAR
    record.pop("exh_id", None)
    return record


def scrape() -> list[dict[str, str]]:
    load_dotenv(ROOT.parent / ".env")
    session = requests.Session()
    session.headers.update(HEADERS)
    records = list_booths(session)
    with ThreadPoolExecutor(max_workers=16) as pool:
        records = list(pool.map(fetch_profile, records))
    missing = [row for row in records if not row.get("domain")]
    with ThreadPoolExecutor(max_workers=8) as pool:
        enriched = list(pool.map(lambda row: serper_enrich(row, os.getenv("SERPER_API_KEY", "")), missing))
    by_name = {row["exhibitor_name"].casefold(): row for row in enriched}
    records = [by_name.get(row["exhibitor_name"].casefold(), row) for row in records]
    return [finalize(row) for row in sorted(records, key=lambda row: row["exhibitor_name"].casefold())]


def write_outputs(records: list[dict[str, str]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "event": EVENT_NAME, "year": YEAR, "source": INDEX_URL, "total": len(records),
        "scraped_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "exhibitors": records,
    }
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)


if __name__ == "__main__":
    rows = scrape()
    write_outputs(rows)
    print(f"Saved {len(rows)} exhibitors")
