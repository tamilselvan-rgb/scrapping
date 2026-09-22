from __future__ import annotations

import csv
import html
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
import tldextract
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://www.domotex.de"
SEARCH_URL = f"{BASE}/de/suche/?category=ep"
EVENT = "DOMOTEX South East Asia, R+T South East Asia, and Future Build Asia"
ROOT = Path(__file__).parent
OUT = ROOT / "output"
OUT.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}
TIMEOUT = 45
BLOCKED_DOMAINS = {
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com",
    "10times.com", "swapcard.com", "domotex.de", "domotexasiachinafloor.com",
}
COUNTRIES = {
    "belgien": "Belgium", "belgium": "Belgium", "be": "Belgium",
    "deutschland": "Germany", "germany": "Germany", "de": "Germany",
    "italien": "Italy", "italy": "Italy", "it": "Italy",
    "frankreich": "France", "france": "France", "fr": "France",
    "niederlande": "Netherlands", "netherlands": "Netherlands", "nl": "Netherlands",
    "österreich": "Austria", "austria": "Austria", "at": "Austria",
    "spanien": "Spain", "spain": "Spain", "es": "Spain",
    "portugal": "Portugal", "pt": "Portugal", "schweiz": "Switzerland",
    "switzerland": "Switzerland", "ch": "Switzerland", "polen": "Poland",
    "poland": "Poland", "pl": "Poland", "indien": "India", "india": "India",
    "in": "India", "china": "China", "cn": "China", "türkei": "Turkey",
    "turkey": "Turkey", "tr": "Turkey", "vereinigtes königreich": "United Kingdom",
    "united kingdom": "United Kingdom", "uk": "United Kingdom", "gb": "United Kingdom",
    "usa": "United States", "united states": "United States", "us": "United States",
    "kanada": "Canada", "canada": "Canada", "ca": "Canada", "australien": "Australia",
    "australia": "Australia", "au": "Australia", "dänemark": "Denmark",
    "denmark": "Denmark", "dk": "Denmark", "norwegen": "Norway", "norway": "Norway",
    "no": "Norway", "schweden": "Sweden", "sweden": "Sweden", "se": "Sweden",
    "finnland": "Finland", "finland": "Finland", "fi": "Finland",
    "tschechien": "Czech Republic", "czech republic": "Czech Republic", "cz": "Czech Republic",
    "rumänien": "Romania", "romania": "Romania", "ro": "Romania",
    "ungarn": "Hungary", "hungary": "Hungary", "hu": "Hungary",
    "thailand": "Thailand", "th": "Thailand", "indonesien": "Indonesia",
    "indonesia": "Indonesia", "id": "Indonesia", "japan": "Japan", "jp": "Japan",
    "slowakei": "Slovakia", "slovakia": "Slovakia", "sk": "Slovakia",
    "kambodscha": "Cambodia", "cambodia": "Cambodia", "kh": "Cambodia",
    "tunesien": "Tunisia", "tunisia": "Tunisia", "tn": "Tunisia",
    "kroatien": "Croatia", "croatia": "Croatia", "hr": "Croatia",
    "bosnien und herzegowina": "Bosnia and Herzegovina",
    "bosnia and herzegovina": "Bosnia and Herzegovina", "ba": "Bosnia and Herzegovina",
    "brasilien": "Brazil", "brazil": "Brazil", "br": "Brazil",
    "nepal": "Nepal", "np": "Nepal", "vereinigte arabische emirate": "United Arab Emirates",
    "united arab emirates": "United Arab Emirates", "ae": "United Arab Emirates",
    "taiwan": "Taiwan", "tw": "Taiwan", "vietnam": "Vietnam", "vn": "Vietnam",
    "malaysia": "Malaysia", "my": "Malaysia", "malta": "Malta", "mt": "Malta",
    "serbien": "Serbia", "serbia": "Serbia", "rs": "Serbia",
    "hongkong": "Hong Kong", "hong kong": "Hong Kong", "hk": "Hong Kong",
    "lettland": "Latvia", "latvia": "Latvia", "lv": "Latvia",
    "libanon": "Lebanon", "lebanon": "Lebanon", "lb": "Lebanon",
}


