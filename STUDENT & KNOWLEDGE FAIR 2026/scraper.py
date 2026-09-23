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


EVENT = "STUDENT_AND_KNOWLEDGE_FAIR_2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LIST_URL = "https://kunskapframtid.se/utstallare/"
FEED_URL = "https://objects.dc-fbg1.glesys.net/holy-term/sites/41/json-cache/exhibitormodel/all.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ExhibitorResearch/1.0)"}
VENUE = "Svenska Mässan, Mässans gata/Korsvägen, Gothenburg, Sweden"
EVENT_DATE = "2026-11-19 to 2026-11-20"
FIELDS = [
    "company_name", "domain", "description", "booth", "email", "city",
    "full_address", "mobile_primary",
]
BLOCKED = {
    "kunskapframtid.se", "facebook.com", "instagram.com", "linkedin.com",
    "twitter.com", "x.com", "youtube.com", "wikipedia.org", "yellowpages.com",
    "yelp.com", "google.com", "svenskamassan.se", "bwz.se",
}


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def root_domain(value):
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


def fetch(url):
    for attempt in range(4):
        try:
            response = requests.get(url, headers=HEADERS, timeout=60)
            response.raise_for_status()
            return response.content
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


def listing():
    data = json.loads(fetch(FEED_URL))
    records = []
    for item in data.get("exhibitors", []):
        url = clean(item.get("url"))
        if not url:
            continue
        records.append({
            "company_name": clean(item.get("title")),
            "domain": "",
            "description": clean(BeautifulSoup(item.get("content", ""), "html.parser").get_text(" ", strip=True)),
            "booth": clean(item.get("stand")),
            "email": "",
            "city": "Gothenburg",
            "full_address": "",
            "mobile_primary": "",
            "profile_url": url,
        })
    if not records:
        raise RuntimeError("No 2026 Student & Knowledge Fair exhibitors found")
    return records


def parse_address(element):
    parts = [clean(part) for part in element.stripped_strings if clean(part)]
    if not parts:
        return "", ""
    country_map = {"SVERIGE": "Sweden", "SWEDEN": "Sweden"}
    country = country_map.get(parts[-1].upper(), parts[-1])
    city = ""
    postcode_index = next(
        (index for index, part in enumerate(parts)
         if re.match(r"^\d{3}\s*\d{2}\s+", part)),
        -1,
    )
    if postcode_index >= 0:
        postcode_city = re.search(r"^\d{3}\s*\d{2}\s+(.+)$", parts[postcode_index])
        if postcode_city:
            city = clean(postcode_city.group(1))
    elif len(parts) > 2:
        city = parts[-2]
    parts[-1] = country
    return ", ".join(parts), city


def profile(record):
    try:
        soup = BeautifulSoup(fetch(record["profile_url"]), "html.parser")
    except requests.RequestException as exc:
        print(f"Profile failed: {record['company_name']}: {exc}")
        return record
    content = soup.select_one("main") or soup
    heading = content.select_one("h1")
    if heading:
        record["company_name"] = clean(heading.get_text(" ", strip=True))
    stand = content.select_one(".stand")
    if stand:
        record["booth"] = clean(stand.get_text(" ", strip=True)).replace("Plats:", "").strip()
    address = content.select_one("dl.sidebar dd")
    if address:
        record["full_address"], city = parse_address(address)
        if city:
            record["city"] = city
    for link in content.select("a[href]"):
        href = link.get("href", "")
        if "mailto:" in href.lower():
            record["email"] = href.split(":", 1)[1].split("?", 1)[0].lower()
        elif not record["domain"]:
            record["domain"] = root_domain(href)
    return record


def serper_key():
    path = ROOT.parent / ".env"
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip().strip("\"'")
    return ""


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
            json={
                "q": f'"{record["company_name"]}" official website 2026 Student Knowledge Fair Sweden',
                "gl": "se", "hl": "en", "num": 10,
            },
            timeout=45,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph") or {}
        record["domain"] = root_domain(graph.get("website", ""))
        if not record["domain"]:
            for result in data.get("organic", []):
                candidate = root_domain(result.get("link", ""))
                if candidate:
                    record["domain"] = candidate
                    break
    except requests.RequestException as exc:
        print(f"Serper failed: {record['company_name']}: {exc}")
    return record


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = listing()
    print(f"Found {len(records)} 2026 exhibitors")
    with ThreadPoolExecutor(max_workers=6) as pool:
        records = list(pool.map(profile, records))
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(serper_enrich, [record for record in records if not record["domain"]]))
    records.sort(key=lambda item: item["company_name"].casefold())
    normalized = [{field: record.get(field, "") for field in FIELDS} for record in records]
    base = OUT / f"{EVENT}_exhibitors"
    with base.with_suffix(".csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(normalized)
    base.with_suffix(".json").write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
