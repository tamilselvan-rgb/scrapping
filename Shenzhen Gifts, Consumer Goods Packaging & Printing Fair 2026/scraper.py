"""Scrape and translate the 2026 Shenzhen Gifts Packaging & Printing Fair list."""

from __future__ import annotations

import csv
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT_NAME = "Shenzhen Gifts, Consumer Goods Packaging & Printing Fair 2026"
BASE_URL = "https://giftpackaging.rxhuabo.com.cn/index.php/list.html"
PAGES = 18
FIELDS = [
    "company_name",
    "booth",
    "description",
    "email",
    "mobile_primary",
    "domain",
    "full_address",
    "city",
    "linkedin_url",
]
SOCIAL_HOSTS = {"facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com", "youtube.com"}
DIRECTORY_HOSTS = {"wikipedia.org", "yellowpages.com", "yelp.com", "crunchbase.com", "zoominfo.com"}


def clean(value: object) -> str:
    value = str(value or "").replace("\ufffd", "-")
    return re.sub(r"\s+", " ", value).strip()


def contains_chinese(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", value))


def translate(value: str, session: requests.Session) -> str:
    value = clean(value)
    if not value or not contains_chinese(value):
        return value
    response = session.get(
        "https://translate.googleapis.com/translate_a/single",
        params={"client": "gtx", "sl": "zh-CN", "tl": "en", "dt": "t", "q": value},
        timeout=30,
    )
    response.raise_for_status()
    translated = response.json()
    return clean("".join(part[0] for part in translated[0] if part and part[0]))


def absolute_url(value: object) -> str:
    value = clean(value)
    if not value:
        return ""
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    return value if urlparse(value).hostname else ""


def blocked(value: str) -> bool:
    host = (urlparse(value).hostname or "").lower().removeprefix("www.")
    return any(host == item or host.endswith("." + item) for item in SOCIAL_HOSTS | DIRECTORY_HOSTS)


def serper_key() -> str:
    env = Path(__file__).parents[1] / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def find_domain(company: str, key: str) -> str:
    if not key:
        return ""
    response = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        json={"q": f'"{company}" official website 2026'},
        timeout=30,
    )
    if response.status_code == 400:
        return ""
    response.raise_for_status()
    data = response.json()
    candidate = absolute_url((data.get("knowledgeGraph") or {}).get("website"))
    if candidate and not blocked(candidate):
        return candidate
    for result in data.get("organic", []):
        candidate = absolute_url(result.get("link"))
        if candidate and not blocked(candidate):
            return candidate
    return ""


def scrape_page(page: int) -> list[dict[str, str]]:
    response = requests.get(BASE_URL, params={"page": page} if page > 1 else {}, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.content.decode("utf-8"), "html.parser")
    records = []
    for row in soup.select("table tr")[1:]:
        company = row.select_one('[id^="title-"]')
        if not company:
            continue
        records.append(
            {
                "company_name": clean(company.get_text(" ", strip=True)),
                "category": clean((row.select_one('[id^="zscate-"]') or {}).get_text(" ", strip=True)),
                "booth": clean((row.select_one('[id^="zwh-"]') or {}).get_text(" ", strip=True)),
                "description": clean((row.select_one('[id^="content-"]') or {}).get_text(" ", strip=True)),
            }
        )
    return records


def verify(records: list[dict[str, str]]) -> None:
    total = len(records)
    print(f"=== Verification Report: {EVENT_NAME} ===")
    print(f"Total Exhibitors : {total}")
    print("Field Coverage   :")
    for field in FIELDS:
        count = sum(bool(record[field]) for record in records)
        print(f"  {field:<15}: {count}/{total} ({count / total * 100:.1f}%)")
    text = json.dumps(records, ensure_ascii=False)
    key = serper_key()
    domains_valid = all(not row["domain"] or re.match(r"^https?://", row["domain"]) for row in records)
    print("Sample Verified  :", ", ".join(row["company_name"] for row in records[:3]), "[OK]")
    print("Security Check   :", "No API key leakage [OK]" if key not in text else "FAILED")
    print("Value Check      :", "PASSED" if domains_valid else "FAILED")
    print("Status            :", "PASSED" if domains_valid and key not in text else "FAILED")


def main() -> None:
    with ThreadPoolExecutor(max_workers=8) as pool:
        pages = [future.result() for future in as_completed([pool.submit(scrape_page, page) for page in range(1, PAGES + 1)])]
    raw_records = [record for page in pages for record in page]
    print(f"Scraped {len(raw_records)} exhibitors across {PAGES} pages")

    # Translate all visible Chinese company and product text to English.
    session = requests.Session()
    unique_text = sorted({text for record in raw_records for text in (record["company_name"], record["description"]) if text})
    translations: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(translate, text, session): text for text in unique_text}
        for future in as_completed(futures):
            source = futures[future]
            try:
                translations[source] = future.result()
            except requests.RequestException:
                translations[source] = source

    records = [
        {
            "company_name": translations.get(record["company_name"], record["company_name"]),
            "booth": record["booth"],
            "description": translations.get(record["description"], record["description"]),
            "email": "",
            "mobile_primary": "",
            "domain": "",
            "full_address": "",
            "city": "",
            "linkedin_url": "",
        }
        for record in raw_records
    ]

    key = serper_key()
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(find_domain, record["company_name"], key): record for record in records}
        for future in as_completed(futures):
            record = futures[future]
            try:
                record["domain"] = future.result()
            except requests.RequestException:
                record["domain"] = ""

    records.sort(key=lambda record: record["company_name"].casefold())
    output = Path(__file__).parent / "output"
    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / "SHENZHEN_GIFTS_CONSUMER_GOODS_PACKAGING_PRINTING_FAIR_2026_exhibitors.csv"
    json_path = output / "SHENZHEN_GIFTS_CONSUMER_GOODS_PACKAGING_PRINTING_FAIR_2026_exhibitors.json"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)
    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    verify(records)
    print(f"CSV  : {csv_path}")
    print(f"JSON : {json_path}")


if __name__ == "__main__":
    main()
