import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests


EVENT = "SPACE_TECH_EXPO_CONFERENCE_EUROPE_2026"
LIST_URL = "https://www.spacetechexpo-europe.com/exhibitor-list/"
API_URL = "https://www.spacetechexpo-europe.com/rest/exhibman.php"
PROFILE_BASE = "https://www.spacetechexpo-europe.com/exhibitor-list/exhibitor/?boothid="
EXPO_ID = "a1xUK000001hXEf"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
VENUE = "Congress Bremen - Messe Bremen, Hallen 4, 5, 6, 7 & 4.1, Findorffstrasse 101, 28215 Bremen, Germany"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "spacetechexpo-europe.com", "wikipedia.org", "yellowpages.com",
    "yelp.com",
}


def clean(value):
    value = html.unescape(str(value or "")).replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def root_domain(value):
    value = clean(value)
    if not value or value.lower().startswith(("mailto:", "tel:")):
        return ""
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    host = (urlparse(value).hostname or "").lower().removeprefix("www.")
    if not host or "." not in host or any(host == x or host.endswith("." + x) for x in BLOCKED):
        return ""
    return host


def country_name(value):
    value = clean(value)
    if value.casefold() == "france, metropolitan":
        return "France"
    return value or "Germany"


def record_from_item(item):
    booth = clean(item.get("exhibitor-booth"))
    profile_url = PROFILE_BASE + clean(item.get("id"))
    return {
        "exhibitor_name": clean(item.get("pagetitle")),
        "domain": root_domain(item.get("url", "")),
        "contact_number": "",
        "mail": "",
        "location": VENUE,
        "country": country_name(item.get("country")),
        "booth_no": booth,
        "desc": clean(item.get("content")),
        "linkedin_url": "",
        "city": "Bremen",
        "profile_url": profile_url,
        "event_source": LIST_URL,
    }


def visit_profile(record):
    try:
        response = requests.get(record["profile_url"], headers=HEADERS, timeout=60)
        response.raise_for_status()
    except Exception as exc:
        print(f"profile failed: {record['exhibitor_name']}: {exc}")
    return record


def serper_enrich(record, api_key):
    if record["domain"] or not api_key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website 2026 space technology', "gl": "de", "hl": "en", "num": 10},
            timeout=45,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph") or {}
        record["domain"] = root_domain(graph.get("website", ""))
        if not record["domain"]:
            for result in data.get("organic", []):
                domain = root_domain(result.get("link", ""))
                if domain:
                    record["domain"] = domain
                    break
        if not record["linkedin_url"]:
            for result in data.get("organic", []):
                if "linkedin.com/company/" in result.get("link", ""):
                    record["linkedin_url"] = result["link"].split("?", 1)[0]
                    break
    except Exception as exc:
        print(f"Serper failed: {record['exhibitor_name']}: {exc}")
    return record


def load_api_records():
    response = requests.get(
        API_URL,
        params={"expos": f"'{EXPO_ID}'"},
        headers={**HEADERS, "Referer": LIST_URL},
        timeout=60,
    )
    response.raise_for_status()
    records = response.json()
    return [item for item in records if item.get("published") and item.get("pagetitle")]


def load_api_key():
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def main():
    OUT.mkdir(exist_ok=True)
    items = load_api_records()
    records = [record_from_item(item) for item in items]
    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(visit_profile, records))
    missing_domains = [record for record in records if not record["domain"]]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda record: serper_enrich(record, load_api_key()), missing_domains))
    records.sort(key=lambda record: record["exhibitor_name"].casefold())
    fields = [
        "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
        "booth_no", "desc", "linkedin_url", "city", "profile_url", "event_source",
    ]
    csv_path = OUT / f"{EVENT}_exhibitors.csv"
    json_path = OUT / f"{EVENT}_exhibitors.json"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf8")
    print(f"Found {len(records)} published 2026 exhibitors")
    print(f"Wrote {csv_path} and {json_path}")


if __name__ == "__main__":
    main()
