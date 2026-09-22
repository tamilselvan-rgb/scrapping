"""Scrape the Intermodal Europe 2026 exhibitor directory."""

from __future__ import annotations

import csv
import html
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from tldextract import extract as extract_domain

EVENT_NAME = "Intermodal Europe"
EVENT_YEAR = "2026"
LIST_URL = "https://www.intermodal-events.com/whats-on/exhibitor-list/"
WIDGET_URL = (
    "https://app.intermodal-events.com/widget/event/"
    "intermodal-europe-2026/exhibitors/RXZlbnRWaWV3XzEyNzMzNjg"
)
GRAPHQL_URL = "https://api.swapcard.com/graphql"
EVENT_ID = "RXZlbnRfNDQzMTkyMA=="
VIEW_ID = "RXZlbnRWaWV3XzEyNzMzNjg="
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
CSV_PATH = OUT / "INTERMODAL_EUROPE_2026_exhibitors.csv"
JSON_PATH = OUT / "INTERMODAL_EUROPE_2026_exhibitors.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
BLOCKED_DOMAINS = (
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com",
    "swapcard.com", "intermodal-events.com", "10times.com", "aeroleads.com",
    "alibaba.com", "all-forward.com", "archiexpo.com", "certipedia.com",
    "cuddably.co.za", "company-information.service.gov.uk", "companieshouse.sg",
    "container-xchange.com", "dnb.com", "discovery.patsnap.com", "eximpedia.app",
    "energy-oil-gas.com", "in.bold.pro", "in.kompass.com", "ipqwery.com",
    "jctrans.com", "justice.gov", "ltddir.com", "panjiva.com", "prnewswire.com",
    "sourcefromontario.com", "ssauk.com", "ssutility.com", "trustpilot.com",
    "tradewheel.com", "ukrailwaypics.smugmug.com", "husumwind.com",
    "intermodal-asia.com", "geofence-review.bic-code.org",
    "scribd.com", "leadiq.com", "developmentaid.org", "games.crossfit.com",
    "pier2pier.com", "kompass.com", "hamburg-logistik.net", "zoominfo.com",
    "technavio.com", "diagnostics.roche.com", "breakbulk.com", "tradeindata.com",
    "trackipi.com", "k-knowledge.kr", "emagecompany.com", "multivu.com",
    "tracecontainer.com", "baidu.com", "rocketreach.co", "rdcprg.cz",
    "cnverify.com", "5sln.com", "intermodal.org", "capps.com", "emis.com",
    "venturelab.swiss", "procurement.ppg.com", "mcicontainers.com",
    "balticon24.com", "international-tank-container.org",
)
CSV_FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "description", "booth", "homepage", "profile_url", "source_year",
]


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


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


def get_domain(value: str) -> str:
    value = clean(value)
    if not value:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", value, re.I):
        value = "https://" + value
    host = urlparse(value).netloc.lower().removeprefix("www.")
    if "." not in host or any(blocked in host for blocked in BLOCKED_DOMAINS):
        return ""
    host = host.split(":")[0]
    extracted = extract_domain(host)
    return (
        extracted.top_domain_under_public_suffix
        or extracted.registered_domain
        or host
    )


def suspect_domain(value: str) -> bool:
    return not value or any(blocked in value for blocked in BLOCKED_DOMAINS)


def normalize_url(value: str) -> str:
    value = clean(value)
    if not value:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", value, re.I):
        return "https://" + value
    return value


