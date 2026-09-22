"""Scrape the Haus.Bau.Ambiente. 2026 exhibitor directory."""

from __future__ import annotations

import csv
import html
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

EVENT_NAME = "Haus.Bau.Ambiente."
EVENT_YEAR = "2026"
LIST_URL = "https://www.haus-bau-ambiente.de/aussteller/ausstellerliste/"
API_BASE = "https://messe-erfurt.profairs.de/api/admin/exhibitors/"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
CSV_PATH = OUT / "HAUS_BAU_AMBIENTE_2026_exhibitors.csv"
JSON_PATH = OUT / "HAUS_BAU_AMBIENTE_2026_exhibitors.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}
BLOCKED_DOMAINS = (
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com",
    "messe-erfurt.de", "profairs.de",
)
CSV_FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "description", "booth", "homepage", "profile_url", "source_year",
]


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def get_domain(value: str) -> str:
    value = clean(value)
    if not value:
        return ""
    value = value.replace("https.//", "https://")
    if not re.match(r"^[a-z][a-z0-9+.-]*://", value, re.I):
        value = "https://" + value
    host = urlparse(value).netloc.lower().removeprefix("www.")
    if "." not in host or any(blocked in host for blocked in BLOCKED_DOMAINS):
        return ""
    return host.split(":")[0]


def normalize_url(value: str) -> str:
    value = clean(value).replace("https.//", "https://")
    if not value:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", value, re.I):
        value = "https://" + value
    return value


def valid_email(value: str) -> str:
    value = clean(value).lower()
    if not value or "example." in value or "yourdomain" in value:
        return ""
    return value


