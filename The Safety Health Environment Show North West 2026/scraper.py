import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "THE_SAFETY_HEALTH_ENVIRONMENT_SHOW_NORTH_WEST_2026"
SOURCE = "https://thesheshow.com/northwest/exhibitor-profiles/"
VENUE = "Old Trafford, The Home of Manchester United, Sir Matt Busby Way, Manchester, M16 0RA, United Kingdom"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "thesheshow.com", "wikipedia.org", "yellowpages.com", "yelp.com",
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


def extract_email(text):
    match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
    return match.group(0) if match else ""


def extract_phone(text):
    match = re.search(r"(?<!\d)(?:\+?\d[\d\s()./-]{7,}\d)(?!\d)", text)
    return clean(match.group(0)) if match else ""


def parse_listing(soup):
    records = []
    for card in soup.select(".fusion-person"):
        stand_node = card.select_one(".person-name")
        name_node = card.select_one(".person-title")
        content_node = card.select_one(".person-content")
        if not stand_node or not name_node:
            continue
        stand = clean(stand_node.get_text(" ", strip=True))
        if not re.fullmatch(r"Stand\s+\d+", stand, re.I):
            continue
        name = clean(name_node.get_text(" ", strip=True))
        description = clean(content_node.get_text(" ", strip=True) if content_node else "")
        website = ""
        image_link = card.select_one(".person-image-container a[href]")
        if image_link:
            website = image_link.get("href", "")
        if not root_domain(website):
            visit_match = re.search(r"\bVisit:\s*(\S+)", description, re.I)
            website = visit_match.group(1).rstrip(".,)") if visit_match else website
        linkedin = ""
        for link in card.select('a[href*="linkedin.com/"]'):
            linkedin = link.get("href", "").split("?", 1)[0].strip()
            break
        records.append({
            "exhibitor_name": name,
            "domain": root_domain(website),
            "contact_number": extract_phone(description),
            "mail": extract_email(description),
            "location": VENUE,
            "country": "United Kingdom",
            "booth_no": stand,
            "desc": description,
            "linkedin_url": linkedin,
            "city": "Manchester",
            "profile_url": SOURCE,
            "event_source": SOURCE,
        })
    unique = {}
    for record in records:
        unique[record["exhibitor_name"].casefold()] = record
    return list(unique.values())


def serper_enrich(record, api_key):
    if record["domain"] or not api_key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website 2026 Manchester', "gl": "uk", "hl": "en", "num": 10},
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
    response = requests.get(SOURCE, headers=HEADERS, timeout=60)
    response.raise_for_status()
    records = parse_listing(BeautifulSoup(response.text, "html.parser"))
    api_key = load_api_key()
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda record: serper_enrich(record, api_key), records))
    records.sort(key=lambda record: record["exhibitor_name"].casefold())
    fields = [
        "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
        "booth_no", "desc", "linkedin_url", "city", "profile_url", "event_source",
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
