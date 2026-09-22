import csv
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "FSB_FORUM_ITALY_2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LIST_URL = "https://www.fsb-forum.com/it/espositori-2026/elenco-espositori/"
PAGE_URL = "https://www.fsb-forum.com/it/espositori-2026/elenco-espositori/index.php"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "tripadvisor.com", "booking.com",
    "google.com", "gmail.com", "yahoo.com", "hotmail.com", "fsb-forum.com",
}
COUNTRIES = {
    "IT": "Italy", "DE": "Germany", "FR": "France", "BE": "Belgium",
    "NL": "The Netherlands", "PL": "Poland", "GB": "United Kingdom",
    "SI": "Slovenia", "ES": "Spain", "US": "United States", "TR": "Turkey",
    "CN": "China", "HK": "Hong Kong", "CA": "Canada", "GR": "Greece",
}


def clean(value):
    value = html.unescape(str(value or "")).replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def domain(value):
    if not value:
        return ""
    if "@" in value and not value.startswith(("http://", "https://")):
        value = value.rsplit("@", 1)[1]
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    host = (urlparse(value).hostname or "").lower().removeprefix("www.")
    if not host or any(host == item or host.endswith("." + item) for item in BLOCKED):
        return ""
    return host


def email_from(soup):
    for link in soup.select('a[href^="mailto:"]'):
        value = link["href"].split(":", 1)[1].split("?", 1)[0].strip()
        if "@" in value:
            return value.lower()
    found = re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", soup.get_text(" ", strip=True))
    return found[0].lower() if found else ""


def phone_from(soup):
    for link in soup.select('a[href^="tel:"]'):
        value = clean(link["href"].split(":", 1)[1])
        digits = re.sub(r"\D", "", value)
        if 8 <= len(digits) <= 16:
            return value
    return ""


def list_exhibitors():
    records = {}
    for page in range(3):
        url = LIST_URL if page == 0 else f"{PAGE_URL}?uwpi={page}&uwtr=125&uwtr=3&uwtr=125"
        response = requests.get(url, headers=HEADERS, timeout=60)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        for link in soup.select('a[href*="exhib="]'):
            match = re.search(r"[?&]exhib=(\d+)", link.get("href", ""))
            if not match:
                continue
            card = link.find_parent("div", class_="col_3") or link.parent.parent
            columns = card.select(".col") if card else []
            name = clean(link.get_text(" ", strip=True))
            stand = clean(columns[1].get_text(" ", strip=True)) if len(columns) > 1 else ""
            country_code = clean(columns[1].select("p")[-1].get_text(" ", strip=True)) if len(columns) > 1 and columns[1].select("p") else ""
            records[match.group(1)] = {
                "exhibitor_name": name,
                "booth_no": stand,
                "country": COUNTRIES.get(country_code.upper(), country_code),
                "profile_url": urljoin(LIST_URL, link["href"]),
            }
    return list(records.values())


def parse_profile(record):
    try:
        response = requests.get(record["profile_url"], headers=HEADERS, timeout=60)
        response.raise_for_status()
    except requests.RequestException:
        return record
    soup = BeautifulSoup(response.content, "html.parser")
    h1 = soup.select_one("section.content.addholder h1")
    if h1:
        record["exhibitor_name"] = clean(h1.get_text(" ", strip=True))
    first_module = soup.select_one("section.content.addholder > div.cmodul:nth-of-type(2)")
    if first_module:
        text = clean(first_module.get_text(" ", strip=True))
        position = re.search(r"Position\s+(.*?)(?=\s+" + re.escape(record["exhibitor_name"]) + r"\s+)", text)
        if position:
            record["booth_no"] = clean(position.group(1))
        address_text = text
        if record["exhibitor_name"] in address_text:
            address_text = address_text.split(record["exhibitor_name"], 1)[1]
        address_text = re.split(r"\btel\s*:", address_text, flags=re.I)[0]
        address_text = re.sub(r"\bPosition\b.*?\bStand\s+[\w./-]+\s*", "", address_text, flags=re.I)
        record["location"] = clean(address_text)
        if "Contatta l'azienda" in record["location"] or record["location"].startswith("-"):
            record["location"] = ""
    record["mail"] = email_from(soup)
    record["contact_number"] = phone_from(soup)
    record["domain"] = domain(record["mail"])
    if record["exhibitor_name"].lower() == "koelnmesse italia":
        record["domain"] = "koelnmesse.it"
    product_module = soup.select_one("section.content.addholder > div.cmodul:nth-of-type(3)")
    if product_module:
        parts = []
        for heading in product_module.select("h2"):
            following = []
            for node in heading.find_all_next():
                if node is not heading and node.name == "h2":
                    break
                if node.name == "p":
                    value = clean(node.get_text(" ", strip=True))
                    if value and "cookie" not in value.lower() and "privacy" not in value.lower():
                        following.append(value)
            if following:
                parts.append(f"{clean(heading.get_text(' ', strip=True))}: {' '.join(following)}")
        record["desc"] = clean(" ".join(parts))
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
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": f'"{name}" official website FSB Forum Italy 2026'},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        candidate = data.get("knowledgeGraph", {}).get("website", "")
        for result in data.get("organic", []):
            if not candidate or not domain(candidate):
                candidate = result.get("link", "")
            if domain(candidate):
                break
        return domain(candidate)
    except requests.RequestException:
        return ""


def website_contacts(record):
    if not record["domain"]:
        return record
    try:
        response = requests.get("https://" + record["domain"], headers=HEADERS, timeout=25)
        soup = BeautifulSoup(response.content, "html.parser")
        record["mail"] = record["mail"] or email_from(soup)
        record["contact_number"] = record["contact_number"] or phone_from(soup)
    except requests.RequestException:
        pass
    return record


def enrich(record):
    if not record["domain"]:
        record["domain"] = serper_domain(record["exhibitor_name"])
    return website_contacts(record)


def main():
    OUT.mkdir(exist_ok=True)
    records = list_exhibitors()
    print(f"Found {len(records)} unique exhibitors")
    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(parse_profile, records))
    for record in records:
        record.setdefault("domain", "")
        record.setdefault("mail", "")
        record.setdefault("contact_number", "")
        record.setdefault("location", "")
        record.setdefault("desc", "")
        record["country"] = record["country"] or "Italy"
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(enrich, records))
    records.sort(key=lambda item: item["exhibitor_name"].lower())
    fields = ["exhibitor_name", "domain", "contact_number", "mail", "location",
              "country", "booth_no", "desc", "profile_url"]
    base = OUT / f"{EVENT}_exhibitors"
    with (base.with_suffix(".csv")).open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    base.with_suffix(".json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Scraped {len(records)} exhibitors")
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
