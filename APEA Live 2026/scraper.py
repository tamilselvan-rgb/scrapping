import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "APEA_LIVE_2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LIST_URL = "https://www.apealive.co.uk/2026/exhibition/exhibitor-list/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "apealive.co.uk", "facebook.com", "instagram.com", "linkedin.com",
    "twitter.com", "x.com", "youtube.com", "wikipedia.org", "google.com",
    "gmail.com", "hotmail.com", "yahoo.com", "10times.com", "madeinbritain.org",
    "mobilityplaza.com", "cochranelibrary.com", "peimf.com", "apea.org.uk",
    "healthytimes.com.sg", "mobilityplaza.org", "tetherx.io",
}


def clean(value):
    value = html.unescape(str(value or "")).replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def root_domain(value):
    if not value:
        return ""
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    host = (urlparse(value).hostname or "").lower().removeprefix("www.")
    if not host or any(host == item or host.endswith("." + item) for item in BLOCKED):
        return ""
    return host


def phone_from_text(text):
    for value in re.findall(r"(?<!\w)(?:\+|00)?\d[\d\s()./-]{7,}\d", text or ""):
        value = clean(value)
        digits = re.sub(r"\D", "", value)
        if 8 <= len(digits) <= 16 and not re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)", value):
            return value
    return ""


def email_from_soup(soup):
    for link in soup.select('a[href^="mailto:"]'):
        value = link["href"].split(":", 1)[1].split("?", 1)[0].strip()
        if "@" in value:
            return value.lower()
    return ""


def list_exhibitors():
    response = requests.get(LIST_URL, headers=HEADERS, timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    records = []
    for card in soup.select("section.exlist_modal_links div.e"):
        name_node = card.select_one("b")
        if not name_node:
            continue
        text = clean(card.get_text(" ", strip=True))
        name = clean(name_node.get_text(" ", strip=True))
        country = ""
        stand = ""
        chunks = [clean(x) for x in card.get_text("\n", strip=True).splitlines() if clean(x)]
        for chunk in chunks:
            if chunk != name and chunk.startswith("Stand "):
                stand = chunk
            elif chunk != name and chunk != "Profile" and not chunk.startswith("Stand "):
                country = chunk
        profile = card.select_one('a[href*="/exhibitor-profile/apea-2026/"]')
        records.append({
            "exhibitor_name": name,
            "domain": "",
            "contact_number": "",
            "mail": "",
            "location": "",
            "country": country or "United Kingdom",
            "booth_no": stand,
            "desc": "",
            "linkedin_url": "",
            "profile_url": profile.get("href", "") if profile else "",
        })
    return records


def parse_profile(record):
    if not record["profile_url"]:
        return record
    try:
        response = requests.get(record["profile_url"], headers=HEADERS, timeout=60)
        response.raise_for_status()
    except requests.RequestException:
        return record
    soup = BeautifulSoup(response.content, "html.parser")
    heading = soup.select_one("h1")
    if heading:
        record["exhibitor_name"] = clean(heading.get_text(" ", strip=True))
    country = soup.select_one("h2.country_town")
    stand = soup.select_one("h3.hall_stand")
    if country:
        record["country"] = clean(country.get_text(" ", strip=True))
    if stand:
        record["booth_no"] = clean(stand.get_text(" ", strip=True))
    profile_heading = next(
        (h for h in soup.select("h2") if clean(h.get_text(" ", strip=True)).lower() == "profile"),
        None,
    )
    if profile_heading:
        paragraph = profile_heading.find_next("p")
        if paragraph:
            record["desc"] = clean(paragraph.get_text(" ", strip=True))
    contact_heading = next(
        (h for h in soup.select("h2") if clean(h.get_text(" ", strip=True)).lower() == "contact details"),
        None,
    )
    if contact_heading:
        first_p = contact_heading.find_next("p")
        if first_p:
            record["location"] = clean(first_p.get_text(" ", strip=True))
        second_p = first_p.find_next("p") if first_p else None
        if second_p:
            record["contact_number"] = phone_from_text(second_p.get_text(" ", strip=True))
    website = soup.select_one('a.allowwrap[href^="http"]')
    if website:
        record["domain"] = root_domain(website.get("href", ""))
    record["mail"] = email_from_soup(soup.select_one("#e_profile") or soup)
    return record


def serper_domain(name):
    env = ROOT.parent / ".env"
    key = ""
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("SERPER_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"\'')
    if not key:
        return ""
    try:
        for query in (f'"{name}" official website APEA Live 2026',
                      f'"{name}" official website'):
            response = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": key, "Content-Type": "application/json"},
                json={"q": query},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            candidate = data.get("knowledgeGraph", {}).get("website", "")
            for result in data.get("organic", []):
                if not root_domain(candidate):
                    candidate = result.get("link", "")
                if root_domain(candidate):
                    break
            if root_domain(candidate):
                return root_domain(candidate)
        return ""
    except requests.RequestException:
        return ""


def website_contacts(record):
    if not record["domain"]:
        return record
    try:
        response = requests.get("https://" + record["domain"], headers=HEADERS, timeout=25)
        soup = BeautifulSoup(response.content, "html.parser")
        if not record["mail"]:
            record["mail"] = email_from_soup(soup)
        if not record["contact_number"]:
            record["contact_number"] = phone_from_text(soup.get_text(" ", strip=True))
        if not record["linkedin_url"]:
            link = soup.select_one('a[href*="linkedin.com/"]')
            if link:
                record["linkedin_url"] = link["href"]
    except requests.RequestException:
        pass
    return record


def enrich(record):
    if record["exhibitor_name"].strip().lower() == "apea":
        record["domain"] = "apea.org.uk"
    if not record["domain"]:
        record["domain"] = serper_domain(record["exhibitor_name"])
    return website_contacts(record)


def main():
    OUT.mkdir(exist_ok=True)
    records = list_exhibitors()
    print(f"Found {len(records)} exhibitors")
    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(parse_profile, records))
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(enrich, records))
    records.sort(key=lambda item: item["exhibitor_name"].lower())
    fields = ["exhibitor_name", "domain", "contact_number", "mail", "location",
              "country", "booth_no", "desc", "linkedin_url", "profile_url"]
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
