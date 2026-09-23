import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "DATACENTRES_IRELAND_2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LIST_URL = "https://www.datacentres-ireland.com/exhibitors-2026/"
BASE_URL = "https://www.datacentres-ireland.com/"
VENUE = "RDS Venue, Dublin, Ireland"
EVENT_DATE = "2026-11-18 to 2026-11-19"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ExhibitorResearch/1.0)"}
BLOCKED = {
    "datacentres-ireland.com", "facebook.com", "instagram.com", "linkedin.com",
    "twitter.com", "x.com", "youtube.com", "wikipedia.org", "yellowpages.com",
    "yelp.com", "google.com",
}
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location",
    "country", "booth_no", "desc", "linkedin_url", "city", "profile_url",
    "event_date", "event_venue", "source_url", "source_year",
]


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
    if not host or "." not in host:
        return ""
    if any(host == item or host.endswith("." + item) for item in BLOCKED):
        return ""
    return host


def request(url):
    response = requests.get(url, headers=HEADERS, timeout=60)
    response.raise_for_status()
    return response.content


def listing():
    soup = BeautifulSoup(request(LIST_URL), "html.parser")
    records = []
    seen = set()
    for link in soup.select("a[href*='/exhibitor/']"):
        profile_url = urljoin(LIST_URL, link.get("href", ""))
        if profile_url.rstrip("/") == LIST_URL.rstrip("/") or profile_url in seen:
            continue
        name = clean(link.get_text(" ", strip=True))
        if not name or name.casefold() in {"exhibitors 2026", "view profile"}:
            continue
        seen.add(profile_url)
        parent_text = clean(link.parent.get_text(" ", strip=True))
        stand_match = re.search(r"\bStand\s+([A-Za-z0-9]+)", parent_text, re.I)
        records.append({
            "exhibitor_name": name,
            "domain": "",
            "contact_number": "",
            "mail": "",
            "location": "",
            "country": "",
            "booth_no": f"Stand {stand_match.group(1)}" if stand_match else "",
            "desc": "",
            "linkedin_url": "",
            "city": "",
            "profile_url": profile_url,
            "event_date": EVENT_DATE,
            "event_venue": VENUE,
            "source_url": LIST_URL,
            "source_year": "2026",
        })
    if not records:
        raise RuntimeError("No 2026 DataCentres Ireland exhibitors found")
    return records


def labelled_text(text, label, following):
    match = re.search(
        rf"{re.escape(label)}\s*:?\s*(.*?)(?=\s+{re.escape(following)}\s*:?(?:\s|$)|\Z)",
        text, re.I,
    )
    return clean(match.group(1)) if match else ""


def profile(record):
    try:
        soup = BeautifulSoup(request(record["profile_url"]), "html.parser")
    except requests.RequestException as exc:
        print(f"Profile failed: {record['exhibitor_name']}: {exc}")
        return record
    content = soup.select_one("main, article, .entry-content") or soup
    text = clean(content.get_text(" ", strip=True))
    record["booth_no"] = labelled_text(text, "Stand", "Category") or record["booth_no"]
    record["contact_number"] = labelled_text(text, "Telephone", "Email")
    record["mail"] = labelled_text(text, "Email", "Website").lower()
    record["mail"] = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", record["mail"]).group(0) if re.search(
        r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", record["mail"]
    ) else ""
    website = labelled_text(text, "Website", "Address")
    record["domain"] = root_domain(website)
    address = labelled_text(text, "Address", "Company Profile")
    record["location"] = address
    record["country"] = "Ireland" if address else ""
    if address:
        parts = [clean(part) for part in re.split(r",|\n", address) if clean(part)]
        record["city"] = parts[-2] if len(parts) > 1 else ""
        if "United Kingdom" in address:
            record["country"] = "United Kingdom"
        elif "Ireland" in address:
            record["country"] = "Ireland"
    description = labelled_text(text, "Company Profile", "Back")
    record["desc"] = description
    for link in content.select("a[href]"):
        href = link.get("href", "")
        if "linkedin.com/" in href.lower():
            record["linkedin_url"] = href
            break
        if not record["domain"]:
            candidate = root_domain(href)
            if candidate:
                record["domain"] = candidate
    return record


def serper_key():
    path = ROOT.parent / ".env"
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf8").splitlines():
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
                "q": f'"{record["exhibitor_name"]}" official website 2026 DataCentres Ireland',
                "gl": "ie", "hl": "en", "num": 10,
            },
            timeout=45,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph") or {}
        record["domain"] = root_domain(graph.get("website", ""))
        for item in data.get("organic", []):
            link = item.get("link", "")
            if not record["domain"]:
                record["domain"] = root_domain(link)
            if not record["linkedin_url"] and "linkedin.com/" in link:
                record["linkedin_url"] = link.split("?", 1)[0]
    except requests.RequestException as exc:
        print(f"Serper failed: {record['exhibitor_name']}: {exc}")
    return record


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = listing()
    with ThreadPoolExecutor(max_workers=10) as pool:
        records = list(pool.map(profile, records))
    missing = [record for record in records if not record["domain"]]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(serper_enrich, missing))
    records.sort(key=lambda item: item["exhibitor_name"].casefold())
    base = OUT / f"{EVENT}_exhibitors"
    with base.with_suffix(".csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)
    base.with_suffix(".json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print(f"Exported {len(records)} 2026 DataCentres Ireland exhibitors")
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
