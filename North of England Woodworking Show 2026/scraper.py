import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "NORTH_OF_ENGLAND_WOODWORKING_SHOW"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
BASE_URL = "https://www.harrogatewoodworkingshow.co.uk"
LIST_URL = f"{BASE_URL}/exhibitors-demonstrators"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "harrogatewoodworkingshow.co.uk", "linkedin.com", "facebook.com",
    "instagram.com", "twitter.com", "x.com", "youtube.com", "wikipedia.org",
    "yellowpages.com", "yelp.com", "google.com", "10times.com", "kompass.com",
    "tracxn.com", "tiktok.com",
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


def plausible_domain(name, domain):
    generic = {
        "ltd", "company", "tools", "woodworking", "woodturning", "club",
        "association", "products", "technology", "the", "and",
    }
    tokens = [
        token for token in re.findall(r"[a-z0-9]+", name.lower())
        if len(token) >= 4 and token not in generic
    ]
    return any(token in domain for token in tokens)


def linkedin_url(value):
    value = value or ""
    href = value if value.startswith("http") else "https:" + value
    parsed = urlparse(href)
    if "linkedin.com" not in parsed.netloc.lower():
        return ""
    if not re.search(r"/(company|school|in)/", parsed.path):
        return ""
    if "/admin" in parsed.path or "mycompany" in parsed.path:
        return ""
    return href


def valid_phone(value):
    value = clean(value)
    digits = re.sub(r"\D", "", value)
    return bool(value and 7 <= len(digits) <= 16)


def phone_from_text(text):
    for candidate in re.findall(r"(?<!\w)(?:\+|00)?\d[\d\s()./-]{7,}\d", text or ""):
        if valid_phone(candidate):
            return clean(candidate)
    return ""


def email_from_soup(soup):
    for link in soup.select('a[href^="mailto:"]'):
        value = link["href"].split(":", 1)[1].split("?", 1)[0].strip()
        if "@" in value:
            return value.lower()
    match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", soup.get_text(" ", strip=True))
    return match.group(0).lower() if match else ""


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
    section = soup.select_one("section.user-items-list-section")
    if not section:
        raise RuntimeError("2026 exhibitor section not found")
    records = []
    for item in section.select("li.list-item"):
        title = item.select_one("h2.list-item-content__title")
        if not title:
            continue
        card_description = (
            clean(item.select_one(".list-item-content__description").get_text(" ", strip=True))
            if item.select_one(".list-item-content__description") else ""
        )
        card_description = re.sub(r"^More info\s*", "", card_description, flags=re.I).strip()
        link = next(
            (
                anchor for anchor in item.select("a[href]")
                if "more info" in clean(anchor.get_text(" ", strip=True)).lower()
            ),
            None,
        )
        records.append({
            "exhibitor_name": clean(title.get_text(" ", strip=True)),
            "domain": "",
            "contact_number": "",
            "mail": "",
            "location": "",
            "country": "United Kingdom",
            "booth_no": "",
            "desc": card_description,
            "linkedin_url": "",
            "city": "",
            "profile_url": urljoin(BASE_URL, link.get("href", "")) if link else "",
            "event_date": "2026-11-13 to 2026-11-15",
            "event_venue": "The Great Yorkshire Event Centre, Harrogate HG2 8NZ, United Kingdom",
            "source_url": LIST_URL,
            "source_year": "2026",
        })
    if not records:
        raise RuntimeError("No 2026 exhibitors found")
    return records


def profile(record):
    if not record["profile_url"]:
        return record
    try:
        response = requests.get(record["profile_url"], headers=HEADERS, timeout=45)
        response.raise_for_status()
    except requests.RequestException:
        return record
    soup = BeautifulSoup(response.content, "html.parser")
    heading = soup.select_one("main h3, h3")
    if heading:
        expected = {
            token for token in re.findall(r"[a-z0-9]+", record["exhibitor_name"].lower())
            if len(token) >= 3 and token not in {"tools", "tool", "ltd", "fixings", "the", "and"}
        }
        actual = {
            token for token in re.findall(r"[a-z0-9]+", heading.get_text(" ", strip=True).lower())
            if len(token) >= 3 and token not in {"tools", "tool", "ltd", "fixings", "the", "and"}
        }
        if expected and actual and not expected.intersection(actual):
            return record
    profile_host = (urlparse(record["profile_url"]).hostname or "").lower()
    if profile_host and not profile_host.endswith("harrogatewoodworkingshow.co.uk"):
        record["domain"] = root_domain(record["profile_url"])
    record["mail"] = email_from_soup(soup)
    record["contact_number"] = phone_from_text(soup.get_text(" ", strip=True))
    links = soup.select('a[href^="http"], a[href^="www."]')
    website = next(
        (
            link for link in links
            if root_domain(link.get("href", ""))
            and re.search(r"\bwww\.|official|website", link.get_text(" ", strip=True), re.I)
        ),
        None,
    ) or next(
        (link for link in links if root_domain(link.get("href", ""))),
        None,
    )
    if website and not record["domain"]:
        record["domain"] = root_domain(website.get("href", ""))
    linkedin = soup.select_one('a[href*="linkedin.com/"]')
    if linkedin:
        record["linkedin_url"] = linkedin_url(linkedin.get("href", ""))
    paragraphs = []
    for paragraph in soup.select("main p, .content-wrapper p"):
        text = clean(paragraph.get_text(" ", strip=True))
        if (
            len(text) >= 40
            and "sign up to receive" not in text.lower()
            and "great yorkshire event centre" not in text.lower()
            and not re.search(r"@|\b(?:www|https?://)", text, re.I)
        ):
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
            json={"q": f'"{record["exhibitor_name"]}" official website 2026 woodworking'},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph", {})
        candidate = root_domain(graph.get("website", ""))
        if candidate and plausible_domain(record["exhibitor_name"], candidate):
            record["domain"] = candidate
        if not record["domain"]:
            for item in data.get("organic", []):
                candidate = root_domain(item.get("link", ""))
                if candidate and plausible_domain(record["exhibitor_name"], candidate):
                    record["domain"] = candidate
                    break
        if not record["desc"]:
            record["desc"] = clean(graph.get("description", ""))
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
    print(f"Exported {len(records)} 2026 woodworking exhibitors")
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
