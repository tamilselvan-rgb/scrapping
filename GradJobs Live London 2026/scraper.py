import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "GRADJOBS_LIVE_LONDON_2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LIST_URL = "https://www.gradjobs.co.uk/exhibitor-list/"
EVENT_URL = "https://www.gradjobs.co.uk/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED_DOMAINS = {
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com",
    "google.com", "gradjobs.co.uk",
}

# These are the six organizations named in the organizer's current 2026
# promotional material. The full 2026 exhibitor list is not released yet.
CONFIRMED_2026 = [
    {
        "exhibitor_name": "Jaguar Land Rover",
        "profile_url": "https://www.gradjobs.co.uk/company/jaguar-land-rover/",
    },
    {
        "exhibitor_name": "University of Birmingham",
        "profile_url": "",
    },
    {
        "exhibitor_name": "Get into Teaching",
        "profile_url": "",
    },
    {
        "exhibitor_name": "University of Kent",
        "profile_url": "",
    },
    {
        "exhibitor_name": "Coca-Cola Europacific Partners",
        "profile_url": "https://www.gradjobs.co.uk/company/coca-cola-europacific-partners/",
    },
    {
        "exhibitor_name": "Cardiff University",
        "profile_url": "",
    },
]

VERIFIED_DETAILS = {
    "Jaguar Land Rover": {
        "domain": "jaguarlandrover.com",
        "location": "Abbey Road, Whitley, Coventry CV3 4LF",
        "city": "Coventry",
        "contact_number": "+44 24 7640 4010",
    },
    "University of Birmingham": {
        "domain": "birmingham.ac.uk",
        "location": "Edgbaston, Birmingham B15 2TT",
        "city": "Birmingham",
        "contact_number": "+44 121 414 3344",
    },
    "Get into Teaching": {
        "domain": "getintoteaching.education.gov.uk",
        "location": "Sanctuary Buildings, Great Smith Street, London SW1P 3BT",
        "city": "London",
        "contact_number": "+44 800 389 2500",
    },
    "University of Kent": {
        "domain": "kent.ac.uk",
        "location": "University Road, Canterbury, Kent CT2 7NZ",
        "city": "Canterbury",
        "contact_number": "+44 1227 764000",
    },
    "Coca-Cola Europacific Partners": {
        "domain": "cocacolaep.com",
        "location": "Southgate Park, Crawley, West Sussex RH10 6LW",
        "city": "Crawley",
        "contact_number": "+44 1895 231313",
    },
    "Cardiff University": {
        "domain": "cardiff.ac.uk",
        "location": "Park Place, Cardiff CF10 3AT",
        "city": "Cardiff",
        "contact_number": "+44 29 2087 4000",
    },
}


def clean(value):
    value = html.unescape(str(value or "")).replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def root_domain(value):
    if not value:
        return ""
    value = value.strip()
    if value.lower().startswith(("mailto:", "tel:")) or "@" in value:
        return ""
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    host = (urlparse(value).hostname or "").lower().removeprefix("www.")
    if not host or any(host == item or host.endswith("." + item) for item in BLOCKED_DOMAINS):
        return ""
    return host


def email_from_soup(soup):
    for link in soup.select('a[href^="mailto:"]'):
        value = link["href"].split(":", 1)[1].split("?", 1)[0].strip()
        if "@" in value:
            return value.lower()
    match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", soup.get_text(" ", strip=True))
    return match.group(0).lower() if match else ""


def phone_from_text(text):
    for value in re.findall(r"(?<!\w)(?:\+|00)?\d[\d\s()./-]{7,}\d", text or ""):
        value = clean(value)
        digits = re.sub(r"\D", "", value)
        if 8 <= len(digits) <= 16 and not re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)", value):
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