def text(node: Any) -> str:
    if node is None:
        return ""
    # The DOMOTEX templates contain direct strings that BeautifulSoup does not
    # expose through .strings when custom elements are involved.
    return re.sub(r"\s+", " ", html.unescape("".join(str(x) for x in node.contents))).strip()


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def valid_email(value: str) -> str:
    value = clean(value).lower().removeprefix("mailto:")
    match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", value, re.I)
    return match.group(0) if match and "example." not in match.group(0) else ""


def valid_phone(value: str) -> str:
    value = clean(value)
    digits = re.sub(r"\D", "", value)
    if not 8 <= len(digits) <= 15:
        return ""
    if re.search(r"\b(?:19|20)\d{2}\b", value) or re.search(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", value):
        return ""
    return value


def domain(value: str) -> str:
    value = clean(value)
    if not value:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", value, re.I):
        value = "https://" + value
    host = urlparse(value).netloc.lower().split("@")[-1].split(":")[0].removeprefix("www.")
    if not host or "." not in host:
        return ""
    ext = tldextract.extract(host)
    root = ext.top_domain_under_public_suffix or ext.registered_domain
    if not root or any(host == x or host.endswith("." + x) for x in BLOCKED_DOMAINS):
        return ""
    return root


def country_for(location: str) -> str:
    low = clean(location).casefold()
    for key, value in COUNTRIES.items():
        if re.search(rf"(?<![a-z]){re.escape(key)}(?![a-z])", low):
            return value
    return ""


def fetch_page(session: requests.Session, page: int) -> list[dict[str, str]]:
    initial = session.get(SEARCH_URL, headers=HEADERS, timeout=TIMEOUT)
    initial.raise_for_status()
    soup = BeautifulSoup(initial.text, "html.parser")
    state = soup.select_one("input[name=state]")
    data = {
        "action": json.dumps({"action": "page", "value": str(page)}, separators=(",", ":")),
        "state": state.get("value", "") if state else "",
        "category": "ep",
    }
    response = session.post(f"{BASE}/de/suche/", data=data, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    result = BeautifulSoup(response.text, "html.parser")
    rows = []
    for item in result.select("o-search-snippet[href]"):
        # The supplied search combines exhibitors and products. Keep only
        # company profiles, while still visiting all 64 result pages.
        if clean(item.get("type", "")) != "Aussteller 2026":
            continue
        href = item.get("href", "")
        name = text(item.select_one("[data-cy=masterSnippetName]"))
        place = text(item.select_one("[data-cy=masterSnippetAttribute]"))
        booth = text(item.select_one(".search-snippet-location"))
        if href and name:
            rows.append({"exhibitor_name": name, "city_country": place, "booth": booth,
                         "profile_url": urljoin(BASE, href)})
    return rows


def parse_detail(session: requests.Session, base: dict[str, str]) -> dict[str, str]:
    record = {
        "exhibitor_name": base["exhibitor_name"], "domain": "", "contact_number": "",
        "mail": "", "location": "", "country": "", "booth": base["booth"],
        "profile_url": base["profile_url"], "description": "", "website": "",
        "city_country": base["city_country"], "event_year": "2026",
    }
    try:
        response = session.get(base["profile_url"], headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        title = soup.select_one('h1[data-cy="fragmentHeadline"]') or soup.select_one("h1.headline")
        record["exhibitor_name"] = text(title) or base["exhibitor_name"]
        desc = soup.select_one('[data-cy="detailPageDescription"]')
        record["description"] = text(desc)
        website_links = []
        for a in soup.select("a[href]"):
            href = clean(a.get("href", ""))
            if href.startswith(("http://", "https://")) and domain(href):
                website_links.append(href)
        if website_links:
            record["website"] = website_links[0]
            record["domain"] = domain(website_links[0])
        street = text(soup.select_one('[data-cy="contactCompanyStreet"]'))
        zip_city = text(soup.select_one('[data-cy="contactCompanyZipCode"]'))
        country = text(soup.select_one('[data-cy="contactCompanyCountry"]'))
        record["location"] = clean(" ".join(x for x in (street, zip_city, country) if x))
        record["country"] = country_for(record["location"]) or country_for(base["city_country"])
        for a in soup.select('a[href^="tel:"]'):
            phone = valid_phone(a.get("href", "")[4:].split("?", 1)[0])
            if phone:
                record["contact_number"] = phone
                break
        if not record["contact_number"]:
            match = re.search(r"(?:Telefon|Phone|Tel\\.?)\s*:\s*([^<\n]+)", response.text, re.I)
            if match:
                record["contact_number"] = valid_phone(match.group(1))
        for a in soup.select('a[href^="mailto:"]'):
            record["mail"] = valid_email(a.get("href", ""))
            if record["mail"]:
                break
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    return record


def serper_enrich(record: dict[str, str], api_key: str) -> None:
    if record["domain"] or not api_key:
        return
    query = f'"{record["exhibitor_name"]}" official website {record["city_country"]}'
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": 5}, timeout=TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        knowledge = data.get("knowledgeGraph", {})
        candidate = domain(knowledge.get("website", ""))
        if candidate:
            record["domain"] = candidate
            record["website"] = knowledge.get("website", "")
        if not record["location"] and knowledge.get("address"):
            record["location"] = clean(knowledge["address"])
        if not record["contact_number"]:
            record["contact_number"] = valid_phone(knowledge.get("phone", ""))
        if not record["domain"]:
            for item in data.get("organic", []):
                candidate = domain(item.get("link", ""))
                if candidate:
                    record["domain"] = candidate
                    record["website"] = item.get("link", "")
                    break
    except Exception as exc:
        record["serper_error"] = f"{type(exc).__name__}: {exc}"


def main() -> None:
    api_key = ""
    env_path = ROOT.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("SERPER_API_KEY="):
                api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                break

    all_rows: list[dict[str, str]] = []
    with requests.Session() as session:
        for page in range(1, 65):
            rows = fetch_page(session, page)
            all_rows.extend(rows)
            print(f"page {page:02d}/64: {len(rows)} exhibitors (total {len(all_rows)})", flush=True)
            time.sleep(0.15)

    unique: dict[str, dict[str, str]] = {row["profile_url"]: row for row in all_rows}
    records: list[dict[str, str]] = []
    def worker(row: dict[str, str]) -> dict[str, str]:
        with requests.Session() as session:
            return parse_detail(session, row)
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = {pool.submit(worker, row): row for row in unique.values()}
        for index, future in enumerate(as_completed(futures), 1):
            record = future.result()
            serper_enrich(record, api_key)
            records.append(record)
            if index % 50 == 0 or index == len(futures):
                print(f"details {index}/{len(futures)}", flush=True)

    records.sort(key=lambda x: (x["exhibitor_name"].casefold(), x["profile_url"]))
    fields = [
        "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
        "booth", "profile_url", "description", "website", "city_country", "event_year",
    ]
    csv_path = OUT / "DOMOTEX_SOUTH_EAST_ASIA_R_T_SOUTH_EAST_ASIA_FUTURE_BUILD_ASIA_2026_exhibitors.csv"
    json_path = OUT / "DOMOTEX_SOUTH_EAST_ASIA_R_T_SOUTH_EAST_ASIA_FUTURE_BUILD_ASIA_2026_exhibitors.json"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {len(records)} unique exhibitor records")
    print(csv_path)
    print(json_path)


if __name__ == "__main__":
    main()
