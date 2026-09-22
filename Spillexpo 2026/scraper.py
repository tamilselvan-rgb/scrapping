import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "SPILLEXPO"
YEAR = "2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LIST_URL = "https://spillexpo.no/utstillere-2025/"
EVENT_URL = "https://spillexpo.no/oslo/"
BASE_URL = "https://spillexpo.no"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "spillexpo.no", "linkedin.com", "facebook.com", "instagram.com",
    "twitter.com", "x.com", "youtube.com", "wikipedia.org", "yellowpages.com",
    "yelp.com", "google.com", "10times.com", "kompass.com", "tracxn.com",
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


def plausible_domain(name, domain):
    generic = {
        "games", "game", "scandinavia", "nordic", "design", "store",
        "media", "group", "company", "academy", "school",
    }
    tokens = [
        token for token in re.findall(r"[a-z0-9]+", name.lower())
        if len(token) >= 4 and token not in generic
    ]
    return any(token in domain for token in tokens)


def linkedin_url(value):
    value = value or ""
    href = value if value.startswith("http") else "https:" + value
    parsed = urlparse(href)
    if "linkedin.com" not in parsed.netloc.lower():
        return ""
    if not re.search(r"/(company|school|in)/", parsed.path):
        return ""
    if "/admin" in parsed.path or "mycompany" in parsed.path:
        return ""
    return href


def email_from_soup(soup):
    for link in soup.select('a[href^="mailto:"]'):
        value = link["href"].split(":", 1)[1].split("?", 1)[0].strip()
        if "@" in value:
            return value.lower()
    match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", soup.get_text(" ", strip=True))
    return match.group(0).lower() if match else ""


def valid_phone(value):
    value = clean(value)
    digits = re.sub(r"\D", "", value)
    return bool(value and 7 <= len(digits) <= 16 and not re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", value))


def phone_from_soup(soup):
    tel = soup.select_one('a[href^="tel:"]')
    if tel and valid_phone(tel.get("href", "")[4:]):
        return clean(tel.get("href", "")[4:])
    for candidate in re.findall(r"(?<!\w)(?:\+|00)?\d[\d\s()./-]{7,}\d", soup.get_text(" ", strip=True)):
        if valid_phone(candidate):
            return clean(candidate)
    return ""


def serper_key():
    env = ROOT.parent / ".env"
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"\'')
    return ""


def listing():
    response = requests.get(LIST_URL, headers=HEADERS, timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    heading = next(
        (node for node in soup.find_all(["h2", "h3"])
         if "Utstillere 2026" in clean(node.get_text(" ", strip=True))),
        None,
    )
    if not heading:
        raise RuntimeError("2026 exhibitor heading not found")
    records = []
    for node in heading.find_all_next():
        if node.name in {"h2", "h3"} and node is not heading:
            break
        if node.name != "p":
            continue
        name = clean(node.get_text(" ", strip=True))
        if not name or name in {item["exhibitor_name"] for item in records}:
            continue
        records.append({
            "exhibitor_name": name,
            "domain": "",
            "contact_number": "",
            "mail": "",
            "location": "",
            "country": "Norway",
            "booth_no": "",
            "desc": "",
            "linkedin_url": "",
            "city": "",
            "profile_url": "",
            "event_date": "2026-11-13 to 2026-11-15",
            "event_venue": "NOVA Spektrum, Messeveien 8, 2004 Lillestrøm, Norway",
            "source_url": LIST_URL,
            "source_year": YEAR,
        })
    if not records:
        raise RuntimeError("No 2026 exhibitors found")
    return records


def serper_enrich(record):
    key = serper_key()
    if not key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website 2026 Norway'},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph", {})
        graph_domain = root_domain(graph.get("website", ""))
        if graph_domain and plausible_domain(record["exhibitor_name"], graph_domain):
            record["domain"] = graph_domain
            record["location"] = clean(graph.get("address", ""))
            record["contact_number"] = clean(graph.get("phone", "")) if valid_phone(graph.get("phone", "")) else ""
            record["desc"] = clean(graph.get("description", ""))
        for item in data.get("organic", []):
            if not record["domain"]:
                candidate = root_domain(item.get("link", ""))
                if candidate and plausible_domain(record["exhibitor_name"], candidate):
                    record["domain"] = candidate
            if not record["linkedin_url"]:
                candidate = linkedin_url(item.get("link", ""))
                if candidate:
                    record["linkedin_url"] = candidate
        if not record["domain"]:
            record["location"] = ""
            record["contact_number"] = ""
            record["desc"] = ""
            record["linkedin_url"] = ""
    except requests.RequestException:
        pass
    return record


def website_contacts(record):
    if not record["domain"]:
        return record
    try:
        response = requests.get(
            "https://" + record["domain"], headers=HEADERS, timeout=20
        )
        soup = BeautifulSoup(response.content, "html.parser")
        record["mail"] = record["mail"] or email_from_soup(soup)
        record["contact_number"] = record["contact_number"] or phone_from_soup(soup)
        if not record["linkedin_url"]:
            link = soup.select_one('a[href*="linkedin.com/"]')
            if link:
                record["linkedin_url"] = linkedin_url(link.get("href", ""))
    except requests.RequestException:
        pass
    return record


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = listing()
    with ThreadPoolExecutor(max_workers=16) as pool:
        records = list(pool.map(serper_enrich, records))
    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(website_contacts, records))
    for record in records:
        if record["location"] and not record["city"]:
            parts = [part.strip() for part in record["location"].split(",") if part.strip()]
            record["city"] = parts[-2] if len(parts) > 1 else parts[-1]
    records.sort(key=lambda item: item["exhibitor_name"].casefold())
    base = OUT / f"{EVENT}_2026_exhibitors"
    with base.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    base.with_suffix(".json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Exported {len(records)} 2026 Spillexpo exhibitors")
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
