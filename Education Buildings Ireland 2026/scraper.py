"""Scrape the official Education Buildings Ireland 2026 exhibitor directory."""

from __future__ import annotations

import csv
import html
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

EVENT_NAME = "Education Buildings Ireland"
EVENT_YEAR = "2026"
SOURCE_URL = "https://www.educationbuildings.ie/exhibitor-list"
BASE_URL = "https://www.educationbuildings.ie/"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
CSV_PATH = OUTPUT / "EDUCATION_BUILDINGS_IRELAND_2026_exhibitors.csv"
JSON_PATH = OUTPUT / "EDUCATION_BUILDINGS_IRELAND_2026_exhibitors.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/151.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}
BLOCKED_DOMAINS = {
    "educationbuildings.ie", "facebook.com", "instagram.com", "linkedin.com",
    "twitter.com", "x.com", "youtube.com", "tiktok.com", "wikipedia.org",
    "yellowpages.com", "yelp.com", "google.com", "stepconnect2.com",
}
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
    "booth_no", "name", "desc", "email", "phone", "address", "city",
    "linkedin_url", "profile_url", "source_year", "source_url",
]
COUNTRIES = {
    "ireland": "Ireland", "united kingdom": "United Kingdom", "england": "United Kingdom",
    "scotland": "United Kingdom", "wales": "United Kingdom", "germany": "Germany",
    "france": "France", "italy": "Italy", "spain": "Spain", "netherlands": "Netherlands",
    "belgium": "Belgium", "austria": "Austria", "switzerland": "Switzerland",
    "united states": "United States", "usa": "United States", "canada": "Canada",
    "australia": "Australia", "norway": "Norway", "sweden": "Sweden",
    "denmark": "Denmark", "finland": "Finland", "poland": "Poland",
}
TLD_COUNTRIES = {
    "ie": "Ireland", "uk": "United Kingdom", "co.uk": "United Kingdom",
    "de": "Germany", "fr": "France", "it": "Italy", "es": "Spain",
    "nl": "Netherlands", "be": "Belgium", "at": "Austria", "ch": "Switzerland",
    "us": "United States", "ca": "Canada", "au": "Australia", "no": "Norway",
    "se": "Sweden", "dk": "Denmark", "fi": "Finland", "pl": "Poland",
}
KNOWN_OFFICIALS = {
    "Hevac Ireland": "hevac.ie",
    "Visitorbooks": "visitorbooks.ie",
}
NAME_OVERRIDES = {
    "AtkinsR�alis Ireland": "AtkinsRéalis Ireland",
}


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "").replace("\xa0", " ")).strip()


def normalize_domain(value: str) -> str:
    value = clean(value).strip(" .;,")
    if not value:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", value, re.I):
        value = "https://" + value
    host = urlparse(value).netloc.lower().removeprefix("www.")
    if not host or "." not in host:
        return ""
    if any(host == blocked or host.endswith("." + blocked) for blocked in BLOCKED_DOMAINS):
        return ""
    return host


def extract_email(text: str) -> str:
    match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text or "")
    return match.group(0) if match else ""


def guess_country(location: str, domain: str) -> str:
    lower = location.casefold()
    for needle, country in COUNTRIES.items():
        if re.search(rf"\b{re.escape(needle)}\b", lower):
            return country
    parts = domain.rsplit(".", 2)
    suffix = ".".join(parts[-2:]) if len(parts) >= 2 else ""
    return TLD_COUNTRIES.get(suffix, TLD_COUNTRIES.get(parts[-1], ""))


def jsonld_address(soup: BeautifulSoup) -> str:
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            address = item.get("address")
            if isinstance(address, dict):
                parts = [
                    address.get("streetAddress", ""), address.get("addressLocality", ""),
                    address.get("addressRegion", ""), address.get("postalCode", ""),
                    address.get("addressCountry", ""),
                ]
                result = clean(", ".join(str(part) for part in parts if part))
                if result:
                    return result
            elif isinstance(address, str) and clean(address):
                return clean(address)
    return ""


def slugify(name: str) -> str:
    value = clean(name).casefold().replace("&", " and ")
    value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE)
    return re.sub(r"[-\s]+", "-", value).strip("-")


