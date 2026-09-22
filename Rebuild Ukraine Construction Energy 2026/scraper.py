import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "REBUILD_UKRAINE_CONSTRUCTION_ENERGY_2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
SITE_URL = "https://catalog.pe.com.ua"
API_URL = "https://apic.pe.com.ua/api"
CATALOG_ID = 74
LIST_URL = f"{SITE_URL}/catalog/{CATALOG_ID}"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "catalog.pe.com.ua", "linkedin.com", "facebook.com", "instagram.com",
    "twitter.com", "x.com", "youtube.com", "wikipedia.org", "yellowpages.com",
    "yelp.com", "google.com", "tracxn.com", "kompass.com", "kununu.com",
    "10times.com", "jobv.eu", "pmc.ncbi.nlm.nih.gov",
}

FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location",
    "country", "booth_no", "name", "desc", "email", "phone", "address",
    "city", "linkedin_url", "profile_url", "source_year",
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
    tokens = [
        token for token in re.findall(r"[a-z0-9]+", name.lower())
        if len(token) >= 4 and token not in {"gmbh", "gesellschaft", "limited", "company"}
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
    if not value or len(digits) < 7 or len(digits) > 16:
        return False
    if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", value):
        return False
    return True


def email_from_soup(soup):
    for link in soup.select('a[href^="mailto:"]'):
        value = link["href"].split(":", 1)[1].split("?", 1)[0].strip()
        if "@" in value:
            return value.lower()
    match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", soup.get_text(" ", strip=True))
    return match.group(0).lower() if match else ""


def phone_from_soup(soup):
    tel = soup.select_one('a[href^="tel:"]')
    if tel and valid_phone(tel.get("href", "")[4:]):
        return clean(tel.get("href", "")[4:])
    for value in re.findall(r"(?<!\w)(?:\+|00)?\d[\d\s()./-]{7,}\d", soup.get_text(" ", strip=True)):
        if valid_phone(value):
            return clean(value)
    return ""


def api_get(session, path, params=None):
    response = session.get(API_URL + path, params=params, timeout=60)
    response.raise_for_status()
    return response.json()


def list_companies(session):
    first = api_get(session, f"/companies/catalog/{CATALOG_ID}", {"page": 1})
    paginator = first["companies"]
    rows = list(paginator.get("data", []))
    for page in range(2, paginator.get("last_page", 1) + 1):
        data = api_get(session, f"/companies/catalog/{CATALOG_ID}", {"page": page})
        rows.extend(data["companies"].get("data", []))
    return rows


def parse_company(row):
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        detail = api_get(session, f"/companies/show/{row['id']}")["company"]
    except requests.RequestException:
        detail = row
    sites = detail.get("site") or []
    socials = detail.get("social") or []
    phones = detail.get("phone") or []
    emails = detail.get("email") or []
    phone = next(
        (clean(item.get("number", "")) for item in phones if isinstance(item, dict)),
        "",
    )
    mail = next(
        (
            clean(item.get("email", "") if isinstance(item, dict) else item)
            for item in emails
            if "@" in clean(item.get("email", "") if isinstance(item, dict) else item)
        ),
        "",
    )
    domain = next(
        (root_domain(item.get("url", "") if isinstance(item, dict) else item) for item in sites),
        "",
    )
    social_links = [
        item.get("url", "") if isinstance(item, dict) else item for item in socials
    ]
    stand = detail.get("stend") or []
    booth = next(
        (
            clean(
                item.get("name", item.get("number", item.get("stend", "")))
                if isinstance(item, dict) else item
            )
            for item in stand
            if clean(item.get("name", item.get("number", item.get("stend", "")))
                     if isinstance(item, dict) else item)
        ),
        "",
    )
    address = clean(detail.get("address", ""))
    return {
        "exhibitor_name": clean(detail.get("name", row.get("name", ""))),
        "domain": domain,
        "contact_number": phone if valid_phone(phone) else "",
        "mail": mail,
        "location": address,
        "country": "Ukraine" if "Укра" in address else "Ukraine",
        "booth_no": booth,
        "name": clean(detail.get("name", row.get("name", ""))),
        "desc": clean(detail.get("description", "")),
        "email": mail,
        "phone": phone if valid_phone(phone) else "",
        "address": address,
        "city": "",
        "linkedin_url": next((linkedin_url(x) for x in social_links if linkedin_url(x)), ""),
        "profile_url": f"{SITE_URL}/company/{detail.get('id', row['id'])}",
        "source_year": "2026",
        "_id": detail.get("id", row["id"]),
    }


def serper_key():
    env = ROOT.parent / ".env"
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"\'')
    return ""


def serper_domain(record):
    if record["domain"]:
        return record
    key = serper_key()
    if not key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website 2026 Ukraine'},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph", {})
        record["domain"] = root_domain(graph.get("website", ""))
        if not record["domain"] or not plausible_domain(
            record["exhibitor_name"], record["domain"]
        ):
            record["domain"] = ""
            for item in data.get("organic", []):
                candidate = root_domain(item.get("link", ""))
                if candidate and plausible_domain(record["exhibitor_name"], candidate):
                    record["domain"] = candidate
                    break
        if not record["linkedin_url"]:
            for item in data.get("organic", []):
                candidate = linkedin_url(item.get("link", ""))
                if candidate:
                    record["linkedin_url"] = candidate
                    break
    except requests.RequestException:
        pass
    return record


def website_contacts(record):
    if not record["domain"]:
        return record
    session = requests.Session()
    session.headers.update(HEADERS)
    for suffix in ("", "contact", "contacts", "about", "impressum"):
        try:
            response = session.get(f"https://{record['domain']}/{suffix}", timeout=20)
            if response.status_code >= 400:
                continue
        except requests.RequestException:
            continue
        soup = BeautifulSoup(response.content, "html.parser")
        record["mail"] = record["mail"] or email_from_soup(soup)
        record["contact_number"] = record["contact_number"] or phone_from_soup(soup)
        if not record["linkedin_url"]:
            link = soup.select_one('a[href*="linkedin.com/"]')
            if link:
                record["linkedin_url"] = linkedin_url(link.get("href", ""))
        if record["mail"] and record["contact_number"]:
            break
    record["email"] = record["mail"]
    record["phone"] = record["contact_number"]
    return record


def translate_text(value):
    if not value or not re.search(r"[\u0400-\u04ff]", value):
        return value
    try:
        response = requests.get(
            "https://api.mymemory.translated.net/get",
            params={"q": value[:4500], "langpair": "uk|en"},
            timeout=8,
        )
        response.raise_for_status()
        translated = response.json().get("responseData", {}).get("translatedText", "")
        return clean(translated) or value
    except (requests.RequestException, ValueError):
        return value


def translate_record(record):
    record["desc"] = translate_text(record["desc"])
    record["location"] = translate_text(record["location"])
    record["address"] = record["location"]
    country_map = {
        "Україна": "Ukraine", "Німеччина": "Germany", "Данія": "Denmark",
        "Швейцарія": "Switzerland", "Японія": "Japan", "Австрія": "Austria",
        "Швеція": "Sweden", "Польща": "Poland", "Франція": "France",
        "Італія": "Italy", "Тайвань": "Taiwan", "США": "United States",
        "Туреччина": "Türkiye", "Нідерланди": "Netherlands", "Канада": "Canada",
        "Китай": "China", "Південна Корея": "South Korea",
    }
    for native, english in country_map.items():
        if native in record["location"]:
            record["country"] = english
            break
    if record["location"]:
        parts = [part.strip() for part in record["location"].split(",") if part.strip()]
        record["city"] = parts[-2] if len(parts) > 1 and re.search(r"\d", parts[-1]) else (parts[-1] if parts else "")
    return record


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(HEADERS)
    rows = list_companies(session)
    with ThreadPoolExecutor(max_workers=16) as pool:
        records = list(pool.map(parse_company, rows))
    with ThreadPoolExecutor(max_workers=24) as pool:
        records = list(pool.map(serper_domain, records))
    with ThreadPoolExecutor(max_workers=32) as pool:
        records = list(pool.map(translate_record, records))
    for record in records:
        record.pop("_id", None)
        record["country"] = record["country"] or "Ukraine"
    records.sort(key=lambda item: item["exhibitor_name"].casefold())
    base = OUT / f"{EVENT}_exhibitors"
    with base.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    base.with_suffix(".json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Exported {len(records)} 2026 ReBuild Ukraine exhibitors")
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
