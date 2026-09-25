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


EVENT = "BIOTECH_JAPAN_2026"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
LIST_URL = "https://biojapan2026.jcdbizmatch.jp/Lookup/en/List/u0"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ExhibitorResearch/1.0)"}
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location",
    "country", "company_name", "booth", "description", "city", "linkedin_url",
]
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com",
    "jcdbizmatch.jp",
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
            "ltd", "llc", "inc", "co", "company", "corporation", "the",
            "and", "gmbh", "group", "holdings", "pharma",
        }
    }
    return domain if host and tokens and any(
        token in host or host in token for token in tokens
    ) else ""


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
    soup = BeautifulSoup(fetch(LIST_URL), "html.parser")
    records = []
    seen = set()
    for row in soup.select("table tr"):
        cells = row.select("td")
        if len(cells) < 3:
            continue
        exhibit = clean(cells[0].get_text(" ", strip=True))
        company = clean(cells[1].get_text(" ", strip=True))
        booth = clean(cells[2].get_text(" ", strip=True))
        if not company or company.casefold() == "company":
            continue
        company = re.sub(r"^-\s*", "", company)
        key = (company.casefold(), booth.casefold(), exhibit.casefold())
        if key in seen:
            continue
        seen.add(key)
        records.append({
            "exhibitor_name": company,
            "company_name": company,
            "booth": booth,
            "description": f"Exhibitor in {exhibit}" if exhibit else "",
            "domain": "",
            "contact_number": "",
            "mail": "",
            "location": "PACIFICO Yokohama, Yokohama, Japan",
            "country": "Japan",
            "city": "Yokohama",
            "linkedin_url": "",
        })
    if not records:
        raise RuntimeError("No BioJapan 2026 exhibitors found")
    return records


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
                "q": f'"{record["exhibitor_name"]}" official website {record["location"]}',
                "gl": "jp", "hl": "en", "num": 10,
            },
            timeout=45,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph") or {}
        candidates = [graph.get("website", "")]
        candidates.extend(item.get("link", "") for item in data.get("organic", []))
        for candidate in candidates:
            domain = matching_domain(record["exhibitor_name"], domain_url(candidate))
            if domain:
                record["domain"] = domain
                break
        if not record["contact_number"]:
            record["contact_number"] = clean(graph.get("phone"))
        if not record["mail"]:
            record["mail"] = clean(graph.get("email")).lower()
        if record["location"] == "PACIFICO Yokohama, Yokohama, Japan":
            address = clean(graph.get("address"))
            if address:
                record["location"] = address
    except requests.RequestException:
        pass
    return record


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    records = listing()
    print(f"Found {len(records)} unique 2026 exhibitors")
    with ThreadPoolExecutor(max_workers=16) as pool:
        records = list(pool.map(serper_enrich, records))
    unique = {}
    for record in records:
        unique.setdefault(record["exhibitor_name"].casefold(), record)
    records = list(unique.values())
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