def graphql(session: requests.Session, query: str, variables: dict) -> dict:
    response = session.post(
        GRAPHQL_URL,
        json={"query": query, "variables": variables},
        headers={**HEADERS, "Content-Type": "application/json",
                 "Origin": "https://app.intermodal-events.com"},
        timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(payload["errors"][0].get("message", "GraphQL error"))
    return payload.get("data", {})


LIST_QUERY = """
query ExhibitorList($viewId: ID!, $eventId: ID!, $after: String) {
  view: Core_eventExhibitorListView(viewId: $viewId) {
    exhibitors(cursor: { first: 50, after: $after }) {
      nodes {
        id: _id
        name
        websiteUrl
        email
        description
        address { street city zipCode state country place }
        withEvent(eventId: $eventId) { booth }
      }
      pageInfo { hasNextPage endCursor }
      totalCount
    }
  }
}
"""
DETAIL_QUERY = """
query ExhibitorDetail($eventId: ID!, $exhibitorId: ID!) {
  exhibitors: Core_exhibitors(
    _eventId: $eventId
    first: 1
    filters: { exhibitorIds: [$exhibitorId] }
  ) {
    nodes {
      id: _id
      name
      websiteUrl
      email
      description
      htmlDescription
      address { street city zipCode state country place }
      withEvent(eventId: $eventId) { booth }
    }
  }
}
"""


def fetch_list(session: requests.Session) -> list[dict]:
    records: list[dict] = []
    after = None
    while True:
        data = graphql(
            session, LIST_QUERY,
            {"viewId": VIEW_ID, "eventId": EVENT_ID, "after": after},
        )
        connection = data["view"]["exhibitors"]
        records.extend(connection["nodes"])
        if not connection["pageInfo"]["hasNextPage"]:
            expected = connection["totalCount"]
            if len(records) != expected:
                raise RuntimeError(f"Expected {expected} records, found {len(records)}")
            return records
        after = connection["pageInfo"]["endCursor"]


def fetch_detail(session: requests.Session, exhibitor_id: str) -> dict:
    try:
        data = graphql(
            session, DETAIL_QUERY,
            {"eventId": EVENT_ID, "exhibitorId": exhibitor_id},
        )
        return (data.get("exhibitors") or {}).get("nodes", [{}])[0]
    except (requests.RequestException, RuntimeError, KeyError):
        return {}


def address_text(address: dict | None) -> str:
    address = address or {}
    return ", ".join(
        clean(address.get(key))
        for key in ("street", "place", "zipCode", "city", "state", "country")
        if clean(address.get(key))
    )


def country_from(location: str, domain: str) -> str:
    text = location.casefold()
    countries = {
        "netherlands": "Netherlands", "nederland": "Netherlands",
        "germany": "Germany", "deutschland": "Germany",
        "united kingdom": "United Kingdom", "uk": "United Kingdom",
        "belgium": "Belgium", "france": "France", "spain": "Spain",
        "italy": "Italy", "denmark": "Denmark", "norway": "Norway",
        "sweden": "Sweden", "finland": "Finland", "poland": "Poland",
        "china": "China", "india": "India", "united states": "United States",
        "usa": "United States", "canada": "Canada", "austria": "Austria",
        "switzerland": "Switzerland", "portugal": "Portugal",
    }
    for needle, country in countries.items():
        if re.search(rf"\b{re.escape(needle)}\b", text):
            return country
    tld = domain.rsplit(".", 1)[-1] if "." in domain else ""
    return {
        "nl": "Netherlands", "de": "Germany", "uk": "United Kingdom",
        "be": "Belgium", "fr": "France", "dk": "Denmark", "no": "Norway",
        "se": "Sweden", "fi": "Finland", "pl": "Poland", "cn": "China",
        "in": "India", "us": "United States", "ca": "Canada",
        "at": "Austria", "ch": "Switzerland",
    }.get(tld, "")


def serper_enrich(
    session: requests.Session, record: dict[str, str], api_key: str
) -> None:
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
    if not record["location"]:
        record["location"] = clean(knowledge.get("address", ""))
    if not record["contact_number"]:
        record["contact_number"] = valid_phone(knowledge.get("phone", ""))
    if not record["mail"]:
        candidates = [knowledge.get("email", "")]
        candidates.extend(
            f"{item.get('title', '')} {item.get('snippet', '')}"
            for item in data.get("organic", [])
        )
        for candidate in candidates:
            match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", candidate)
            if match:
                record["mail"] = valid_email(match.group(0))
                if record["mail"]:
                    break


def website_contacts(session: requests.Session, record: dict[str, str]) -> None:
    if not record["domain"]:
        return
    base = normalize_url(record["homepage"]) or f"https://{record['domain']}/"
    seen: set[str] = set()
    for path in ("", "contact", "contact-us", "about", "about-us", "imprint", "impressum"):
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
        if not record["mail"]:
            for anchor in soup.select('a[href^="mailto:"]'):
                email = valid_email(anchor.get("href", "")[7:].split("?", 1)[0])
                if email:
                    record["mail"] = email
                    break
        if not record["mail"]:
            visible_text = clean(soup.get_text(" ", strip=True))
            for email in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", visible_text):
                record["mail"] = valid_email(email)
                if record["mail"]:
                    break
        if not record["contact_number"]:
            tel = soup.select_one('a[href^="tel:"]')
            if tel:
                record["contact_number"] = valid_phone(
                    tel.get("href", "")[5:].split("?", 1)[0]
                )
            if not record["contact_number"]:
                body = clean(soup.get_text(" ", strip=True))
                match = re.search(r"(?:\+?\d[\d\s()./+ -]{7,}\d)", body)
                if match:
                    record["contact_number"] = valid_phone(match.group(0))
        if not record["location"]:
            address = soup.find("address")
            if address:
                record["location"] = clean(address.get_text(" ", strip=True))
        if not record["location"]:
            for script in soup.select('script[type="application/ld+json"]'):
                try:
                    payload = json.loads(script.get_text())
                except (TypeError, json.JSONDecodeError):
                    continue
                candidates = payload if isinstance(payload, list) else [payload]
                for item in candidates:
                    address = item.get("address") if isinstance(item, dict) else None
                    if isinstance(address, dict):
                        record["location"] = ", ".join(
                            clean(address.get(key))
                            for key in (
                                "streetAddress", "postalCode", "addressLocality",
                                "addressRegion", "addressCountry",
                            )
                            if clean(address.get(key))
                        )
                        if record["location"]:
                            break
                if record["location"]:
                    break
        if record["mail"] and record["contact_number"] and record["location"]:
            break


def make_record(base: dict, detail: dict) -> dict[str, str]:
    data = {**base, **{k: v for k, v in detail.items() if v is not None}}
    location = address_text(data.get("address"))
    booth = clean((data.get("withEvent") or {}).get("booth"))
    exhibitor_id = data["id"]
    return {
        "exhibitor_name": clean(data.get("name")),
        "domain": get_domain(data.get("websiteUrl", "")),
        "contact_number": "",
        "mail": valid_email(data.get("email", "")),
        "location": location,
        "country": "",
        "description": clean(data.get("description") or data.get("htmlDescription")),
        "booth": booth,
        "homepage": normalize_url(data.get("websiteUrl", "")),
        "profile_url": (
            "https://app.intermodal-events.com/widget/event/"
            f"intermodal-europe-2026/exhibitor/{exhibitor_id}"
        ),
        "source_year": EVENT_YEAR,
    }


def enrich_one(base: dict, detail: dict, api_key: str) -> dict[str, str]:
    record = make_record(base, detail)
    if suspect_domain(record["domain"]):
        record["domain"] = ""
        record["homepage"] = ""
    with requests.Session() as session:
        session.headers.update(HEADERS)
        if not record["domain"] or not record["location"] or not record["contact_number"]:
            serper_enrich(session, record, api_key)
        website_contacts(session, record)
        if not record["domain"] or not record["mail"] or not record["contact_number"]:
            serper_enrich(session, record, api_key)
    record["country"] = country_from(record["location"], record["domain"])
    return record


def scrape() -> list[dict[str, str]]:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    api_key = os.getenv("SERPER_API_KEY", "")
    session = requests.Session()
    session.headers.update(HEADERS)
    bases = fetch_list(session)
    details: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = {pool.submit(fetch_detail, session, item["id"]): item["id"] for item in bases}
        for index, job in enumerate(as_completed(jobs), 1):
            details[jobs[job]] = job.result()
            print(f"Profile details {index}/{len(bases)}", flush=True)
    records: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = {
            pool.submit(enrich_one, base, details.get(base["id"], {}), api_key): base["name"]
            for base in bases
        }
        for index, job in enumerate(as_completed(jobs), 1):
            record = job.result()
            records.append(record)
            print(f"Enriched {index}/{len(bases)} {record['exhibitor_name']}", flush=True)
    return sorted(records, key=lambda row: row["exhibitor_name"].casefold())


def write_outputs(records: list[dict[str, str]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "event": EVENT_NAME,
        "year": EVENT_YEAR,
        "source": LIST_URL,
        "widget_source": WIDGET_URL,
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
