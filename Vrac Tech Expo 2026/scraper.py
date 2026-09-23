import csv
import html
import json
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "VRAC_TECH_EXPO_2026"
BASE_URL = "https://www.vractech.com/fr/partners"
VENUE = "114 Rue de Calonges, 47440 Casseneuil, France"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "vractech.com", "wikipedia.org", "yellowpages.com", "yelp.com",
}


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
    if not host or "." not in host or any(host == x or host.endswith("." + x) for x in BLOCKED):
        return ""
    return host


def extract_state(text):
    marker = 'INITIAL_STATE = JSON.parse(decodeURIComponent("'
    start = text.index(marker) + len(marker)
    end = text.index('"));', start)
    return json.loads(urllib.parse.unquote(text[start:end]))


def find_entity(value, expected_name):
    if isinstance(value, dict):
        if clean(value.get("name", "")).casefold() == clean(expected_name).casefold():
            if any(key in value for key in ("website", "description", "linkedin")):
                return value
        for child in value.values():
            found = find_entity(child, expected_name)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_entity(child, expected_name)
            if found:
                return found
    return {}


def parse_listing(soup):
    records = []
    for card in soup.select(".exhibitor-item"):
        link = next((a for a in card.find_all("a", href=True) if "/fr/partner/" in a["href"]), None)
        name_node = card.select_one("h4.bloc-title .fieldtext")
        if not link or not name_node:
            continue
        name = clean(name_node.get_text(" ", strip=True))
        profile_url = urllib.parse.urljoin(BASE_URL, link["href"])
        website = ""
        linkedin = ""
        for anchor in card.find_all("a", href=True):
            href = anchor["href"]
            if "linkedin.com/" in href:
                linkedin = href.split("?", 1)[0]
            elif root_domain(href):
                website = href
        stand_node = card.select_one(".exhibitor-standnumber-formatted")
        desc_node = card.select_one(".description .fieldtext")
        records.append({
            "exhibitor_name": name,
            "domain": root_domain(website),
            "contact_number": "",
            "mail": "",
            "location": VENUE,
            "country": "France",
            "booth_no": clean(stand_node.get_text(" ", strip=True) if stand_node else ""),
            "desc": clean(desc_node.get_text(" ", strip=True) if desc_node else ""),
            "linkedin_url": linkedin,
            "city": "Casseneuil",
            "profile_url": profile_url,
            "event_source": BASE_URL,
        })
    return records


def profile_enrich(record):
    try:
        response = requests.get(record["profile_url"], headers=HEADERS, timeout=60)
        response.raise_for_status()
        state = extract_state(response.text)
        entity = find_entity(state, record["exhibitor_name"])
        description = entity.get("description", "")
        if isinstance(description, dict):
            description = description.get("en") or description.get("fr") or ""
        if description:
            record["desc"] = clean(description)
        record["domain"] = root_domain(entity.get("website", "")) or record["domain"]
        record["linkedin_url"] = clean(entity.get("linkedin", "")) or record["linkedin_url"]
        soup = BeautifulSoup(response.text, "html.parser")
        for anchor in soup.select('a[href^="mailto:"]'):
            record["mail"] = anchor["href"].split(":", 1)[1].split("?", 1)[0]
            break
        for anchor in soup.select('a[href^="tel:"]'):
            record["contact_number"] = clean(anchor["href"].split(":", 1)[1])
            break
    except Exception as exc:
        print(f"profile failed: {record['exhibitor_name']}: {exc}")
    return record


def serper_enrich(record, api_key):
    if record["domain"] or not api_key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website 2026 France', "gl": "fr", "hl": "en", "num": 10},
            timeout=45,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph") or {}
        record["domain"] = root_domain(graph.get("website", ""))
        for result in data.get("organic", []):
            if not record["domain"]:
                record["domain"] = root_domain(result.get("link", ""))
            if not record["linkedin_url"] and "linkedin.com/" in result.get("link", ""):
                record["linkedin_url"] = result["link"].split("?", 1)[0]
    except Exception as exc:
        print(f"Serper failed: {record['exhibitor_name']}: {exc}")
    return record


def load_api_key():
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def main():
    out = Path(__file__).resolve().parent / "output"
    out.mkdir(exist_ok=True)
    records = []
    session = requests.Session()
    for page in range(8):
        url = BASE_URL if page == 0 else f"{BASE_URL}?page={page}"
        response = session.get(url, headers=HEADERS, timeout=60)
        response.raise_for_status()
        records.extend(parse_listing(BeautifulSoup(response.text, "html.parser")))
    unique = {record["profile_url"]: record for record in records}
    records = list(unique.values())
    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(profile_enrich, records))
    api_key = load_api_key()
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda record: serper_enrich(record, api_key), records))
    records.sort(key=lambda record: record["exhibitor_name"].casefold())
    fields = [
        "exhibitor_name", "domain", "contact_number", "mail", "location", "country",
        "booth_no", "desc", "linkedin_url", "city", "profile_url", "event_source",
    ]
    csv_path = out / f"{EVENT}_exhibitors.csv"
    json_path = out / f"{EVENT}_exhibitors.json"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf8")
    print(f"Found {len(records)} published 2026 exhibitors")
    print(f"Wrote {csv_path} and {json_path}")


if __name__ == "__main__":
    main()
