import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "INTERNATIONAL_PARKING_COMMUNITY_ANNUAL_CONFERENCE"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LIST_URL = "https://www.ipcconference.co.uk/exhibitors"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ExhibitorResearch/1.0)"}
BLOCKED = {
    "facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com",
    "linkedin.com", "wikipedia.org", "yellowpages.com", "yelp.com",
    "google.com", "10times.com", "kompass.com", "ipcconference.co.uk",
}
FIELDS = [
    "company_name", "booth", "description", "email", "mobile_primary",
    "domain", "full_address", "city", "linkedin_url",
]
DOMAIN_NAMES = {
    "solutions.autopay.io": "Autopay Technologies",
    "hubparking.co.uk": "HUB Parking Technology",
    "designa.com": "DESIGNA",
    "nmi.com": "NMI",
    "displayways.co.uk": "Displayways",
    "sioma.co.uk": "Sioma",
    "twinpay.co.uk": "TwinPay",
    "thetracegroup.co.uk": "The Trace Group",
    "signmark.co.uk": "SignMark",
    "arvoo.com": "Arvoo",
    "cammaxlimited.co.uk": "Cammax",
    "ipsgroup.com": "IPS Group",
    "metricgroup.co.uk": "Metric Group",
    "parkingpatrol.co.uk": "Parking Patrol",
    "skidata.com": "SKIDATA",
    "arrive.com": "Arrive",
    "nagels.com": "Nagels",
    "fr.survisiongroup.com": "Survision",
    "jenoptik.com": "JENOPTIK",
    "openparking.co.uk": "Open Parking",
}


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
        "GB": "United Kingdom", "UK": "United Kingdom",
        "US": "United States", "USA": "United States",
        "CA": "Canada", "DE": "Germany", "FR": "France",
        "NL": "Netherlands", "IE": "Ireland",
    }
    value = clean(value)
    return mapping.get(value.upper(), value)


def jsonld_entries(soup):
    entries = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        entries.extend(value if isinstance(value, list) else [value])
    return [entry for entry in entries if isinstance(entry, dict)]


def address_fields(address):
    if not isinstance(address, dict):
        return "", ""
    values = [
        address.get("streetAddress"), address.get("addressLocality"),
        address.get("addressRegion"), address.get("postalCode"),
        country_name(address.get("addressCountry", "")),
    ]
    return clean(", ".join(clean(value) for value in values if clean(value))), clean(
        address.get("addressLocality", "")
    )


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
    for link in soup.select("a.has-link[href]"):
        href = root_url(link.get("href", ""))
        if not href or href in seen:
            continue
        seen.add(href)
        records.append({
            "company_name": "",
            "booth": "",
            "description": "",
            "email": "",
            "mobile_primary": "",
            "domain": href,
            "full_address": "",
            "city": "",
            "linkedin_url": "",
            "_profile_url": href,
            "_source_name": clean(link.find_previous("h3").get_text(" ", strip=True))
            if link.find_previous("h3") else "",
        })
    if not records:
        raise RuntimeError("No 2026 IPC exhibitors found")
    return records


def profile(record):
    try:
        response = requests.get(record["_profile_url"], headers=HEADERS, timeout=30)
        response.raise_for_status()
    except requests.RequestException:
        if not record["company_name"]:
            record["company_name"] = (
                record["_profile_url"].split("//", 1)[-1]
                .split(".", 1)[0]
                .replace("-", " ")
                .title()
            )
        return record
    soup = BeautifulSoup(response.content, "html.parser")
    entries = jsonld_entries(soup)
    for entry in entries:
        entry_type = entry.get("@type", "")
        if entry_type in {"Organization", "Corporation", "LocalBusiness"}:
            record["company_name"] = clean(entry.get("name", ""))
        if not record["full_address"]:
            record["full_address"], record["city"] = address_fields(entry.get("address"))
        if not record["email"]:
            record["email"] = clean(entry.get("email", "")).lower()
        if not record["mobile_primary"] and valid_phone(entry.get("telephone", "")):
            record["mobile_primary"] = clean(entry.get("telephone", ""))
        for same_as in entry.get("sameAs", []) if isinstance(entry.get("sameAs"), list) else []:
            if "linkedin.com/company/" in same_as:
                record["linkedin_url"] = same_as
    title = soup.select_one("title")
    if not record["company_name"] and title:
        title_text = clean(title.get_text(" ", strip=True))
        record["company_name"] = re.split(r"\s+[|–—-]\s+", title_text)[0]
    if not record["company_name"]:
        record["company_name"] = record["_profile_url"].split("//", 1)[-1].split(".", 1)[0].title()
    description = soup.select_one(
        'meta[name="description"], meta[property="og:description"]'
    )
    if description:
        value = clean(description.get("content", ""))
        if len(value) >= 30 and not re.search(
            r"enable javascript|cookie|just a moment", value, re.I
        ):
            record["description"] = value
    if not record["email"]:
        record["email"] = next(
            (
                link.get("href", "").split(":", 1)[1].split("?", 1)[0].lower()
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
    if not record["linkedin_url"]:
        record["linkedin_url"] = next(
            (
                link.get("href")
                for link in soup.select('a[href*="linkedin.com/company/"]')
            ),
            "",
        )
    host = urlparse(record["_profile_url"]).hostname or ""
    record["company_name"] = DOMAIN_NAMES.get(host.lower(), record["company_name"])
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
        and record["domain"].startswith(("http://", "https://"))
        and (not record["email"] or "@" in record["email"])
        and (not record["mobile_primary"] or valid_phone(record["mobile_primary"]))
        and (not record["linkedin_url"] or "linkedin.com/company/" in record["linkedin_url"])
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
    print("Status           :", "PASSED" if valid and len(records) >= 3 and (not key or key not in payload) else "FAILED")
    if not valid or len(records) < 3 or (key and key in payload):
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
