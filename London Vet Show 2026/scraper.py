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


EVENT = "LONDON_VET_SHOW_2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LIST_URL = "https://london.vetshow.com/exhibitor-list"
BASE_URL = "https://london.vetshow.com/"
EVENT_DATE = "2026-11-19 to 2026-11-20"
VENUE = "Excel London, Royal Victoria Dock, Western Gateway, London E16 1XL, United Kingdom"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ExhibitorResearch/1.0)",
    "Referer": LIST_URL,
}
BLOCKED = {
    "london.vetshow.com", "facebook.com", "instagram.com", "linkedin.com",
    "twitter.com", "x.com", "youtube.com", "wikipedia.org", "yellowpages.com",
    "yelp.com", "google.com",
}
FIELDS = [
    "company_name", "domain", "description", "booth", "email", "city",
    "full_address", "mobile_primary",
]


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def root_domain(value):
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
    for item in soup.select("li.m-exhibitors-list__items__item"):
        link = item.find("a", href=re.compile(r"(?:^|/)exhibitors/"))
        if not link:
            continue
        profile_url = urljoin(LIST_URL, link.get("href", ""))
        if profile_url in seen:
            continue
        seen.add(profile_url)
        name = clean(link.get("aria-label") or link.get_text(" ", strip=True))
        stand = clean(item.select_one(
            ".m-exhibitors-list__items__item__header__meta__stand"
        ).get_text(" ", strip=True)) if item.select_one(
            ".m-exhibitors-list__items__item__header__meta__stand"
        ) else ""
        description = clean(item.select_one(
            ".m-exhibitors-list__items__item__body__description"
        ).get_text(" ", strip=True)) if item.select_one(
            ".m-exhibitors-list__items__item__body__description"
        ) else ""
        records.append({
            "company_name": name,
            "domain": "",
            "description": description,
            "booth": stand,
            "email": "",
            "city": "London",
            "full_address": "",
            "mobile_primary": "",
            "profile_url": profile_url,
        })
    if not records:
        raise RuntimeError("No 2026 London Vet Show exhibitors found")
    return records


def parse_address(address_element):
    parts = [
        clean(part)
        for part in re.split(r"[\r\n]+", address_element.get_text("\n", strip=True))
    ]
    if parts and parts[0].casefold() == "address":
        parts.pop(0)
    parts = [part for part in parts if part]
    country = parts[-1] if parts else ""
    postcode_index = next(
        (index for index, part in enumerate(parts)
         if re.search(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", part, re.I)),
        -1,
    )
    if country in {"United Kingdom", "United States"} and postcode_index > 1:
        city = parts[postcode_index - 2]
    else:
        city = parts[postcode_index - 1] if postcode_index > 0 else ""
    return ", ".join(parts), city, country


def profile(record):
    try:
        soup = BeautifulSoup(fetch(record["profile_url"]), "html.parser")
    except requests.RequestException as exc:
        print(f"Profile failed: {record['company_name']}: {exc}")
        return record
    heading = soup.select_one("h1")
    if heading and clean(heading.get_text(" ", strip=True)):
        record["company_name"] = clean(heading.get_text(" ", strip=True))
    stand = soup.select_one(".m-exhibitor-entry__item__header__meta__stand")
    if stand:
        record["booth"] = clean(stand.get_text(" ", strip=True))
    description = soup.select_one(".m-exhibitor-entry__item__body__description")
    if description:
        record["description"] = clean(description.get_text(" ", strip=True))
    address = soup.select_one(".m-exhibitor-entry__item__body__contacts__address")
    if address:
        record["full_address"], city, _ = parse_address(address)
        if city:
            record["city"] = city
    website = next(
        (link.get("href", "") for link in soup.select("a[href]")
         if "visit website" in clean(link.get_text(" ", strip=True)).casefold()),
        "",
    )
    record["domain"] = root_domain(website)
    record["email"] = ""
    phone = soup.select_one("a[href^='tel:']")
    if phone:
        record["mobile_primary"] = clean(phone.get("href", "").split(":", 1)[1])
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
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={
                "q": f'"{record["company_name"]}" official website 2026 London Vet Show',
                "gl": "uk", "hl": "en", "num": 10,
            },
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
    except requests.RequestException as exc:
        print(f"Serper failed: {record['company_name']}: {exc}")
    return record


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = listing()
    print(f"Found {len(records)} 2026 exhibitors")
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(profile, records))
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(serper_enrich, [record for record in records if not record["domain"]]))
    records.sort(key=lambda item: item["company_name"].casefold())
    base = OUT / f"{EVENT}_exhibitors"
    with base.with_suffix(".csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows({field: record.get(field, "") for field in FIELDS} for record in records)
    base.with_suffix(".json").write_text(
        json.dumps([{field: record.get(field, "") for field in FIELDS} for record in records],
                   ensure_ascii=False, indent=2),
        encoding="utf8",
    )
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
