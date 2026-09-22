import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "ENERGETICS_LUBLIN_2026"
LIST_URL = "https://energetics.targi.lublin.pl/lista-wystawcow/"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
VENUE = "Targi Lublin, ul. Dworcowa 11, 20-406 Lublin, Poland"
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "energetics.targi.lublin.pl",
    "yellowpages.com", "yelp.com",
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


def parse_listing():
    response = requests.get(LIST_URL, headers=HEADERS, timeout=60)
    response.encoding = response.apparent_encoding or "utf-8"
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    records = {}
    for card in soup.select(".exhibitors-grid .exhibitor-box"):
        heading = card.select_one("h2")
        if not heading:
            continue
        name = clean(heading.get_text(" ", strip=True))
        website = card.select_one(".website a[href]")
        stand = card.select_one(".stand")
        stand_text = clean(stand.get_text(" ", strip=True)) if stand else ""
        stand_text = re.sub(r"^Stanowisko:\s*", "", stand_text, flags=re.I)
        records[name.casefold()] = {
            "exhibitor_name": name,
            "domain": root_domain(website.get("href", "") if website else ""),
            "contact_number": "",
            "mail": "",
            "location": VENUE,
            "country": "Poland",
            "booth_no": stand_text,
            "desc": "",
            "linkedin_url": "",
            "city": "Lublin",
            "event_location": VENUE,
            "profile_url": "",
            "event_source": LIST_URL,
        }
    return list(records.values())


def serper_key():
    env = Path(__file__).resolve().parents[1] / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"\'')
    return ""


def relevant(result, name):
    title = clean(result.get("title", "")).casefold()
    host = (urlparse(result.get("link", "")).hostname or "").lower()
    normalized_name = re.sub(r"[^a-z0-9]", "", name.casefold())
    normalized_title = re.sub(r"[^a-z0-9]", "", title)
    normalized_host = re.sub(r"[^a-z0-9]", "", host)
    if normalized_name and normalized_name in normalized_title:
        return True
    tokens = [token for token in re.findall(r"[a-z0-9]{4,}", name.casefold())]
    return len(tokens) >= 2 and all(token in normalized_host for token in tokens[:2])


def enrich_domain(record):
    if record["domain"]:
        return record
    key = serper_key()
    if not key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website Energetics Lublin 2026'},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        record["domain"] = root_domain(data.get("knowledgeGraph", {}).get("website", ""))
        if not record["domain"]:
            for result in data.get("organic", []):
                candidate = root_domain(result.get("link", ""))
                if candidate and relevant(result, record["exhibitor_name"]):
                    record["domain"] = candidate
                    break
    except requests.RequestException:
        pass
    return record


def main():
    records = parse_listing()
    print(f"Found {len(records)} Energetics Lublin 2026 exhibitors")
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(enrich_domain, records))
    records.sort(key=lambda item: item["exhibitor_name"].casefold())
    OUT.mkdir(parents=True, exist_ok=True)
    fields = [
        "exhibitor_name", "domain", "contact_number", "mail", "location",
        "country", "booth_no", "desc", "linkedin_url", "city",
        "event_location", "profile_url", "event_source",
    ]
    base = OUT / f"{EVENT}_exhibitors"
    with base.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    base.with_suffix(".json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Scraped {len(records)} exhibitors")


if __name__ == "__main__":
    main()
