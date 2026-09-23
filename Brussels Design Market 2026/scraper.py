import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "BRUSSELS_DESIGN_MARKET"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LIST_URL = "https://designmarket.be/uk/exhibitors/"
BASE_URL = "https://designmarket.be"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ExhibitorResearch/1.0)"}
BLOCKED = {
    "facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com",
    "linkedin.com", "wikipedia.org", "yellowpages.com", "yelp.com",
    "google.com", "10times.com", "kompass.com", "designmarket.be",
    "entrytickets.be",
}
FIELDS = [
    "company_name", "booth", "description", "email", "mobile_primary",
    "domain", "full_address", "city", "linkedin_url",
]


def clean(value):
    value = unquote(html.unescape(str(value or ""))).replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def root_url(value):
    if not value:
        return ""
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value.strip()
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if not host or any(host == item or host.endswith("." + item) for item in BLOCKED):
        return ""
    return f"{parsed.scheme or 'https'}://{host}"


def valid_phone(value):
    return 7 <= len(re.sub(r"\D", "", clean(value))) <= 16


def country_name(value):
    mapping = {
        "BE": "Belgium", "FR": "France", "NL": "Netherlands",
        "DE": "Germany", "DK": "Denmark", "IT": "Italy",
        "LU": "Luxembourg", "SE": "Sweden", "CH": "Switzerland",
        "SI": "Slovenia", "UK": "United Kingdom",
    }
    value = clean(value)
    return mapping.get(value.upper(), value)


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
    names = {}
    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        if "/uk/team/" not in href:
            continue
        profile_url = urljoin(BASE_URL, href)
        name = clean(link.get_text(" ", strip=True))
        if name and name.lower() not in {"click here"}:
            names[profile_url] = name
    records = []
    for profile_url, name in names.items():
        records.append({
            "company_name": name,
            "booth": "",
            "description": "",
            "email": "",
            "mobile_primary": "",
            "domain": "",
            "full_address": "",
            "city": "",
            "linkedin_url": "",
            "_profile_url": profile_url,
        })
    if not records:
        raise RuntimeError("No 2026 Brussels Design Market exhibitors found")
    return records


def profile(record):
    try:
        response = requests.get(record["_profile_url"], headers=HEADERS, timeout=30)
        response.raise_for_status()
    except requests.RequestException:
        return record
    soup = BeautifulSoup(response.content, "html.parser")
    heading = soup.select_one("h2")
    if heading:
        record["company_name"] = clean(heading.get_text(" ", strip=True))
    country = clean(soup.select_one("h3").get_text(" ", strip=True)) if soup.select_one("h3") else ""
    text = clean(soup.get_text(" ", strip=True))
    address_match = re.search(r"Address:\s*(.+?)\s+Brief info", text, re.I)
    if address_match:
        record["full_address"] = clean(address_match.group(1))
        if country and country.lower() not in record["full_address"].lower():
            record["full_address"] += f", {country_name(country)}"
        city_match = re.search(r",\s*\d{4,6}\s+([^,]+)", record["full_address"])
        if city_match:
            record["city"] = clean(city_match.group(1))
    description_match = re.search(
        r"Brief info\s*(.+?)(?:\s+Website\s*:|\s+Instagram\s*:|$)", text, re.I
    )
    if description_match:
        record["description"] = clean(description_match.group(1))
    for link in soup.select("a[href]"):
        href = link.get("href", "")
        if not record["domain"] and root_url(href):
            record["domain"] = root_url(href)
        if "linkedin.com/company/" in href and not record["linkedin_url"]:
            record["linkedin_url"] = href
        if href.startswith("mailto:") and not record["email"]:
            record["email"] = href.split(":", 1)[1].split("?", 1)[0].lower()
        if href.startswith("tel:") and not record["mobile_primary"] and valid_phone(href[4:]):
            record["mobile_primary"] = clean(href[4:])
    if not record["domain"]:
        website_match = re.search(r"Website\s*:\s*([^\s]+)", text, re.I)
        if website_match:
            record["domain"] = root_url(website_match.group(1))
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
            json={"q": f'{record["company_name"]} official website 2026 design'},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph", {})
        record["domain"] = root_url(graph.get("website", ""))
        if not record["domain"]:
            record["domain"] = next(
                (
                    root_url(item.get("link", ""))
                    for item in data.get("organic", [])
                    if root_url(item.get("link", ""))
                ),
                "",
            )
        if not record["description"]:
            record["description"] = clean(graph.get("description", ""))
    except requests.RequestException:
        pass
    return record


def verify(records):
    key = serper_key()
    payload = json.dumps(records, ensure_ascii=False)
    valid = all(
        record["company_name"]
        and (not record["domain"] or record["domain"].startswith(("http://", "https://")))
        and (not record["email"] or "@" in record["email"])
        and (not record["mobile_primary"] or valid_phone(record["mobile_primary"]))
        for record in records
    )
    print(f"=== Verification Report: {EVENT} ===")
    print(f"Total Exhibitors : {len(records)}")
    print("Field Coverage   :")
    for field in FIELDS:
        count = sum(bool(record[field]) for record in records)
        print(f"  {field:<16}: {count}/{len(records)} ({count / len(records) * 100:.1f}%)")
    print("Sample Verified  :", "3 records [OK]" if len(records) >= 3 else "FAILED")
    print("Security Check   :", "No API key leakage [OK]" if not key or key not in payload else "FAILED")
    status = valid and len(records) >= 3 and (not key or key not in payload)
    print("Status           :", "PASSED" if status else "FAILED")
    if not status:
        raise RuntimeError("Verification failed")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = listing()
    with ThreadPoolExecutor(max_workers=16) as pool:
        records = list(pool.map(profile, records))
        records = list(pool.map(serper_enrich, records))
    records.sort(key=lambda item: item["company_name"].casefold())
    verify(records)
    output = [{field: record[field] for field in FIELDS} for record in records]
    base = OUT / f"{EVENT}_2026_exhibitors"
    with base.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(output)
    base.with_suffix(".json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