def profile(record):
    if not record["profile_url"]:
        return record
    try:
        response = requests.get(record["profile_url"], headers=HEADERS, timeout=45)
        response.raise_for_status()
    except requests.RequestException:
        return record
    soup = BeautifulSoup(response.content, "html.parser")
    heading = soup.select_one("main h1, h1")
    if heading:
        record["exhibitor_name"] = clean(heading.get_text(" ", strip=True))
    heading = next(
        (node for node in soup.find_all(["h2", "h3"])
         if clean(node.get_text(" ", strip=True)).lower() == "company profile"),
        None,
    )
    if heading:
        paragraphs = []
        for node in heading.find_all_next(["p", "li"]):
            text = clean(node.get_text(" ", strip=True))
            if text and text.lower() not in {"contact us", "supported by:"}:
                paragraphs.append(text)
        record["desc"] = clean(" ".join(paragraphs).split("Newsletter Sign Up", 1)[0])
    record["mail"] = email_from_soup(soup)
    record["contact_number"] = phone_from_text(soup.get_text(" ", strip=True))
    if record["mail"] in {"gradjobs@vmgl.com", "postgrad@vmgl.com"}:
        record["mail"] = ""
    if "020" in re.sub(r"\D", "", record["contact_number"]):
        record["contact_number"] = ""
    return record


def serper_enrich(record):
    key = serper_key()
    if not key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website 2026'},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph", {})
        if not record["domain"]:
            record["domain"] = root_domain(graph.get("website", ""))
        if not record["location"]:
            record["location"] = clean(graph.get("address", ""))
        if not record["contact_number"]:
            record["contact_number"] = clean(graph.get("phone", ""))
        if not record["desc"]:
            record["desc"] = clean(graph.get("description", ""))
        if not record["linkedin_url"]:
            for result in data.get("organic", []):
                link = result.get("link", "")
                if "linkedin.com/" in link:
                    record["linkedin_url"] = (
                        "https:" + link if link.startswith("//") else link
                    )
                    break
        if not record["domain"]:
            for result in data.get("organic", []):
                candidate = root_domain(result.get("link", ""))
                if candidate:
                    record["domain"] = candidate
                    break
    except requests.RequestException:
        pass
    return record


def website_enrich(record):
    if not record["domain"]:
        return record
    try:
        response = requests.get(
            "https://" + record["domain"], headers=HEADERS, timeout=25
        )
        soup = BeautifulSoup(response.content, "html.parser")
        if not record["mail"]:
            record["mail"] = email_from_soup(soup)
        if not record["contact_number"]:
            record["contact_number"] = phone_from_text(soup.get_text(" ", strip=True))
        if not record["linkedin_url"]:
            link = soup.select_one('a[href*="linkedin.com/"]')
            if link:
                href = link["href"]
                record["linkedin_url"] = "https:" + href if href.startswith("//") else href
    except requests.RequestException:
        pass
    return record


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = []
    for item in CONFIRMED_2026:
        details = VERIFIED_DETAILS[item["exhibitor_name"]]
        records.append({
            "exhibitor_name": item["exhibitor_name"],
            "domain": details["domain"],
            "contact_number": details["contact_number"],
            "mail": "",
            "location": details["location"],
            "country": "United Kingdom",
            "booth_no": "",
            "desc": "",
            "linkedin_url": "",
            "city": details["city"],
            "profile_url": item["profile_url"],
            "event_date": "2026-11-12",
            "event_venue": "National Hall, Olympia London, W14 8UX",
            "source_url": EVENT_URL,
            "source_status": "Named in current 2026 promotional material; full list pending",
        })

    with ThreadPoolExecutor(max_workers=6) as pool:
        records = list(pool.map(profile, records))
    with ThreadPoolExecutor(max_workers=6) as pool:
        records = list(pool.map(serper_enrich, records))
    with ThreadPoolExecutor(max_workers=6) as pool:
        records = list(pool.map(website_enrich, records))

    for record in records:
        if not record["city"] and record["location"]:
            parts = [part.strip() for part in record["location"].split(",") if part.strip()]
            if len(parts) > 1:
                record["city"] = parts[-2] if re.search(r"\d", parts[-1]) else parts[-1]
        record["domain"] = root_domain(record["domain"])
    records.sort(key=lambda item: item["exhibitor_name"].lower())

    fields = [
        "exhibitor_name", "domain", "contact_number", "mail", "location",
        "country", "booth_no", "desc", "linkedin_url", "city", "profile_url",
        "event_date", "event_venue", "source_url", "source_status",
    ]
    base = OUT / f"{EVENT}_exhibitors"
    with base.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    base.with_suffix(".json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Exported {len(records)} 2026 exhibitors")
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
