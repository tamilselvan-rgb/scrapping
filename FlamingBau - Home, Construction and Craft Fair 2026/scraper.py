import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "FLAMINGBAU_HOME_CONSTRUCTION_AND_CRAFT_FAIR_2026"
LIST_URL = "https://messe-brandenburg.de/flaemingbau/ausstellerverzeichnis/"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "messe-brandenburg.de",
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
    return "" if not host or any(host == x or host.endswith("." + x) for x in BLOCKED) else host


def parse_address(node):
    parts = [clean(x.get_text(" ", strip=True)) for x in node.select(".street-address")]
    address = clean(" ".join(parts))
    match = re.search(r"\b(?:D|PL)\s*[–-]\s*(\d{5})\s+(.+)$", address)
    if not match:
        match = re.search(r"\b(\d{5})\s+(.+)$", address)
    city = clean(match.group(2)) if match else ""
    country_code = "PL" if re.search(r"\bPL\s*[–-]", address) else "D"
    return address, city, {"D": "Germany", "PL": "Poland"}.get(country_code, "")


def parse_item(item):
    name_node = item.select_one(".org.fn")
    address_node = item.select_one(".adr")
    if not name_node or not address_node:
        return None
    name = clean(name_node.get_text(" ", strip=True))
    location, city, country = parse_address(address_node)
    phone = clean(item.select_one(".cn-phone-number .value").get_text(" ", strip=True)) if item.select_one(".cn-phone-number .value") else ""
    email_node = item.select_one(".cn-email-address a.value")
    email = clean(email_node.get_text(" ", strip=True)) if email_node else ""
    website_node = item.select_one(".cn-link.website a.url")
    domain = root_domain(website_node.get("href", "") if website_node else "")
    if not domain and website_node:
        domain = root_domain(website_node.get_text(" ", strip=True))
    biography = item.select_one(".cn-biography")
    description = clean(biography.get_text(" ", strip=True)) if biography else ""
    linkedin_node = item.select_one('a[href*="linkedin.com/"]')
    return {
        "exhibitor_name": name,
        "domain": domain,
        "contact_number": phone,
        "mail": email,
        "location": location,
        "country": country,
        "booth_no": "",
        "desc": description,
        "linkedin_url": linkedin_node.get("href", "") if linkedin_node else "",
        "city": city,
        "profile_url": LIST_URL,
        "event_source": LIST_URL,
    }


def serper_key():
    env = Path(__file__).resolve().parents[1] / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"\'')
    return ""


def relevant(result, name):
    title = clean(result.get("title", "")).casefold()
    host = (urlparse(result.get("link", "")).hostname or "").lower()
    tokens = [x for x in re.findall(r"[a-z0-9]{4,}", name.casefold())]
    return any(token in title or token in host for token in tokens)


def translate_description(record):
    if not record["desc"]:
        return record
    try:
        url = (
            "https://translate.googleapis.com/translate_a/single"
            f"?client=gtx&sl=de&tl=en&dt=t&q={quote(record['desc'])}"
        )
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        translated = response.json()
        record["desc"] = clean("".join(part[0] for part in translated[0] if part[0]))
    except (requests.RequestException, ValueError, IndexError, TypeError):
        pass
    return record


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
            json={"q": f'"{record["exhibitor_name"]}" official website FlämingBau 2026'},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph", {})
        record["domain"] = root_domain(graph.get("website", ""))
        if not record["domain"]:
            for result in data.get("organic", []):
                candidate = root_domain(result.get("link", ""))
                if candidate and relevant(result, record["exhibitor_name"]):
                    record["domain"] = candidate
                    break
    except requests.RequestException:
        pass
    return record


def main():
    response = requests.get(LIST_URL, headers=HEADERS, timeout=60)
    response.encoding = response.apparent_encoding or "utf-8"
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    records = [
        record for record in (parse_item(item) for item in soup.select(".cn-list-item.fbl26"))
        if record
    ]
    records = list({record["exhibitor_name"].casefold(): record for record in records}.values())
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(translate_description, records))
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(enrich_domain, records))
    records.sort(key=lambda x: x["exhibitor_name"].casefold())
    OUT.mkdir(parents=True, exist_ok=True)
    fields = [
        "exhibitor_name", "domain", "contact_number", "mail", "location",
        "country", "booth_no", "desc", "linkedin_url", "city",
        "profile_url", "event_source",
    ]
    base = OUT / f"{EVENT}_exhibitors"
    with base.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    base.with_suffix(".json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Scraped {len(records)} FlämingBau 2026 exhibitors")


if __name__ == "__main__":
    main()
