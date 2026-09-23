import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "NIDV_EXHIBITION_DEFENCE_SECURITY"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LIST_URL = "https://www.nidvexhibition.eu/overview-exhibitors"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ExhibitorResearch/1.0)"}
BLOCKED = {
    "facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com",
    "linkedin.com", "wikipedia.org", "yellowpages.com", "yelp.com",
    "google.com", "10times.com", "kompass.com", "nidvexhibition.eu",
}
FIELDS = [
    "company_name", "booth", "description", "email", "mobile_primary",
    "domain", "full_address", "city", "linkedin_url",
    "profile_url", "event_date", "event_venue", "source_url", "source_year",
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
        "NL": "Netherlands", "GB": "United Kingdom", "UK": "United Kingdom",
        "US": "United States", "USA": "United States", "DE": "Germany",
        "BE": "Belgium", "FR": "France", "IE": "Ireland", "EE": "Estonia",
    }
    value = clean(value)
    return mapping.get(value.upper(), value)


def address_from_jsonld(value):
    if not isinstance(value, dict):
        return "", ""
    parts = [
        value.get("streetAddress"), value.get("addressLocality"),
        value.get("addressRegion"), value.get("postalCode"),
        country_name(value.get("addressCountry", "")),
    ]
    return clean(", ".join(clean(part) for part in parts if clean(part))), clean(
        value.get("addressLocality", "")
    )


def jsonld_entries(soup):
    entries = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        entries.extend(value if isinstance(value, list) else [value])
    return [entry for entry in entries if isinstance(entry, dict)]


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
    records = []
    seen = set()
    for image in soup.select("main img.img-logo[alt]"):
        link = image.find_parent("a", href=True)
        name = clean(image.get("alt"))
        href = root_url(link.get("href", "")) if link else ""
        if not name or not href or href in seen:
            continue
        seen.add(href)
        records.append({
            "company_name": name,
            "booth": "",
            "description": "",
            "email": "",
            "mobile_primary": "",
            "domain": href,
            "full_address": "",
            "city": "",
            "linkedin_url": "",
            "profile_url": href,
            "event_date": "2026",
            "event_venue": "NEDS, Netherlands",
            "source_url": LIST_URL,
            "source_year": "2026",
        })
    if not records:
        raise RuntimeError("No 2026 NIDV exhibitors found")
    return records


def profile(record):
    try:
        response = requests.get(record["profile_url"], headers=HEADERS, timeout=30)
        response.raise_for_status()
    except requests.RequestException:
        return record
    soup = BeautifulSoup(response.content, "html.parser")
    description = soup.select_one(
        'meta[name="description"], meta[property="og:description"]'
    )
    if description:
        value = clean(description.get("content", ""))
        if len(value) >= 30 and not re.search(
            r"enable javascript|cookie|just a moment", value, re.I
        ):
            record["description"] = value
    for entry in jsonld_entries(soup):
        address = entry.get("address")
        full_address, city = address_from_jsonld(address)
        if full_address and not record["full_address"]:
            record["full_address"] = full_address
            record["city"] = city
        phone = entry.get("telephone", "")
        if not record["mobile_primary"] and valid_phone(phone):
            record["mobile_primary"] = clean(phone)
    record["email"] = next(
        (
            link.get("href", "").split(":", 1)[1].split("?", 1)[0].strip().lower()
            for link in soup.select('a[href^="mailto:"]')
            if "@" in link.get("href", "")
        ),
        "",
    )
    if not record["mobile_primary"]:
        record["mobile_primary"] = next(
            (
                clean(link.get("href", "")[4:])
                for link in soup.select('a[href^="tel:"]')
                if valid_phone(link.get("href", "")[4:])
            ),
            "",
        )
    record["linkedin_url"] = next(
        (
            link.get("href")
            for link in soup.select('a[href*="linkedin.com/"]')
            if re.search(r"linkedin\.com/(company|school)/", link.get("href", ""))
        ),
        "",
    )
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
            json={"q": f'{record["company_name"]} official website 2026'},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        website = data.get("knowledgeGraph", {}).get("website", "")
        record["domain"] = root_url(website)
        if not record["domain"]:
            for item in data.get("organic", []):
                candidate = root_url(item.get("link", ""))
                if candidate:
                    record["domain"] = candidate
                    break
        if not record["description"]:
            record["description"] = clean(
                data.get("knowledgeGraph", {}).get("description", "")
            )
        if not record["linkedin_url"]:
            record["linkedin_url"] = next(
                (
                    item.get("link")
                    for item in data.get("organic", [])
                    if "linkedin.com/company/" in item.get("link", "")
                ),
                "",
            )
    except requests.RequestException:
        pass
    return record


def verification(records):
    required = FIELDS[:9]
    print(f"=== Verification Report: {EVENT} ===")
    print(f"Total Exhibitors : {len(records)}")
    print("Field Coverage   :")
    for field in required:
        count = sum(bool(record.get(field)) for record in records)
        print(f"  {field:<16}: {count}/{len(records)} ({count / len(records) * 100:.1f}%)")
    key = serper_key()
    output_text = json.dumps(records, ensure_ascii=False)
    security_ok = not key or key not in output_text
    samples_ok = all(
        record["company_name"] and record["domain"] and record["source_year"] == "2026"
        for record in records[:3]
    )
    valid_values = all(
        record["company_name"]
        and (not record["email"] or "@" in record["email"])
        and (not record["mobile_primary"] or valid_phone(record["mobile_primary"]))
        and (not record["linkedin_url"] or "linkedin.com/company/" in record["linkedin_url"]
             or "linkedin.com/school/" in record["linkedin_url"])
        and (not record["description"] or len(record["description"]) >= 30)
        for record in records
    )
    print("Sample Verified  :", "3 records [OK]" if samples_ok else "FAILED")
    print("Security Check   :", "No API key leakage [OK]" if security_ok else "FAILED")
    passed = bool(records) and security_ok and samples_ok and valid_values
    print("Status           :", "PASSED" if passed else "FAILED")
    if not passed:
        raise RuntimeError("Verification failed")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = listing()
    with ThreadPoolExecutor(max_workers=16) as pool:
        records = list(pool.map(profile, records))
        records = list(pool.map(serper_enrich, records))
    records.sort(key=lambda item: item["company_name"].casefold())
    verification(records)
    base = OUT / f"{EVENT}_2026_exhibitors"
    with base.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    base.with_suffix(".json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
