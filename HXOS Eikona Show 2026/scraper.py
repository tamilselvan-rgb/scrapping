import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "HXOS_EIKONA_SHOW"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
BASE_URL = "https://highend.show"
LIST_URL = f"{BASE_URL}/"
HEADERS = {"User-Agent": "curl/8.0", "Accept": "*/*"}
BLOCKED = {
    "highend.show", "hxosplus.gr", "facebook.com", "instagram.com",
    "twitter.com", "x.com", "youtube.com", "linkedin.com", "wikipedia.org",
    "yellowpages.com", "yelp.com", "google.com", "10times.com", "kompass.com",
    "tracxn.com", "showthemes.com",
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


def linkedin_url(value):
    value = value or ""
    href = value if value.startswith("http") else "https:" + value
    return href if "linkedin.com/" in href else ""


def plausible_domain(name, domain):
    if not domain:
        return False
    generic = {
        "audio", "audioevolution", "company", "devices", "group", "hi",
        "high", "ltd", "show", "sound", "speakers", "studio", "the",
        "veterans",
    }
    tokens = [
        token for token in re.findall(r"[a-z0-9]+", name.lower())
        if len(token) >= 4 and token not in generic
    ]
    return bool(tokens) and any(token in domain for token in tokens)


def valid_phone(value):
    digits = re.sub(r"\D", "", clean(value))
    return 7 <= len(digits) <= 16


def phone_from_soup(soup):
    tel = soup.select_one('a[href^="tel:"]')
    if tel and valid_phone(tel.get("href", "")[4:]):
        return clean(tel.get("href", "")[4:])
    return ""


def email_from_soup(soup):
    for link in soup.select('a[href^="mailto:"]'):
        value = link["href"].split(":", 1)[1].split("?", 1)[0].strip()
        if "@" in value:
            return value.lower()
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
    for link in soup.select('a[href*="/exhibitor/"]'):
        url = link.get("href", "")
        if url in seen:
            continue
        seen.add(url)
        slug = url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()
        records.append({
            "exhibitor_name": slug,
            "domain": "",
            "contact_number": "",
            "mail": "",
            "location": "",
            "country": "Greece",
            "booth_no": "",
            "desc": "",
            "linkedin_url": "",
            "city": "Athens",
            "profile_url": url,
            "event_date": "2026-11-21 to 2026-11-22",
            "event_venue": "Wyndham Grand Athens, Athens, Greece",
            "source_url": LIST_URL,
            "source_year": "2026",
        })
    if not records:
        raise RuntimeError("No 2026 HXOS Eikona exhibitor profiles found")
    return records


def profile(record):
    try:
        response = requests.get(record["profile_url"], headers=HEADERS, timeout=45)
        response.raise_for_status()
    except requests.RequestException:
        return record
    soup = BeautifulSoup(response.content, "html.parser")
    heading = soup.select_one("main h2, h2")
    if heading:
        record["exhibitor_name"] = clean(heading.get_text(" ", strip=True))
    record["mail"] = email_from_soup(soup)
    record["contact_number"] = phone_from_soup(soup)
    website = next(
        (
            link for link in soup.select('a[href^="http"], a[href^="www."]')
            if root_domain(link.get("href", ""))
        ),
        None,
    )
    if website:
        record["domain"] = root_domain(website.get("href", ""))
    linkedin = soup.select_one('a[href*="linkedin.com/"]')
    if linkedin:
        record["linkedin_url"] = linkedin_url(linkedin.get("href", ""))
    paragraphs = []
    for paragraph in soup.select("main p, .content p"):
        text = clean(paragraph.get_text(" ", strip=True))
        if len(text) > 40 and "contact" not in text.lower():
            paragraphs.append(text)
    if paragraphs:
        record["desc"] = paragraphs[0]
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
            json={"q": f'"{record["exhibitor_name"]}" official website 2026 Greece'},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph", {})
        if not record["contact_number"] and valid_phone(graph.get("phone", "")):
            record["contact_number"] = clean(graph["phone"])
        if not record["location"]:
            record["location"] = clean(graph.get("address", ""))
        candidate = root_domain(graph.get("website", ""))
        record["domain"] = candidate if plausible_domain(record["exhibitor_name"], candidate) else ""
        if not record["domain"]:
            for item in data.get("organic", []):
                candidate = root_domain(item.get("link", ""))
                if plausible_domain(record["exhibitor_name"], candidate):
                    record["domain"] = candidate
                    break
    except requests.RequestException:
        pass
    return record


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = listing()
    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(profile, records))
    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(serper_enrich, records))
    records.sort(key=lambda item: item["exhibitor_name"].casefold())
    base = OUT / f"{EVENT}_2026_exhibitors"
    with base.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    base.with_suffix(".json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Exported {len(records)} 2026 HXOS Eikona exhibitors")
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
