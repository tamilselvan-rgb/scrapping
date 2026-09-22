import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "APCC_NPCC_PARTNERSHIP_SUMMIT"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
BASE_URL = "https://npcc-apcc.com/"
LIST_URL = urljoin(BASE_URL, "exhibitors.asp")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ExhibitorResearch/1.0)"}
BLOCKED = {
    "facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com",
    "linkedin.com", "wikipedia.org", "yellowpages.com", "yelp.com",
    "google.com", "10times.com", "kompass.com", "npcc-apcc.com",
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


def valid_phone(value):
    digits = re.sub(r"\D", "", clean(value))
    return 7 <= len(digits) <= 16


def country_name(value):
    names = {
        "GB": "United Kingdom",
        "UK": "United Kingdom",
        "US": "United States",
        "USA": "United States",
        "CA": "Canada",
        "AU": "Australia",
    }
    value = clean(value)
    return names.get(value.upper(), value)


def jsonld_values(soup):
    values = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            parsed = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        entries = parsed if isinstance(parsed, list) else [parsed]
        for entry in entries:
            if isinstance(entry, dict):
                values.append(entry)
    return values


def listing():
    response = requests.get(LIST_URL, headers=HEADERS, timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    records = []
    seen = set()
    for image in soup.select('img[alt]'):
        link = image.find_parent("a", href=True)
        name = clean(image.get("alt"))
        href = link.get("href", "").strip() if link else ""
        if not name or not href.startswith(("http://", "https://")):
            continue
        domain = root_domain(href)
        if not domain or href in seen:
            continue
        seen.add(href)
        records.append({
            "exhibitor_name": name,
            "domain": domain,
            "contact_number": "",
            "mail": "",
            "location": "",
            "country": "",
            "booth_no": "",
            "desc": "",
            "linkedin_url": "",
            "city": "",
            "profile_url": href,
            "event_date": "2026-11-17 to 2026-11-18",
            "event_venue": "QEII Conference Centre, Westminster, London, United Kingdom",
            "source_url": LIST_URL,
            "source_year": "2026",
        })
    if not records:
        raise RuntimeError("No 2026 APCC/NPCC exhibitors found")
    return records


def profile(record):
    try:
        response = requests.get(record["profile_url"], headers=HEADERS, timeout=30)
        response.raise_for_status()
    except requests.RequestException:
        return record
    soup = BeautifulSoup(response.content, "html.parser")
    record["mail"] = next(
        (
            link["href"].split(":", 1)[1].split("?", 1)[0].strip().lower()
            for link in soup.select('a[href^="mailto:"]')
            if "@" in link.get("href", "")
        ),
        "",
    )
    record["contact_number"] = next(
        (
            clean(link["href"][4:])
            for link in soup.select('a[href^="tel:"]')
            if valid_phone(link.get("href", "")[4:])
        ),
        "",
    )
    linkedin = next(
        (link.get("href") for link in soup.select('a[href*="linkedin.com/"]')),
        "",
    )
    record["linkedin_url"] = linkedin or ""
    for item in jsonld_values(soup):
        address = item.get("address")
        if isinstance(address, dict):
            parts = [
                address.get("streetAddress"), address.get("addressLocality"),
                address.get("addressRegion"), address.get("postalCode"),
            ]
            record["location"] = clean(", ".join(part for part in parts if part))
            record["city"] = clean(address.get("addressLocality", ""))
            record["country"] = country_name(address.get("addressCountry", ""))
        phone = item.get("telephone", "")
        if not record["contact_number"] and valid_phone(phone):
            record["contact_number"] = clean(phone)
    description = soup.select_one('meta[name="description"], meta[property="og:description"]')
    if description:
        record["desc"] = clean(description.get("content", ""))
    if not record["desc"] and soup.title:
        record["desc"] = clean(soup.title.get_text(" ", strip=True))
    return record


def serper_key():
    env = ROOT.parent / ".env"
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"\'')
    return ""


def serper_enrich(record):
    key = serper_key()
    if not key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website 2026 UK'},
            timeout=15,
        )
        response.raise_for_status()
        graph = response.json().get("knowledgeGraph", {})
        if not record["location"]:
            record["location"] = clean(graph.get("address", ""))
        if not record["contact_number"] and valid_phone(graph.get("phone", "")):
            record["contact_number"] = clean(graph["phone"])
        if not record["linkedin_url"]:
            for item in response.json().get("organic", []):
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
    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(profile, records))
        records = list(pool.map(serper_enrich, records))
    records.sort(key=lambda item: item["exhibitor_name"].casefold())
    base = OUT / f"{EVENT}_2026_exhibitors"
    with base.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    base.with_suffix(".json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Exported {len(records)} 2026 APCC/NPCC exhibitors")
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
