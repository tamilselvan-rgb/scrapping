import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "FABRICS_EXPO_2026"
LIST_URL = "https://fasttextile.com/en/wystawcy"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
VENUE = "Ptak Expo Łódź, ul. Tuszyńska 72/74, 95-030 Rzgów, Poland"
COUNTRIES = {
    "Polska": "Poland", "Litwa": "Lithuania", "Grecja": "Greece",
    "Pakistan": "Pakistan", "Indonezja": "Indonesia", "Chiny": "China",
    "Korea Południowa": "South Korea", "Turcja": "Turkey", "Włochy": "Italy",
    "Niemcy": "Germany", "Hongkong": "Hong Kong", "Hiszpania": "Spain",
    "Bułgaria": "Bulgaria", "Czechy": "Czech Republic",
}
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "fasttextile.com", "ptakexpo.eu", "ptakexpo.com.pl",
    "wikipedia.org", "yellowpages.com", "yelp.com", "pappers.fr",
    "rocketreach.co", "oohmagazine.pl", "nashvillelifestyles.com",
    "thetextiledirectory.co.uk", "coltelleriacollini.com", "mdpi.com",
    "alamy.com", "inforegister.ee", "tenereteam.com", "expedia.com",
    "ubuy.com.pl", "leatherworkinggroup.com",
    "sdvoyager.com", "threads.com", "contecinc.com",
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


def parse_listing():
    response = requests.get(LIST_URL, headers=HEADERS, timeout=60)
    response.encoding = response.apparent_encoding or "utf-8"
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    records = {}
    for card in soup.select("li.glass-card"):
        name_node = card.select_one("strong")
        appointment = card.select_one("a[href*='.fasttextile.com/']")
        booth = card.select_one("div.inline-flex strong")
        flag = card.select_one("span[title]")
        if not name_node or not appointment:
            continue
        name = clean(name_node.get_text(" ", strip=True))
        profile_url = appointment.get("href", "")
        records[profile_url] = {
            "exhibitor_name": name,
            "domain": "",
            "contact_number": "",
            "mail": "",
            "location": VENUE,
            "country": COUNTRIES.get(clean(flag.get("title", "")) if flag else "", "Poland"),
            "booth_no": clean(booth.get_text(" ", strip=True)) if booth else "",
            "desc": "",
            "linkedin_url": "",
            "city": "Rzgów",
            "profile_url": profile_url,
            "event_source": LIST_URL,
        }
    return list(records.values())


def parse_profile(record):
    try:
        response = requests.get(record["profile_url"], headers=HEADERS, timeout=45)
        response.encoding = response.apparent_encoding or "utf-8"
        response.raise_for_status()
    except requests.RequestException:
        return record
    soup = BeautifulSoup(response.text, "html.parser")
    name = soup.select_one("h1.pk-regsplit__h1")
    booth = soup.select_one(".pk-regsplit__lead")
    if name:
        record["exhibitor_name"] = clean(name.get_text(" ", strip=True))
    if booth:
        match = re.search(r"Booth no\.\s*(.+)$", clean(booth.get_text(" ", strip=True)), re.I)
        if match:
            record["booth_no"] = clean(match.group(1))
    return record


def serper_key():
    env = Path(__file__).resolve().parents[1] / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"\'')
    return ""


def relevant(result, name):
    title = clean(result.get("title", "")).casefold()
    host = (urlparse(result.get("link", "")).hostname or "").lower()
    normalized_name = re.sub(r"[^a-z0-9]", "", name.casefold())
    normalized_title = re.sub(r"[^a-z0-9]", "", title)
    normalized_host = re.sub(r"[^a-z0-9]", "", host)
    if normalized_name and normalized_name in normalized_title:
        return True
    tokens = [token for token in re.findall(r"[a-z0-9]{4,}", name.casefold())]
    return len(tokens) >= 2 and all(token in normalized_host for token in tokens[:2])


def enrich_domain(record):
    key = serper_key()
    if not key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website Fast Textile 2026'},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        record["domain"] = root_domain(data.get("knowledgeGraph", {}).get("website", ""))
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
    records = parse_listing()
    print(f"Found {len(records)} Fast Textile 2026 exhibitor profiles")
    with ThreadPoolExecutor(max_workers=16) as pool:
        records = list(pool.map(parse_profile, records))
    records = list({record["exhibitor_name"].casefold(): record for record in records}.values())
    with ThreadPoolExecutor(max_workers=10) as pool:
        records = list(pool.map(enrich_domain, records))
    records.sort(key=lambda item: item["exhibitor_name"].casefold())
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
    print(f"Scraped {len(records)} exhibitors")


if __name__ == "__main__":
    main()
