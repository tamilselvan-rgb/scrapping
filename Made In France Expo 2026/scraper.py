import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "MADE_IN_FRANCE_EXPO_2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
BASE = "https://www.mifexpo.fr"
LIST_URL = f"{BASE}/exposants/"
AJAX_URL = f"{BASE}/wp-admin/admin-ajax.php?lang=fr"
SALON_ID = 952944  # Paris 2026
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "google.com", "mifexpo.fr",
    "yellowpages.com", "yelp.com", "tripadvisor.com",
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
    email = match.group(0).lower() if match else ""
    return "" if email.endswith("@mifexpo.fr") else email


def phone_from_text(text):
    for value in re.findall(r"(?<!\w)(?:\+|00)?\d[\d\s()./-]{7,}\d", text or ""):
        value = clean(value)
        digits = re.sub(r"\D", "", value)
        if 8 <= len(digits) <= 16 and not re.search(r"(?<!\d)20\d{2}(?!\d)", value):
            return value
    return ""


def parse_listing():
    response = requests.get(AJAX_URL, params={
        "action": "ajax_search_exposants",
        "pavillon_id": "nan",
        "region_id": "nan",
        "secteur_id": "nan",
        "salon_id": SALON_ID,
        "search_text": "",
        "actionsearch": "true",
    }, headers=HEADERS, timeout=90)
    response.encoding = response.apparent_encoding or "utf-8"
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    records = []
    for card in soup.select(".exposants-item"):
        name_node = card.select_one(".exposants-name")
        if not name_node:
            continue
        link = name_node.select_one("a[href]")
        name = clean(name_node.get_text(" ", strip=True))
        desc = clean(card.select_one(".exposants-secteur:nth-of-type(2), .exposants-secteur:last-of-type").get_text(" ", strip=True)) if card.select_one(".exposants-secteur:last-of-type") else ""
        records.append({
            "exhibitor_name": name,
            "domain": "",
            "contact_number": "",
            "mail": "",
            "location": "",
            "country": "France",
            "booth_no": "",
            "desc": desc,
            "linkedin_url": "",
            "profile_url": urljoin(BASE, link.get("href", "")) if link else "",
            "facebook_url": "",
            "instagram_url": "",
        })
    return records


def parse_profile(record):
    if not record["profile_url"]:
        return record
    try:
        response = requests.get(record["profile_url"], headers=HEADERS, timeout=45)
        response.encoding = response.apparent_encoding or "utf-8"
        response.raise_for_status()
    except requests.RequestException:
        return record
    soup = BeautifulSoup(response.text, "html.parser")
    heading = soup.select_one("article .exposants-name, article h1")
    if heading:
        record["exhibitor_name"] = clean(heading.get_text(" ", strip=True))
    description = soup.select_one(".exposants-produits")
    if description:
        record["desc"] = clean(description.get_text(" ", strip=True))
    stand = soup.select_one(".exposants-stand")
    if stand:
        match = re.search(r"(?:Stand|stand)\s+([^<\n]+)", stand.get_text(" ", strip=True))
        record["booth_no"] = clean(f"Stand {match.group(1)}" if match else stand.get_text(" ", strip=True))
    social = soup.select_one(".exposants-social")
    for link in social.select("a[href]") if social else []:
        href = link.get("href", "")
        domain = (urlparse(href).hostname or "").lower()
        if "linkedin.com/" in domain:
            record["linkedin_url"] = href
        elif "facebook.com/" in domain:
            record["facebook_url"] = href
        elif "instagram.com/" in domain:
            record["instagram_url"] = href
        elif root_domain(href):
            record["domain"] = root_domain(href)
    mailto = soup.select_one('a[href^="mailto:"]')
    if mailto:
        email = mailto.get("href", "").split(":", 1)[1].split("?", 1)[0].lower()
        if not email.endswith("@mifexpo.fr"):
            record["mail"] = email
    tel = soup.select_one('a[href^="tel:"]')
    if tel:
        record["contact_number"] = clean(tel.get("href", "").split(":", 1)[1])
    return record


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
            json={"q": f'"{record["exhibitor_name"]}" official website MIF Expo Paris 2026'},
            timeout=30,
        )
        response.raise_for_status()
        graph = response.json().get("knowledgeGraph", {})
        record["domain"] = root_domain(graph.get("website", ""))
    except requests.RequestException:
        pass
    return record


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = parse_listing()
    print(f"Found {len(records)} Paris 2026 exhibitor cards")
    with ThreadPoolExecutor(max_workers=24) as pool:
        records = list(pool.map(parse_profile, records))
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(enrich_domain, records))
    records.sort(key=lambda item: item["exhibitor_name"].lower())
    fields = [
        "exhibitor_name", "domain", "contact_number", "mail", "location",
        "country", "booth_no", "desc", "linkedin_url", "profile_url",
        "facebook_url", "instagram_url",
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