def valid_phone(value: str) -> str:
    value = clean(value)
    digits = re.sub(r"\D", "", value)
    if not 8 <= len(digits) <= 15:
        return ""
    if re.search(r"\b(?:19|20)\d{2}\b", value):
        return ""
    if re.search(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", value):
        return ""
    return value


def country_for(record: dict[str, str]) -> str:
    if "eta.co.at" in record["domain"] or "Österreich" in record["location"]:
        return "Austria"
    return "Germany"


def api_params(page: int, limit: int = 100, exhibitor_id: int | None = None) -> dict[str, object]:
    params: dict[str, object] = {
        "fairid": 228, "language": "de_DE", "page": page, "limit": limit,
        "locked": "N", "widget": "true", "order": "marketing",
        "companyprofileRequired": "false", "logoRequired": "false",
        "getContacts": "true", "getOnlinemedia": "true", "getBranchen": "true",
        "getBooths": "true", "getKeywords": "true", "getAgendas": "false",
        "getHall": "true", "getBrands": "true", "getSolutionList": "true",
        "getProductGroup": "true", "getSolutions": "true",
        "getPressReleases": "true", "allowMissingMarketingAddress": "true",
        "noPublication": "true", "hasCanceled": "false",
        "branch": "", "solution_list": "", "product_group": "", "keyword": "",
        "brand": "", "halls": "", "locations": "", "countries": "",
        "fixedFilter": "", "search": "",
    }
    if exhibitor_id is not None:
        params.update({
            "exhibitorid": exhibitor_id, "getHighlights": "true",
            "getProductGroups": "true",
        })
        params.pop("page", None)
        params.pop("limit", None)
    return params


def fetch_exhibitors(session: requests.Session) -> list[dict]:
    response = session.get(API_BASE, params=api_params(0), timeout=45)
    response.raise_for_status()
    payload = response.json()
    exhibitors = payload.get("exhibitors", [])
    if not exhibitors:
        raise RuntimeError("The 2026 Profairs exhibitor API returned no records.")
    return exhibitors


def fetch_detail(session: requests.Session, exhibitor_id: int) -> dict:
    response = session.get(
        API_BASE, params=api_params(0, exhibitor_id=exhibitor_id), timeout=45
    )
    response.raise_for_status()
    exhibitors = response.json().get("exhibitors", [])
    return exhibitors[0] if exhibitors else {}


def serper_enrich(session: requests.Session, record: dict[str, str], api_key: str) -> None:
    if not api_key:
        return
    query = f'"{record["exhibitor_name"]}" official website {record["location"]}'
    try:
        response = session.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": 10},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return
    knowledge = data.get("knowledgeGraph") or {}
    if not record["domain"]:
        record["domain"] = get_domain(knowledge.get("website", ""))
        if not record["domain"]:
            for item in data.get("organic", []):
                candidate = get_domain(item.get("link", ""))
                if candidate:
                    record["domain"] = candidate
                    break
    if not record["contact_number"]:
        record["contact_number"] = valid_phone(knowledge.get("phone", ""))
    if not record["location"]:
        record["location"] = clean(knowledge.get("address", ""))


def website_contacts(session: requests.Session, record: dict[str, str]) -> None:
    if not record["domain"]:
        return
    base = normalize_url(record["homepage"]) or f"https://{record['domain']}/"
    paths = ("", "kontakt", "contact", "contact-us", "impressum", "about", "about-us")
    seen: set[str] = set()
    for path in paths:
        url = urljoin(base, path)
        if url in seen:
            continue
        seen.add(url)
        try:
            response = session.get(url, timeout=20, allow_redirects=True)
            if response.status_code >= 400:
                continue
        except requests.RequestException:
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        for anchor in soup.select('a[href^="mailto:"]'):
            email = valid_email(anchor.get("href", "")[7:].split("?", 1)[0])
            if email:
                record["mail"] = email
                break
        if not record["mail"]:
            for email in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", response.text):
                record["mail"] = valid_email(email)
                if record["mail"]:
                    break
        if not record["contact_number"]:
            tel = soup.select_one('a[href^="tel:"]')
            if tel:
                record["contact_number"] = valid_phone(
                    tel.get("href", "")[4:].split("?", 1)[0]
                )
            else:
                body = clean(soup.get_text(" ", strip=True))
                match = re.search(r"(?:\+?\d[\d\s()./-]{7,}\d)", body)
                if match:
                    record["contact_number"] = valid_phone(match.group(0))
        if record["mail"] and record["contact_number"]:
            break


def make_record(base: dict, detail: dict) -> dict[str, str]:
    data = detail or base
    address = data.get("marketing_address") or {}
    street = clean(data.get("street") or address.get("street"))
    additional = clean(data.get("additional_address") or address.get("additional_address"))
    postal = clean(data.get("postalcode") or address.get("postalcode"))
    city = clean(data.get("city") or address.get("city"))
    location = ", ".join(
        part for part in (street, additional, f"{postal} {city}".strip()) if part
    )
    homepage = clean(data.get("homepage") or address.get("homepage"))
    online = data.get("online_media") or {}
    description = clean(
        online.get("company_description")
        or online.get("description")
        or data.get("remarks")
    )
    booths = data.get("booths") or []
    booth = ", ".join(
        clean(item.get("boothnumber") or item.get("location"))
        for item in booths
        if clean(item.get("boothnumber") or item.get("location"))
    )
    record = {
        "exhibitor_name": clean(data.get("company") or base.get("company")),
        "domain": get_domain(homepage),
        "contact_number": "",
        "mail": "",
        "location": location,
        "country": "",
        "description": description,
        "booth": booth,
        "homepage": normalize_url(homepage),
        "profile_url": f"{LIST_URL}#/{data.get('id', base.get('id'))}",
        "source_year": EVENT_YEAR,
    }
    record["country"] = country_for(record)
    return record


def scrape() -> list[dict[str, str]]:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    api_key = os.getenv("SERPER_API_KEY", "")
    session = requests.Session()
    session.headers.update(HEADERS)
    bases = fetch_exhibitors(session)
    records: list[dict[str, str]] = []
    for index, base in enumerate(bases, 1):
        detail = fetch_detail(session, int(base["id"]))
        record = make_record(base, detail)
        if not record["domain"]:
            serper_enrich(session, record, api_key)
            record["country"] = country_for(record)
        website_contacts(session, record)
        records.append(record)
        print(f"{index}/{len(bases)} {record['exhibitor_name']}", flush=True)
    return sorted(records, key=lambda row: row["exhibitor_name"].casefold())


def write_outputs(records: list[dict[str, str]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "event": EVENT_NAME,
        "year": EVENT_YEAR,
        "source": LIST_URL,
        "scraped_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(records),
        "exhibitors": records,
    }
    JSON_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(records)


if __name__ == "__main__":
    started = time.time()
    rows = scrape()
    write_outputs(rows)
    print(f"Saved {len(rows)} exhibitors in {time.time() - started:.1f}s")
