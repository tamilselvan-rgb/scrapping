import csv
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "DSEI_UK_2027"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
BASE_URL = "https://www.dsei.co.uk"
LIST_URL = f"{BASE_URL}/visit/exhibiting-companies"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ExhibitorResearch/1.0)"}
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location",
    "country", "company_name", "booth", "description", "city", "linkedin_url",
]
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com",
    "dsei.co.uk", "clarion-defence.com", "asp.events",
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
            "ltd", "llc", "inc", "pty", "plc", "ag", "co", "company",
            "corporation", "the", "and", "group", "limited",
        }
    }
    return domain if host and tokens and any(
        token in host or host in token for token in tokens
    ) else ""


def get(url, **kwargs):
    for attempt in range(4):
        try:
            response = requests.get(url, headers=HEADERS, timeout=60, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


def listing_page(page):
    response = get(
        LIST_URL,
        params={"page": page, "azLetterField": ""},
    )
    soup = BeautifulSoup(response.content, "html.parser")
    records = []
    for item in soup.select("li.js-library-item"):
        title = item.select_one(
            ".m-exhibitors-list__items__item__header__title"
        )
        if not title:
            continue
        name = clean(title.get_text(" ", strip=True))
        link = title.select_one("a[href*='openRemoteModal']")
        if not link:
            continue
        match = re.search(
            r"openRemoteModal\('([^']+)'", link.get("href", "")
        )
        if not match:
            continue
        stand = item.select_one(
            ".m-exhibitors-list__items__item__header__meta__stand"
        )
        records.append({
            "exhibitor_name": name,
            "booth": clean(stand.get_text(" ", strip=True)) if stand else "",
            "slug": match.group(1),
            "profile_url": f"{BASE_URL}/{match.group(1)}",
        })
    return records


def listing():
    records = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for page_records in pool.map(listing_page, range(1, 9)):
            records.extend(page_records)
    unique = {}
    for record in records:
        unique.setdefault(record["slug"], record)
    return list(unique.values())


def profile(record):
    try:
        soup = BeautifulSoup(get(record["profile_url"]).content, "html.parser")
    except requests.RequestException:
        return record
    name = clean(record["exhibitor_name"])
    description = soup.select_one(
        ".m-exhibitor-entry__item__body__description"
    )
    website = ""
    website_block = soup.select_one(
        ".m-exhibitor-entry__item__body__contacts__additional__website"
    )
    if website_block:
        link = website_block.select_one("a[href]")
        website = domain_url(link.get("href")) if link else ""
    country = ""
    location = ""
    city = ""
    ld = soup.select_one("script[type='application/ld+json']")
    if ld:
        try:
            data = json.loads(ld.get_text())
            organization = data.get("mainEntity") or {}
            name = clean(organization.get("name") or name)
            if not website:
                website = domain_url(organization.get("url"))
            address = organization.get("address") or {}
            country = clean(address.get("addressCountry"))
            location = clean(", ".join(
                value for value in [
                    address.get("streetAddress"),
                    address.get("addressLocality"),
                    address.get("addressRegion"),
                    address.get("postalCode"),
                    country,
                ] if clean(value)
            ))
            city = clean(address.get("addressLocality"))
            if not description:
                description = organization.get("description")
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass
    record.update({
        "exhibitor_name": name,
        "domain": matching_domain(name, website),
        "country": country,
        "location": location,
        "city": city,
        "description": clean(
            description.get_text(" ", strip=True)
            if hasattr(description, "get_text") else description
        ),
        "contact_number": "",
        "mail": "",
        "company_name": name,
        "linkedin_url": "",
    })
    return record


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
                "q": f'"{record["exhibitor_name"]}" official website {record.get("location") or "DSEI UK"}',
                "gl": "gb", "hl": "en", "num": 10,
            },
            timeout=45,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph") or {}
        candidates = [graph.get("website", "")]
        candidates.extend(item.get("link", "") for item in data.get("organic", []))
        if not record.get("domain"):
            for candidate in candidates:
                domain = matching_domain(
                    record["exhibitor_name"], domain_url(candidate)
                )
                if domain:
                    record["domain"] = domain
                    break
        if not record.get("contact_number"):
            record["contact_number"] = clean(graph.get("phone"))
        if not record.get("location"):
            record["location"] = clean(graph.get("address"))
    except requests.RequestException:
        pass
    return record


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source_records = listing()
    print(f"Found {len(source_records)} DSEI UK 2027 profile entries")
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(profile, source_records))
    with ThreadPoolExecutor(max_workers=16) as pool:
        records = list(pool.map(serper_enrich, records))
    for record in records:
        record["company_name"] = record["exhibitor_name"]
    records.sort(key=lambda item: item["exhibitor_name"].casefold())
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
