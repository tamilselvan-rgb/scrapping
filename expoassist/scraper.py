import csv
import html
import os
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


BASE = "https://expoassist.net"
SEARCH_URL = f"{BASE}/en/event_search"
EVENTS_URL = f"{BASE}/en/events"
ROOT = Path(__file__).resolve().parent
OUT_CSV = ROOT / "expoassist.csv"
OUT_MD = ROOT / "expoassist.md"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ExpoAssistResearch/1.0)"}
FIELDS = [
    "event_name",
    "event_start_date",
    "event_end_date",
    "venue",
    "city",
    "country",
    "event_domain",
]
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com",
    "10times.com", "eventbrite.com", "expoassist.net",
    "whatsapp.com", "maps.app.goo.gl", "google.com",
}


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def domain(value):
    if not value:
        return ""
    value = value.strip()
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if not host or any(host == x or host.endswith("." + x) for x in BLOCKED):
        return ""
    return host


def session():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def get_text(node):
    return clean(node.get_text(" ", strip=True)) if node else ""


def sectors(soup):
    values = []
    for option in soup.select('select[name="sektor_sorgu"] option'):
        value = clean(option.get("value"))
        label = get_text(option)
        if value and label and label.lower() != "select sector":
            values.append(value)
    return list(dict.fromkeys(values))


def query_params(sector, page=1):
    # The portal represents the untouched optional filters with '*'. No
    # country, city, type, year, text or online-event filter is applied.
    return {
        "etkinlik_sorgu": "",
        "sektor_sorgu": sector,
        "bolge_sorgu": "",
        "ulke_sorgu": "*",
        "sehir_sorgu": "*",
        "yil_sorgu": "*",
        "etkinlik_tur_sorgu": "*",
        "online_sorgu": "None",
        "filter": "",
        "page": page,
    }


def result_links(soup):
    links = {}
    for card in soup.select("div.event"):
        link = card.select_one('a[href^="/event/"]:not([href*="/adverts"])')
        if not link:
            continue
        href = urljoin(BASE, link["href"])
        # The event name is taken from the card heading, not the image alt.
        heading = card.select_one("h3")
        name = get_text(heading)
        name = re.sub(r"\s*[|]?\s*Uses POWER Upline Feature\s*$", "", name, flags=re.I)
        if name:
            links[href] = name
    return links


def max_page(soup):
    pages = []
    for link in soup.select('a[href*="page="]'):
        match = re.search(r"[?&]page=(\d+)", link.get("href", ""))
        if match:
            pages.append(int(match.group(1)))
    return max(pages, default=1)


def collect_sector(s, sector):
    found = {}
    first = s.get(EVENTS_URL, params=query_params(sector), timeout=60)
    first.raise_for_status()
    soup = BeautifulSoup(first.content, "html.parser")
    found.update(result_links(soup))
    last = max_page(soup)
    for page in range(2, last + 1):
        response = s.get(EVENTS_URL, params=query_params(sector, page), timeout=60)
        response.raise_for_status()
        found.update(result_links(BeautifulSoup(response.content, "html.parser")))
    return found, last


def parse_list_date(value):
    parts = re.findall(r"\d{1,2}\.\d{1,2}\.\d{4}", value)
    return (parts + ["", ""])[:2]


def detail(record):
    s = session()
    try:
        response = s.get(record["_url"], timeout=60)
        response.raise_for_status()
    except requests.RequestException:
        return record
    soup = BeautifulSoup(response.content, "html.parser")
    # This exact block contains the canonical date/location data.
    date_node = soup.select_one("div.text-larger.text-dark i.icon-calendar3")
    date_text = get_text(date_node.parent if date_node else None)
    dates = parse_list_date(date_text)
    if dates[0]:
        record["event_start_date"], record["event_end_date"] = dates
    location_node = soup.select_one("div.text-larger i.icon-map-marker1")
    location = location_node.parent if location_node else None
    place_links = location.select("a") if location else []
    if len(place_links) >= 3:
        record["country"] = get_text(place_links[0])
        record["city"] = get_text(place_links[1])
        record["venue"] = get_text(place_links[2])
    elif place_links:
        record["country"] = get_text(place_links[0])
    # A real Event Website URL is present on some profiles. Ignore the
    # platform's login-gated empty href and all social/share links.
    for link in soup.find_all("a", href=True):
        if "event website" not in get_text(link).lower():
            continue
        candidate = domain(link.get("href", ""))
        if candidate:
            record["event_domain"] = candidate
            break
    return record