def parse_directory(page_html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(page_html, "html.parser")
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for card in soup.select("li.js-library-item"):
        content_id = clean(card.get("data-content-i-d", ""))
        title_node = card.select_one("h2")
        name = clean(title_node.get_text(" ", strip=True) if title_node else "")
        name = NAME_OVERRIDES.get(name, name.replace("\ufffd", "é"))
        if not content_id or not name or content_id in seen:
            continue
        seen.add(content_id)
        link = card.select_one("a.js-librarylink-entry[href]")
        path = link["href"] if link else f"exhibitors/{quote(slugify(name))}"
        stand_node = card.select_one(
            ".m-exhibitors-list__items__item__header__meta__stand"
        )
        records.append({
            "exhibitor_name": name,
            "profile_url": urljoin(BASE_URL, path),
            "booth_no": clean(stand_node.get_text(" ", strip=True) if stand_node else ""),
            "content_id": content_id,
        })
    if not records:
        raise RuntimeError("No 2026 exhibitors found on the official directory")
    return records


def parse_profile(record: dict[str, str], page_html: str) -> dict[str, str]:
    soup = BeautifulSoup(page_html, "html.parser")
    title = soup.select_one(".m-exhibitor-entry__item__header__infos__title")
    stand = soup.select_one(".m-exhibitor-entry__item__header__infos__stand")
    if title:
        record["exhibitor_name"] = clean(title.get_text(" ", strip=True))
        record["exhibitor_name"] = NAME_OVERRIDES.get(
            record["exhibitor_name"], record["exhibitor_name"].replace("\ufffd", "é")
        )
    if stand:
        stand_text = clean(stand.get_text(" ", strip=True))
        hall = re.search(r"Hall:\s*([^\s]+)", stand_text, re.I)
        booth = re.search(r"Stand:\s*(.+)$", stand_text, re.I)
        if hall and booth:
            record["booth_no"] = f"Hall {hall.group(1)} / {booth.group(1)}"
        elif booth:
            record["booth_no"] = booth.group(1)

    profile = {
        "exhibitor_name": record["exhibitor_name"],
        "domain": "",
        "contact_number": "",
        "mail": "",
        "location": "",
        "country": "",
        "booth_no": record.get("booth_no", ""),
        "name": record["exhibitor_name"],
        "desc": "",
        "email": "",
        "phone": "",
        "address": "",
        "city": "",
        "linkedin_url": "",
        "profile_url": record["profile_url"],
        "source_year": EVENT_YEAR,
        "source_url": SOURCE_URL,
    }
    entry = soup.select_one(".m-exhibitor-entry__item")
    description = entry.select_one(".m-exhibitor-entry__item__body__description") if entry else None
    if description:
        profile["desc"] = clean(description.get_text(" ", strip=True))
    for anchor in (entry.select("a[href]") if entry else []):
        href = clean(anchor.get("href", ""))
        lower = href.casefold()
        if lower.startswith("mailto:") and not profile["mail"]:
            profile["mail"] = href[7:].split("?", 1)[0]
        elif lower.startswith("tel:") and not profile["contact_number"]:
            profile["contact_number"] = href[4:]
        elif "linkedin.com/" in lower and "education-buildings" not in lower:
            profile["linkedin_url"] = href
        elif not profile["domain"]:
            profile["domain"] = normalize_domain(href)
    profile["email"] = profile["mail"]
    profile["phone"] = profile["contact_number"]
    return profile


def empty_profile(item: dict[str, str]) -> dict[str, str]:
    return {
        "exhibitor_name": item["exhibitor_name"], "domain": "", "contact_number": "",
        "mail": "", "location": "", "country": "", "booth_no": item.get("booth_no", ""),
        "name": item["exhibitor_name"], "desc": "", "email": "", "phone": "",
        "address": "", "city": "", "linkedin_url": "", "profile_url": item["profile_url"],
        "source_year": EVENT_YEAR, "source_url": SOURCE_URL,
    }


def serper_enrich(session: requests.Session, record: dict[str, str], api_key: str) -> None:
    if not api_key:
        return
    query = f'"{record["exhibitor_name"]}" official website {EVENT_YEAR} Ireland'
    try:
        response = session.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": 8},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return
    knowledge = data.get("knowledgeGraph") or {}
    if not record["domain"]:
        record["domain"] = normalize_domain(knowledge.get("website", ""))
        if not record["domain"]:
            for item in data.get("organic", []):
                candidate = normalize_domain(item.get("link", ""))
                if candidate:
                    record["domain"] = candidate
                    break
    if not record["location"]:
        record["location"] = clean(knowledge.get("address", ""))
    if not record["contact_number"]:
        record["contact_number"] = clean(knowledge.get("phone", ""))
    if not record["desc"]:
        record["desc"] = clean(knowledge.get("description", ""))
    if not record["mail"]:
        record["mail"] = extract_email(clean(knowledge.get("description", "")))
    if not record["linkedin_url"]:
        record["linkedin_url"] = next(
            (
                item.get("link", "").split("?", 1)[0]
                for item in data.get("organic", [])
                if "linkedin.com/" in item.get("link", "").lower()
            ),
            "",
        )


def website_enrich(session: requests.Session, record: dict[str, str]) -> None:
    if not record["domain"]:
        return
    base = f"https://{record['domain']}/"
    for suffix in ("", "contact", "contact-us", "about", "about-us"):
        try:
            response = session.get(urljoin(base, suffix), timeout=12)
            if response.status_code >= 400:
                continue
        except requests.RequestException:
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        body = clean(soup.get_text(" ", strip=True))
        if not record["mail"]:
            record["mail"] = extract_email(body)
        if not record["contact_number"]:
            tel = soup.select_one('a[href^="tel:"]')
            record["contact_number"] = clean(tel.get("href", "")[4:]) if tel else ""
        if not record["location"]:
            record["location"] = clean(soup.find("address").get_text(" ", strip=True)) if soup.find("address") else jsonld_address(soup)
        if not record["desc"]:
            meta = soup.select_one('meta[name="description"]')
            record["desc"] = clean(meta.get("content", "")) if meta else ""
        if record["mail"] and record["contact_number"] and record["location"]:
            break


def enrich_record(record: dict[str, str], api_key: str) -> dict[str, str]:
    session = requests.Session()
    session.headers.update(HEADERS)
    serper_enrich(session, record, api_key)
    if not record["domain"]:
        record["domain"] = KNOWN_OFFICIALS.get(record["exhibitor_name"], "")
    website_enrich(session, record)
    record["email"] = record["mail"]
    record["phone"] = record["contact_number"]
    record["address"] = record["location"]
    record["country"] = guess_country(record["location"], record["domain"])
    if not record["city"] and record["location"]:
        record["city"] = clean(record["location"].split(",")[-2] if "," in record["location"] else "")
    return record


def write_outputs(records: list[dict[str, str]]) -> None:
    records = sorted(records, key=lambda row: row["exhibitor_name"].casefold())
    OUTPUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "event": EVENT_NAME, "year": EVENT_YEAR, "source": SOURCE_URL,
        "scraped_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(records), "exhibitors": records,
    }
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)


