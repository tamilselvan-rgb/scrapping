import csv
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "BEAUTYWORLD_MIDDLE_EAST_2026"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
BASE_URL = "https://beautyworld-dubai.ae.messefrankfurt.com/dubai/en"
API_URL = "https://api.messefrankfurt.com/service/esb_api/exhibitor-service/api/2.1/public/exhibitor/search"
EVENT_ID = "BEAUTYWORLDMIDDLEEAST"
PUBLIC_API_KEY = "LXnMWcYQhipLAS7rImEzmZ3CkrU033FMha9cwVSngG4vbufTsAOCQQ=="
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ExhibitorResearch/1.0)"}
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location",
    "country", "company_name", "booth", "description", "city", "linkedin_url",
]
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com",
    "messefrankfurt.com", "beautyworld-dubai.ae",
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


def request(method, url, **kwargs):
    for attempt in range(4):
        try:
            response = requests.request(method, url, headers=HEADERS, timeout=60, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


def search_page(page):
    params = {
        "language": "en-GB", "findEventVariable": EVENT_ID, "orderBy": "name",
        "pageNumber": page, "pageSize": 90, "showJumpLabels": "true",
    }
    response = requests.get(
        API_URL, params=params,
        headers={**HEADERS, "apikey": PUBLIC_API_KEY}, timeout=60,
    )
    response.raise_for_status()
    return response.json()["result"]


def api_records():
    first = search_page(1)
    total = first["metaData"]["hitsTotal"]
    pages = (total + 89) // 90
    results = first["hits"]
    if pages > 1:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for result in pool.map(search_page, range(2, pages + 1)):
                results.extend(result["hits"])
    records = []
    for hit in results:
        exhibitor = hit.get("exhibitor") or {}
        address = exhibitor.get("address") or {}
        country = (address.get("country") or {}).get("label", "")
        stands = []
        for hall in (exhibitor.get("exhibition") or {}).get("exhibitionHall") or []:
            stands.extend(stand.get("name", "") for stand in hall.get("stand") or [])
        rewrite = exhibitor.get("rewriteId", "")
        if not rewrite:
            continue
        records.append({
            "exhibitor_name": clean(exhibitor.get("name")),
            "domain": domain_url(exhibitor.get("homepage") or exhibitor.get("href")),
            "contact_number": clean(address.get("tel")),
            "mail": clean(address.get("email")).lower(),
            "location": clean(", ".join(
                part for part in [
                    address.get("street"), address.get("zip"), address.get("city"),
                    country,
                ] if clean(part)
            )),
            "country": clean(country),
            "company_name": clean(exhibitor.get("name")),
            "booth": clean(", ".join(filter(None, stands))),
            "description": clean((exhibitor.get("description") or {}).get("text")),
            "city": clean(address.get("city")),
            "linkedin_url": "",
            "profile_url": f"{BASE_URL}/exhibitor-search.detail.html/{rewrite}.html#exhibitorheadline",
        })
    return records


def name_tokens(name):
    return {
        token for token in re.findall(r"[a-z0-9]+", name.casefold())
        if len(token) >= 3 and token not in {
            "ltd", "llc", "inc", "fze", "fzco", "co", "company", "limited",
            "gmbh", "sa", "spa", "srl", "and", "the",
        }
    }


def matching_domain(name, domain):
    if not domain:
        return ""
    host = re.sub(r"[^a-z0-9]", "", domain.split(".")[0].casefold())
    tokens = name_tokens(name)
    if not host or not tokens:
        return ""
    return domain if any(token in host or host in token for token in tokens) else ""


def visit_profile(record):
    try:
        soup = BeautifulSoup(request("GET", record["profile_url"]).content, "html.parser")
    except requests.RequestException:
        return record
    heading = soup.select_one("h1.ex-exhibitor-detail__title-headline")
    if heading:
        record["exhibitor_name"] = clean(heading.get_text(" ", strip=True))
        record["company_name"] = record["exhibitor_name"]
    for link in soup.select("a[href^='tel:']"):
        if clean(link.get("href", "").split(":", 1)[-1]):
            record["contact_number"] = clean(link["href"].split(":", 1)[-1])
            break
    for link in soup.select("a[href^='mailto:']"):
        address = clean(link.get("href", "").split(":", 1)[-1].split("?", 1)[0]).lower()
        if address:
            record["mail"] = address
            break
    website_candidates = []
    for script in soup.select('script[type="application/ld+json"]'):
        website_candidates.extend(
            re.findall(r'"url"\s*:\s*"([^"]+)"', script.get_text())
        )
    website_candidates.extend(
        link.get("href", "") for link in soup.select("a.a-link--external[href]")
    )
    for candidate in website_candidates:
        domain = matching_domain(record["exhibitor_name"], domain_url(candidate))
        if domain:
            record["domain"] = domain
            break
    record["domain"] = matching_domain(record["exhibitor_name"], record["domain"])
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
                "q": f'"{record["exhibitor_name"]}" official website {record["location"]}',
                "gl": "ae", "hl": "en", "num": 10,
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
        if not record["location"]:
            record["location"] = clean(graph.get("address"))
    except requests.RequestException:
        pass
    return record


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    records = api_records()
    unique = {}
    for record in records:
        unique.setdefault(record["exhibitor_name"].casefold(), record)
    records = list(unique.values())
    print(f"Found {len(records)} 2026 exhibitors")
    with ThreadPoolExecutor(max_workers=24) as pool:
        records = list(pool.map(visit_profile, records))
    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(serper_enrich, records))
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
