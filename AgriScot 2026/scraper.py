import csv
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests


EVENT = "AGRISCOT_2026"
BASE_URL = "https://agriscot.co.uk/exhibitors-list/"
PROXY = "https://r.jina.ai/https://agriscot.co.uk/exhibitors-list"
VENUE = "Royal Highland Centre, Ingliston, Edinburgh, EH28 8NB, United Kingdom"
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "agriscot.co.uk", "wikipedia.org", "yellowpages.com", "yelp.com",
    "thescottishfarmer.co.uk",
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


def fetch_letter(letter):
    url = f"{PROXY}-{letter.lower()}/"
    for attempt in range(5):
        response = requests.get(url, headers=HEADERS, timeout=90)
        if response.status_code == 200:
            return letter, response.text
        time.sleep(3 * (attempt + 1))
    response.raise_for_status()
    return letter, response.text


def parse_page(letter, text):
    records = []
    in_content = False
    for raw_line in text.splitlines():
        line = clean(raw_line)
        if line == "Markdown Content:":
            in_content = True
            continue
        if not in_content or not line or line.startswith(("Title:", "URL Source:", "## Contact Us", "## Quick Links")):
            continue
        if line.startswith("**Company**") or line.startswith("#") or line.startswith("*"):
            continue
        website_match = re.findall(r"\[([^\]]+)\]\((https?://[^)]+)\)", line)
        website = website_match[-1][1] if website_match else ""
        line = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", "", line)
        stand_match = re.search(r"(?<![A-Za-z])(\d{1,3}(?:\s*&\s*\d{1,3})?)\s+(.*)$", line)
        if not stand_match:
            continue
        name = clean(line[:stand_match.start()])
        stand = clean(stand_match.group(1))
        desc = clean(stand_match.group(2))
        if (
            not name
            or name.casefold() in {"company", "website"}
            or name.casefold().startswith(("copyright", "tel:", "email:"))
        ):
            continue
        phone = ""
        phone_match = re.search(r"(?<!\d)(?:\+?\d[\d\s()./-]{7,}\d)(?!\d)", desc)
        if phone_match:
            phone = clean(phone_match.group(0))
        records.append({
            "exhibitor_name": name,
            "domain": root_domain(website),
            "contact_number": phone,
            "mail": "",
            "location": VENUE,
            "country": "United Kingdom",
            "booth_no": stand,
            "desc": desc,
            "linkedin_url": "",
            "city": "Edinburgh",
            "profile_url": f"{BASE_URL}{letter.lower()}/",
            "event_source": BASE_URL,
            "alphabet_section": letter,
        })
    return records


def serper_enrich(record, api_key):
    if record["domain"] or not api_key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website 2026 AgriScot', "gl": "uk", "hl": "en", "num": 10},
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
    with ThreadPoolExecutor(max_workers=3) as pool:
        pages = list(pool.map(fetch_letter, LETTERS))
    records = []
    for letter, text in pages:
        records.extend(parse_page(letter, text))
    unique = {}
    for record in records:
        unique[record["exhibitor_name"].casefold()] = record
    records = list(unique.values())
    api_key = load_api_key()
    missing = [record for record in records if not record["domain"]]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda record: serper_enrich(record, api_key), missing))
    records.sort(key=lambda record: record["exhibitor_name"].casefold())
    fields = [
        "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
        "booth_no", "desc", "linkedin_url", "city", "profile_url", "event_source",
        "alphabet_section",
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
