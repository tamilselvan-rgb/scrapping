import csv
import html
import json
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests


EVENT = "GET_NORD_2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LIST_URL = "https://www.get-nord.de/ausstellen-besuchen/ausstellendenverzeichnis"
API = "https://live.messebackend.aws.corussoft.de/webservice"
API_PARAMS = {
    "os": "web",
    "appUrl": "https://www.get-nord.de",
    "clientVersion": "1.17.0",
    "topic": "2026_getnord",
    "apiVersion": "52",
    "browserLang": "en-US",
    "timezoneOffset": "0",
    "lang": "en",
}
VENUE = "Hamburg Messe und Congress, Hamburg, Germany"
EVENT_DATE = "2026-11-19 to 2026-11-21"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ExhibitorResearch/1.0)",
    "Accept": "application/json",
}
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location",
    "country", "booth_no", "desc", "linkedin_url", "city", "profile_url",
    "event_date", "event_venue", "source_url", "source_year", "organization_id",
]
BLOCKED = {
    "get-nord.de", "facebook.com", "instagram.com", "linkedin.com",
    "twitter.com", "x.com", "youtube.com", "wikipedia.org", "yellowpages.com",
    "yelp.com", "google.com",
}


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def root_domain(value):
    value = clean(value)
    if not value:
        return ""
    parsed = urlparse(value if re.match(r"^https?://", value, re.I) else "https://" + value)
    value = (parsed.hostname or "").lower().removeprefix("www.")
    if "." not in value or any(value == item or value.endswith("." + item) for item in BLOCKED):
        return ""
    return value


def request(method, url, **kwargs):
    headers = {**HEADERS, **kwargs.pop("headers", {})}
    for attempt in range(4):
        try:
            response = requests.request(method, url, headers=headers, timeout=60, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


def profile_url(name, organization_id):
    slug = re.sub(r"[^A-Za-z0-9]+", "-", clean(name)).strip("-")
    return f"{LIST_URL}#organization--{slug}--{organization_id}"


def listing():
    records = []
    start = 0
    page_size = 100
    while True:
        params = {
            **API_PARAMS,
            "numresultrows": str(page_size),
            "startresultrow": str(start),
            "filterlist": "entity_orga,,cur_curated",
            "order": "relevance",
        }
        response = request("POST", f"{API}/search", data=params)
        data = response.json()
        entities = data.get("entities", [])
        for entity in entities:
            stands = entity.get("stands") or []
            booth = "; ".join(
                clean(stand.get("displayName") or stand.get("standName") or stand.get("standNr"))
                for stand in stands
                if clean(stand.get("displayName") or stand.get("standName") or stand.get("standNr"))
            )
            organization_id = str(entity.get("id", "")).strip()
            if not organization_id:
                continue
            records.append({
                "exhibitor_name": clean(entity.get("name")),
                "domain": "",
                "contact_number": "",
                "mail": "",
                "location": "",
                "country": clean(entity.get("country")),
                "booth_no": booth,
                "desc": clean(entity.get("teaser")),
                "linkedin_url": "",
                "city": clean(entity.get("city")),
                "profile_url": profile_url(entity.get("name"), organization_id),
                "event_date": EVENT_DATE,
                "event_venue": VENUE,
                "source_url": LIST_URL,
                "source_year": "2026",
                "organization_id": organization_id,
            })
        if not data.get("hasMore") or not entities:
            break
        start = int(data.get("nextStartIndex", start + len(entities)))
    unique = {}
    for record in records:
        unique[record["organization_id"]] = record
    return list(unique.values())


def details(record):
    params = {
        **API_PARAMS,
        "organizationid": record["organization_id"],
        "hideNewsdata": "true",
        "showCategoryHierarchy": "false",
    }
    try:
        response = request(
            "POST", f"{API}/companydetails",
            headers={"Accept": "application/xml"},
            data=params,
        )
        root = ET.fromstring(response.content)
        organization = root.find(".//organization") or root
        get = lambda key: clean(organization.attrib.get(key, ""))
        record["exhibitor_name"] = get("name") or record["exhibitor_name"]
        record["domain"] = root_domain(get("web"))
        record["contact_number"] = get("phone")
        record["mail"] = get("email").lower()
        record["country"] = get("country") or record["country"]
        record["city"] = get("city") or record["city"]
        address_parts = [get(key) for key in ("adress1", "adress2", "adress3", "postCode", "city", "country")]
        record["location"] = ", ".join(part for part in address_parts if part)
        description = organization.find(".//description/text")
        if description is not None and description.text:
            record["desc"] = clean(description.text)
    except (requests.RequestException, ET.ParseError) as exc:
        print(f"Profile failed: {record['exhibitor_name']}: {exc}")
    return record


def serper_key():
    env_path = ROOT.parent / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf8").splitlines():
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
        response = request(
            "POST",
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={
                "q": f'"{record["exhibitor_name"]}" official website 2026 GET NORD',
                "gl": "de", "hl": "en", "num": 10,
            },
        )
        data = response.json()
        graph = data.get("knowledgeGraph") or {}
        record["domain"] = root_domain(graph.get("website", ""))
        for result in data.get("organic", []):
            link = result.get("link", "")
            if not record["domain"]:
                record["domain"] = root_domain(link)
            if not record["linkedin_url"] and "linkedin.com/" in link:
                record["linkedin_url"] = link.split("?", 1)[0]
    except requests.RequestException as exc:
        print(f"Serper failed: {record['exhibitor_name']}: {exc}")
    return record


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = listing()
    print(f"Found {len(records)} 2026 organizations")
    with ThreadPoolExecutor(max_workers=16) as pool:
        records = list(pool.map(details, records))
    missing = [record for record in records if not record["domain"]]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(serper_enrich, missing))
    records.sort(key=lambda item: item["exhibitor_name"].casefold())
    base = OUT / f"{EVENT}_exhibitors"
    with base.with_suffix(".csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)
    base.with_suffix(".json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