def main() -> None:
    load_dotenv(ROOT.parent / ".env")
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        response = session.get(SOURCE_URL, timeout=45)
        response.raise_for_status()
        directory_html = response.content.decode("utf-8", errors="replace")
    except requests.RequestException:
        cached = ROOT.parent / "education_list.html"
        if not cached.exists():
            raise
        directory_html = cached.read_text(encoding="utf-8")
    items = parse_directory(directory_html)
    records: list[dict[str, str]] = []
    for index, item in enumerate(items, 1):
        try:
            profile_response = None
            for _ in range(3):
                candidate = session.get(
                    item["profile_url"],
                    headers={**HEADERS, "Referer": SOURCE_URL},
                    timeout=30,
                )
                if candidate.status_code != 405:
                    profile_response = candidate
                    break
            if profile_response is None:
                raise requests.HTTPError("Profile request returned 405")
            profile_response.raise_for_status()
            record = parse_profile(
                item, profile_response.content.decode("utf-8", errors="replace")
            )
        except requests.RequestException:
            record = empty_profile(item)
        records.append(record)
        print(f"{index}/{len(items)} {record['exhibitor_name']}", flush=True)

    api_key = os.getenv("SERPER_API_KEY", "")
    with ThreadPoolExecutor(max_workers=8) as executor:
        jobs = [executor.submit(enrich_record, record, api_key) for record in records]
        records = [job.result() for job in as_completed(jobs)]
    write_outputs(records)
    print(f"Saved {len(records)} exhibitors")
    print(CSV_PATH)
    print(JSON_PATH)


if __name__ == "__main__":
    main()
