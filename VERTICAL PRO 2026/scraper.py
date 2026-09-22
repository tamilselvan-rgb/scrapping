import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "VERTICAL_PRO_2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LIST_URL = "https://www.vertical-pro.com/index-of-exhibitors/preliminary-index-of-exhibitors"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
COUNTRIES = {
    "A": "Austria", "AUS": "Australia", "B": "Belgium", "BG": "Bulgaria",
    "CDN": "Canada", "CH": "Switzerland", "CZ": "Czech Republic",
    "D": "Germany", "DK": "Denmark", "E": "Spain", "F": "France",
    "FIN": "Finland", "GB": "United Kingdom", "I": "Italy", "IL": "Israel",
    "IND": "India", "N": "Norway", "NL": "Netherlands", "P": "Portugal",
    "PL": "Poland", "SLO": "Slovenia", "SK": "Slovakia", "USA": "United States",
    "VRC": "China", "LV": "Latvia", "J": "Japan", "RC": "Taiwan",
    "S": "Sweden",
}
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "google.com", "vertical-pro.com",
    "yellowpages.com", "yelp.com",
}


def clean(value):
    value = html.unescape(str(value or "")).replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def root_domain(value):
    if not value:
        return ""
    value = clean(value)
    if value.lower().startswith(("mailto:", "tel:")) or "@" in value:
        return ""
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    host = (urlparse(value).hostname or "").lower().removeprefix("www.")
    if not host or any(host == item or host.endswith("." + item) for item in BLOCKED):
        return ""
    return host


def email_from_text(text):
    match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text or "")
    return match.group(0).lower() if match else ""


def phone_from_text(text):
    for value in re.findall(r"(?<!\w)(?:\+|00)?\d[\d\s()./-]{7,}\d", text or ""):
        value = clean(value)
        digits = re.sub(r"\D", "", value)
        if re.search(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b", value):
            continue
        if 8 <= len(digits) <= 16:
            return value
    return ""


def listing():
    response = requests.get(LIST_URL, headers=HEADERS, timeout=60)
    response.encoding = response.apparent_encoding or "utf-8"
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.find("table")
    records = []
    for row in table.select("tr")[1:]:
        cells = row.select("td")
        if len(cells) < 3:
            continue
        name = clean(cells[0].get_text(" ", strip=True))
        code = clean(cells[1].get_text(" ", strip=True)).upper()
        link = cells[2].select_one("a[href]")
        website = link.get("href", "") if link else clean(cells[2].get_text(" ", strip=True))
        if not name:
            continue
        records.append({
            "exhibitor_name": name,
            "domain": root_domain(website),
            "contact_number": "",
            "mail": "",
            "location": "",
            "country": COUNTRIES.get(code, ""),
            "booth_no": "",
            "desc": "Exhibitor listed for VERTICAL PRO Friedrichshafen 2026.",
            "linkedin_url": "",
            "city": "",
            "profile_url": website or LIST_URL,
        })
    return records


def serper_key():
    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"\'')
    return ""


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
            json={"q": f'"{record["exhibitor_name"]}" official website VERTICAL PRO 2026'},
            timeout=30,
        )
        response.raise_for_status()
        graph = response.json().get("knowledgeGraph", {})
        record["domain"] = root_domain(graph.get("website", ""))
        record["location"] = clean(graph.get("address", ""))
        record["contact_number"] = clean(graph.get("phone", ""))
    except requests.RequestException:
        pass
    return record


def enrich_website(record):
    if not record["domain"]:
        return record
    try:
        response = requests.get("https://" + record["domain"], headers=HEADERS, timeout=25)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text(" ", strip=True)
        record["mail"] = email_from_text(text)
        record["contact_number"] = record["contact_number"] or phone_from_text(text)
        meta = soup.select_one('meta[name="description"], meta[property="og:description"]')
        if meta and meta.get("content"):
            record["desc"] = clean(meta["content"])
        linkedin = soup.select_one('a[href*="linkedin.com/"]')
        if linkedin:
            record["linkedin_url"] = linkedin.get("href", "")
    except requests.RequestException:
        pass
    return record


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = listing()
    print(f"Found {len(records)} official 2026 exhibitors")
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(enrich_domain, records))
    with ThreadPoolExecutor(max_workers=16) as pool:
        records = list(pool.map(enrich_website, records))
    records.sort(key=lambda item: item["exhibitor_name"].lower())
    fields = [
        "exhibitor_name", "domain", "contact_number", "mail", "location",
        "country", "booth_no", "desc", "linkedin_url", "city", "profile_url",
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
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
