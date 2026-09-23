import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "THE_DA_FORUM_2026"
LIST_URL = "https://www.leforumdelada.com/page/exposants/"
API_URL = "https://api.digitevent.com/site/events/68f7bd862ff7bde163bb613a/exhibitorSpace/exhibitors"
VENUE = "73 Boulevard de la Croisette, 06400 Cannes, France"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "leforumdelada.com", "wikipedia.org", "yellowpages.com",
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


def translate_text(value):
    text = clean(BeautifulSoup(value, "html.parser").get_text(" ", strip=True))
    if not text:
        return ""
    try:
        response = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "fr", "tl": "en", "dt": "t", "q": text},
            headers=HEADERS,
            timeout=45,
        )
        response.raise_for_status()
        return clean(" ".join(part[0] for part in response.json()[0] if part and part[0]))
    except Exception as exc:
        print(f"translation failed: {exc}")
        return text


def record_from_item(item):
    social = item.get("socialNetworks") or {}
    return {
        "exhibitor_name": clean(item.get("name")),
        "domain": root_domain(item.get("ctaLink", "")),
        "contact_number": "",
        "mail": "",
        "location": VENUE,
        "country": "France",
        "booth_no": clean(item.get("boothLocation")),
        "desc": clean(item.get("description")),
        "linkedin_url": clean(social.get("linkedin")),
        "city": "Cannes",
        "profile_url": LIST_URL,
        "event_source": LIST_URL,
        "partner_id": clean(item.get("partnerId")),
        "slogan": clean(item.get("slogan")),
    }


def serper_enrich(record, api_key):
    if record["domain"] or not api_key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website 2026 vending', "gl": "fr", "hl": "en", "num": 10},
            timeout=45,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph") or {}
        record["domain"] = root_domain(graph.get("website", ""))
        for result in data.get("organic", []):
            if not record["domain"]:
                record["domain"] = root_domain(result.get("link", ""))
            if not record["linkedin_url"] and "linkedin.com/" in result.get("link", ""):
                record["linkedin_url"] = result["link"].split("?", 1)[0]
    except Exception as exc:
        print(f"Serper failed: {record['exhibitor_name']}: {exc}")
    return record


def load_api_key():
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def main():
    out = Path(__file__).resolve().parent / "output"
    out.mkdir(exist_ok=True)
    response = requests.get(
        API_URL,
        params={"page": 1, "perPage": 50},
        headers={**HEADERS, "Origin": "https://www.leforumdelada.com", "Referer": LIST_URL},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    records = [record_from_item(item) for item in payload.get("exhibitors", [])]
    with ThreadPoolExecutor(max_workers=6) as pool:
        descriptions = list(pool.map(lambda r: translate_text(r["desc"]), records))
    for record, description in zip(records, descriptions):
        record["desc"] = description
    api_key = load_api_key()
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda r: serper_enrich(r, api_key), records))
    records.sort(key=lambda r: r["exhibitor_name"].casefold())
    fields = [
        "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
        "booth_no", "desc", "linkedin_url", "city", "profile_url", "event_source",
        "partner_id", "slogan",
    ]
    csv_path = out / f"{EVENT}_exhibitors.csv"
    json_path = out / f"{EVENT}_exhibitors.json"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf8")
    print(f"Found {len(records)} published 2026 exhibitors")
    print(f"Wrote {csv_path} and {json_path}")


if __name__ == "__main__":
    main()
