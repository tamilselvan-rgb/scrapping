import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "MOVERS_AND_STORERS_SHOW"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
BASE_URL = "https://moversandstorersshow.com/"
LIST_URL = urljoin(BASE_URL, "exhibitor-list/")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ExhibitorResearch/1.0)"}
BLOCKED = {
    "moversandstorersshow.com", "facebook.com", "instagram.com",
    "twitter.com", "x.com", "youtube.com", "linkedin.com",
    "wikipedia.org", "yellowpages.com", "yelp.com", "google.com",
    "10times.com", "kompass.com",
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
    if not value:
        return ""
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value.strip()
    host = (urlparse(value).hostname or "").lower().removeprefix("www.")
    if not host or any(host == item or host.endswith("." + item) for item in BLOCKED):
        return ""
    return host


def country_name(value):
    names = {
        "GB": "United Kingdom", "UK": "United Kingdom",
        "US": "United States", "USA": "United States",
        "CA": "Canada", "AU": "Australia",
    }
    value = clean(value)
    return names.get(value.upper(), value)


def valid_phone(value):
    digits = re.sub(r"\D", "", clean(value))
    return 7 <= len(digits) <= 16


def phone_from_text(text):
    for match in re.findall(r"(?:\+?\d[\d\s().-]{7,}\d)", text):
        value = clean(match)
        if valid_phone(value):
            return value
    return ""


def serper_key():
    env = ROOT.parent / ".env"
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"\'')
    return ""


def listing():
    response = requests.get(LIST_URL, headers=HEADERS, timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    records = []
    seen = set()
    for item in soup.select(".exhibitorListExhibitor"):
        link = item.select_one("a[href*='/exhibitors/']")
        if not link:
            continue
        profile_url = urljoin(LIST_URL, link.get("href", ""))
        if profile_url in seen:
            continue
        seen.add(profile_url)
        stand = clean(item.get_text(" ", strip=True))
        stand = clean(stand.replace(link.get_text(" ", strip=True), "", 1))
        records.append({
            "exhibitor_name": clean(link.get_text(" ", strip=True)),
            "domain": "",
            "contact_number": "",
            "mail": "",
            "location": "",
            "country": "",
            "booth_no": stand,
            "desc": "",
            "linkedin_url": "",
            "city": "",
            "profile_url": profile_url,
            "event_date": "2026-11-17 to 2026-11-18",
            "event_venue": "NAEC Stoneleigh, Warwickshire, United Kingdom",
            "source_url": LIST_URL,
            "source_year": "2026",
        })
    if not records:
        raise RuntimeError("No 2026 Movers and Storers exhibitors found")
    return records


def profile(record):
    try:
        response = requests.get(record["profile_url"], headers=HEADERS, timeout=45)
        response.raise_for_status()
    except requests.RequestException:
        return record
    soup = BeautifulSoup(response.content, "html.parser")
    content = soup.select_one("main, article, .entry-content") or soup
    external = next(
        (
            link for link in content.select("a[href]")
            if root_domain(link.get("href", ""))
            and "visit website" in clean(link.get_text(" ", strip=True)).lower()
        ),
        None,
    )
    if external:
        record["domain"] = root_domain(external.get("href", ""))
    record["mail"] = next(
        (
            link["href"].split(":", 1)[1].split("?", 1)[0].strip().lower()
            for link in content.select('a[href^="mailto:"]')
            if "@" in link.get("href", "")
        ),
        "",
    )
    text = clean(content.get_text(" ", strip=True))
    record["contact_number"] = phone_from_text(text)
    linkedin = next(
        (link.get("href") for link in content.select('a[href*="linkedin.com/"]')),
        "",
    )
    record["linkedin_url"] = linkedin or ""
    paragraphs = []
    for paragraph in content.select("p"):
        value = clean(paragraph.get_text(" ", strip=True))
        if not value or value.lower() in {"visit website", "contact"}:
            continue
        if "2025" in value:
            continue
        if not re.search(r"required|captcha|your name|telephone number|email", value, re.I):
            paragraphs.append(value)
    description = " ".join(dict.fromkeys(paragraphs))
    description = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "", description)
    description = re.sub(r"(?<!\w)(?:\+?44[\s().-]*)?\d(?:[\d\s().-]{7,}\d)(?!\w)", "", description)
    record["desc"] = clean(description)
    return record


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
            json={"q": f'"{record["exhibitor_name"]}" official website 2026 UK'},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph", {})
        candidate = root_domain(graph.get("website", ""))
        if candidate:
            record["domain"] = candidate
        if not record["contact_number"] and valid_phone(graph.get("phone", "")):
            record["contact_number"] = clean(graph["phone"])
        if not record["location"]:
            record["location"] = clean(graph.get("address", ""))
        if not record["linkedin_url"]:
            for item in data.get("organic", []):
                link = item.get("link", "")
                if "linkedin.com/company/" in link:
                    record["linkedin_url"] = link
                    break
    except requests.RequestException:
        pass
    return record


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = listing()
    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(profile, records))
        records = list(pool.map(serper_enrich, records))
    records.sort(key=lambda item: (item["exhibitor_name"].casefold(), item["profile_url"]))
    base = OUT / f"{EVENT}_2026_exhibitors"
    with base.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    base.with_suffix(".json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Exported {len(records)} 2026 Movers and Storers exhibitors")
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