def serper_key():
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if not env_file.exists():
        return os.getenv("SERPER_API_KEY", "")
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"\'')
    return os.getenv("SERPER_API_KEY", "")


def search_domain(record, key):
    if record["event_domain"] or not key:
        return record
    query = f'"{record["event_name"]}" official website {record["city"]} {record["country"]}'
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": query, "num": 10},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        website = data.get("knowledgeGraph", {}).get("website", "")
        record["event_domain"] = domain(website)
        if not record["event_domain"]:
            for result in data.get("organic", []):
                candidate = domain(result.get("link", ""))
                if candidate:
                    record["event_domain"] = candidate
                    break
    except requests.RequestException:
        pass
    time.sleep(0.05)
    return record


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    s = session()
    landing = s.get(SEARCH_URL, timeout=60)
    landing.raise_for_status()
    all_sectors = sectors(BeautifulSoup(landing.content, "html.parser"))
    print(f"Sectors discovered: {len(all_sectors)}")
    records = {}
    occurrences = []
    sector_counts = Counter()
    def collect_one(sector):
        return sector, *collect_sector(session(), sector)

    with ThreadPoolExecutor(max_workers=8) as pool:
        collected = list(pool.map(collect_one, all_sectors))
    for index, (sector, found, pages) in enumerate(collected, 1):
        sector_counts[sector] = len(found)
        for url, name in found.items():
            records.setdefault(url, {
                "event_name": name,
                "event_start_date": "",
                "event_end_date": "",
                "venue": "",
                "city": "",
                "country": "",
                "event_domain": "",
                "_url": url,
            })
            occurrences.append((url, sector))
        print(f"[{index}/{len(all_sectors)}] {sector}: {len(found)} events, {pages} pages")

    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(detail, record) for record in records.values()]
        detailed = [future.result() for future in as_completed(futures)]

    key = serper_key()
    missing = sum(not row["event_domain"] for row in detailed)
    print(f"Detail pages: {len(detailed)}; domains needing search: {missing}")
    if key and missing:
        with ThreadPoolExecutor(max_workers=8) as pool:
            detailed = list(pool.map(lambda row: search_domain(row, key), detailed))
    detailed_by_url = {row["_url"]: row for row in detailed}
    output_rows = []
    for url in records:
        row = dict(detailed_by_url[url])
        output_rows.append(row)
    output_rows.sort(key=lambda row: (row["event_start_date"], row["event_name"].casefold()))
    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in FIELDS} for row in output_rows)
    with OUT_MD.open("w", encoding="utf-8") as handle:
        handle.write("# Expoassist event scrape\n\n")
        handle.write(f"Source: {SEARCH_URL}\n\n")
        handle.write(f"Total event occurrences across sectors: **{len(output_rows)}**\n\n")
        handle.write(f"Total unique events: **{len(detailed)}**\n\n")
        handle.write(
            f"Event domains found: **{sum(bool(row['event_domain']) for row in output_rows)}** "
            f"of **{len(output_rows)}** occurrences.\n\n"
        )
        handle.write("| Sector | Event count |\n|---|---:|\n")
        for sector in all_sectors:
            handle.write(f"| {sector} | {sector_counts[sector]} |\n")
    print(f"Wrote {OUT_CSV}")
    print(f"Wrote {OUT_MD}")


if __name__ == "__main__":
    main()
