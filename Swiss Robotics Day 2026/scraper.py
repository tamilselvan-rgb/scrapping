import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "SWISS_ROBOTICS_DAY"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LIST_URL = "https://swissroboticsday.ch/srd26/exhibitors/"
EVENT_URL = "https://swissroboticsday.ch/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "swissroboticsday.ch", "linkedin.com", "facebook.com", "instagram.com",
    "twitter.com", "x.com", "youtube.com", "wikipedia.org", "yellowpages.com",
    "yelp.com", "google.com", "10times.com", "kompass.com", "tracxn.com",
    "drivesweb.com",
}
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location",
    "country", "booth_no", "legal_name", "desc", "linkedin_url", "city",
    "profile_url", "event_date", "event_venue", "source_url", "source_year",
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
        "ag", "gmbh", "sa", "lab", "group", "systems", "robotics",
        "technology", "technologies", "university", "zurich",
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


def phone_from_soup(soup):
    tel = soup.select_one('a[href^="tel:"]')
    if tel and valid_phone(tel.get("href", "")[4:]):
        return clean(tel.get("href", "")[4:])
    for candidate in re.findall(r"(?<!\w)(?:\+|00)?\d[\d\s()./-]{7,}\d", soup.get_text(" ", strip=True)):
        if valid_phone(candidate):
            return clean(candidate)
    return ""


def email_from_button(button):
    user = clean(button.get("data-u", ""))
    domain = clean(button.get("data-d", ""))
    return f"{user}@{domain}".lower() if user and domain else ""


def serper_key():
    env = ROOT.parent / ".env"
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"\'')
    return ""


def parse_entry(article):
    face = article.select_one(".sxg26-face")
    detail = article.select_one(".sxg26-detail")
    name = clean((face or article).select_one(".sxg26-name").get_text(" ", strip=True))
    legal_node = (face or article).select_one(".sxg26-legal")
    site_node = (face or article).select_one(".sxg26-site")
    booth_node = (face or article).select_one(".sxg26-booth")
    booth = clean(booth_node.get_text(" ", strip=True)) if booth_node else ""
    if "to be assigned" in booth.lower():
        booth = ""
    site = clean(site_node.get_text(" ", strip=True)) if site_node else ""
    if detail:
        website_link = detail.select_one(".sxg26-kv a[href^='http']")
        if website_link:
            site = website_link.get("href", site)
    description_nodes = detail.select(".sxg26-main .sxg26-long") if detail else []
    desc = clean(" ".join(node.get_text(" ", strip=True) for node in description_nodes))
    if not desc:
        blurb = (face or article).select_one(".sxg26-blurb")
        desc = clean(blurb.get_text(" ", strip=True)) if blurb else ""
    if desc.lower().startswith("this exhibitor is confirmed for the show"):
        desc = ""
    mail_button = detail.select_one(".sxg26-mail") if detail else None
    socials = detail.select(".sxg26-socials a") if detail else []
    social = next((linkedin_url(link.get("href", "")) for link in socials if linkedin_url(link.get("href", ""))), "")
    return {
        "exhibitor_name": name,
        "domain": root_domain(site),
        "contact_number": "",
        "mail": email_from_button(mail_button) if mail_button else "",
        "location": "",
        "country": "Switzerland",
        "booth_no": booth,
        "legal_name": clean(legal_node.get_text(" ", strip=True)) if legal_node else "",
        "desc": desc,
        "linkedin_url": social,
        "city": "Zurich",
        "profile_url": f"{LIST_URL}#{article.get('id', '')}",
        "event_date": "2026-11-13",
        "event_venue": "StageOne Event & Convention Center, Elias-Canetti-Strasse 146, 8050 Zurich, Switzerland",
        "source_url": LIST_URL,
        "source_year": "2026",
    }


def listing():
    response = requests.get(LIST_URL, headers=HEADERS, timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    records = [parse_entry(article) for article in soup.select("article.sxg26-entry")]
    if not records:
        raise RuntimeError("No Swiss Robotics Day 2026 exhibitor cards found")
    return records


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
            json={"q": f'"{record["exhibitor_name"]}" official website 2026 robotics'},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph", {})
        graph_domain = root_domain(graph.get("website", ""))
        if graph_domain and plausible_domain(record["exhibitor_name"], graph_domain):
            record["domain"] = graph_domain
            record["location"] = clean(graph.get("address", ""))
            if not record["contact_number"] and valid_phone(graph.get("phone", "")):
                record["contact_number"] = clean(graph.get("phone", ""))
            if not record["desc"]:
                record["desc"] = clean(graph.get("description", ""))
        for item in data.get("organic", []):
            if not record["domain"]:
                candidate = root_domain(item.get("link", ""))
                if candidate and plausible_domain(record["exhibitor_name"], candidate):
                    record["domain"] = candidate
            if not record["linkedin_url"]:
                candidate = linkedin_url(item.get("link", ""))
                if candidate:
                    record["linkedin_url"] = candidate
    except requests.RequestException:
        pass
    return record


def website_enrich(record):
    if not record["domain"]:
        return record
    try:
        response = requests.get(
            "https://" + record["domain"], headers=HEADERS, timeout=20
        )
        soup = BeautifulSoup(response.content, "html.parser")
        if not record["contact_number"]:
            record["contact_number"] = phone_from_soup(soup)
        if not record["linkedin_url"]:
            link = soup.select_one('a[href*="linkedin.com/"]')
            if link:
                record["linkedin_url"] = linkedin_url(link.get("href", ""))
    except requests.RequestException:
        pass
    return record


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = listing()
    with ThreadPoolExecutor(max_workers=16) as pool:
        records = list(pool.map(serper_enrich, records))
    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(website_enrich, records))
    records.sort(key=lambda item: item["exhibitor_name"].casefold())
    base = OUT / f"{EVENT}_2026_exhibitors"
    with base.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    base.with_suffix(".json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Exported {len(records)} Swiss Robotics Day 2026 exhibitors")
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
