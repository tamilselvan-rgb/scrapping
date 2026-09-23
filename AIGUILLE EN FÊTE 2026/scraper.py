import csv
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests


EVENT = "AIGUILLE_EN_FÊTE_2026"
LISTING_URL = "https://www.creations-savoir-faire.com/en/list-of-exhibitors/exhibitors"
PROXY_BASE = "https://r.jina.ai/" + LISTING_URL
VENUE = "Paris Expo Porte de Versailles, 1 Place de la Porte de Versailles, 75015 Paris, France"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com",
    "creations-savoir-faire.com", "comexposium.com",
}


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(str(value or "")).replace("\xa0", " ")).strip()


def root_domain(value):
    value = clean(value)
    if not value or value.lower().startswith(("mailto:", "tel:")):
        return ""
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    host = (urlparse(value).hostname or "").lower().removeprefix("www.")
    if not host or "." not in host or any(host == item or host.endswith("." + item) for item in BLOCKED):
        return ""
    return host


def fetch(url):
    for attempt in range(5):
        response = requests.get(url, headers=HEADERS, timeout=90)
        if response.status_code == 200:
            return response.text
        time.sleep(2 * (attempt + 1))
    response.raise_for_status()


def fetch_listing(page):
    url = PROXY_BASE if page == 1 else f"{PROXY_BASE}?page={page}"
    return page, fetch(url)


def parse_listing(page, text):
    records = []
    pattern = re.compile(
        r"\[([^\]]+)\]\((https://www\.creations-savoir-faire\.com/en/list-of-exhibitors/Exposant/[^)]+)\)"
    )
    for match in pattern.finditer(text):
        label = clean(match.group(1))
        profile_url = match.group(2)
        if "###" in label:
            booth, name = (clean(part) for part in label.split("###", 1))
        else:
            booth, name = "", label
        if not name or name.casefold() in {"see more exhibitors"}:
            continue
        records.append({
            "exhibitor_name": name,
            "domain": "",
            "contact_number": "",
            "mail": "",
            "location": VENUE,
            "country": "France",
            "booth_no": booth,
            "desc": "",
            "linkedin_url": "",
            "city": "Paris",
            "profile_url": profile_url,
            "event_source": LISTING_URL,
            "event_year": "2026",
            "profile_checked": "yes",
        })
    return records


def visit_profile(record):
    # Visit every published profile. The site currently returns a shell for
    # these JavaScript-rendered pages through the text proxy; parse any contact
    # links that are exposed if the profile becomes server-rendered.
    try:
        text = fetch("https://r.jina.ai/" + record["profile_url"])
    except Exception as exc:
        print(f"Profile failed: {record['exhibitor_name']}: {exc}")
        return record
    emails = re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
    if emails:
        record["mail"] = emails[0]
    phones = re.findall(r"(?<!\d)(?:\+?\d[\d\s()./-]{7,}\d)(?!\d)", text)
    if phones:
        record["contact_number"] = clean(phones[0])
    links = re.findall(r"https?://[^\s)>\"]+", text)
    for link in links:
        domain = root_domain(link)
        if domain:
            record["domain"] = domain
            break
    for link in links:
        if "linkedin.com/" in link.lower():
            record["linkedin_url"] = link.split("?", 1)[0]
            break
    return record


def load_api_key():
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def serper_enrich(record, api_key):
    if record["domain"] or not api_key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website 2026 Aiguille en Fête', "gl": "fr", "hl": "en", "num": 10},
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
        for result in data.get("organic", []):
            link = result.get("link", "")
            if not record["linkedin_url"] and "linkedin.com/" in link:
                record["linkedin_url"] = link.split("?", 1)[0]
    except Exception as exc:
        print(f"Serper failed: {record['exhibitor_name']}: {exc}")
    return record


def main():
    output = Path(__file__).resolve().parent / "output"
    output.mkdir(exist_ok=True)
    csv_path = output / f"{EVENT}_exhibitors.csv"
    json_path = output / f"{EVENT}_exhibitors.json"
    existing = []
    if csv_path.exists():
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            existing = list(csv.DictReader(handle))
    with ThreadPoolExecutor(max_workers=4) as pool:
        pages = list(pool.map(fetch_listing, range(1, 8)))
    published = []
    for page, text in pages:
        published.extend(parse_listing(page, text))
    unique = {}
    for record in published:
        unique[record["profile_url"]] = record
    records = existing + [
        record for profile_url, record in unique.items()
        if profile_url not in {item.get("profile_url") for item in existing}
    ]
    new_records = records[len(existing):]
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = existing + list(pool.map(visit_profile, new_records))
    api_key = load_api_key()
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = existing + list(pool.map(lambda item: serper_enrich(item, api_key), new_records))
    records.sort(key=lambda item: item["exhibitor_name"].casefold())
    fields = [
        "exhibitor_name", "domain", "contact_number", "mail", "location",
        "country", "booth_no", "desc", "linkedin_url", "city", "profile_url",
        "event_source", "event_year", "profile_checked",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf8")
    print(f"Found {len(records)} exhibitors")
    print(f"Wrote {csv_path}")
    print(f"Wrote {json_path}")


if __name__ == "__main__":
    main()
