import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "ITSHOWCASE_BIRMINGHAM_2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
BASE_URL = "https://itshowcase.co.uk"
EVENT_URL = f"{BASE_URL}/events/birmingham-autumn/"
LIST_URL = f"{BASE_URL}/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED_DOMAINS = {
    "itshowcase.co.uk", "linkedin.com", "facebook.com", "instagram.com",
    "twitter.com", "x.com", "youtube.com", "wikipedia.org", "yellowpages.com",
    "yelp.com", "google.com",
}

# The official home page currently publishes these exhibitor cards. Profile
# pages are visited below; profiles are retained when Birmingham Autumn is
# listed as one of their venues.
EXHIBITORS = [
    ("Advania", "/exhibitors/1-advania/", "advania.co.uk"),
    ("Enapps", "/exhibitors/enapps/", "enapps.co.uk"),
    ("Epicor", "/exhibitors/1-epicor/", "epicor.com"),
    ("Exel Computer Systems", "/exhibitors/1-exel/", "exel.co.uk"),
    ("NoBlue2", "/exhibitors/1-noblue/", "noblue2.com"),
    ("WinMan", "/exhibitors/winman/", "winman.com"),
    ("Cedar Bay", "/exhibitors/cedar-bay/", "cedar-bay.com"),
    ("Cooper Software", "/exhibitors/cooper-software/", "coopersoftware.com"),
    ("GenetiQ", "/exhibitors/genetiq/", "genetiq.co.uk"),
    ("Inforlogic", "/exhibitors/inforlogic/", "inforlogic.com"),
    ("Inixion", "/exhibitors/inixion/", "inixion.com"),
    ("iplicit", "/exhibitors/iplicit/", "iplicit.com"),
    ("Medatech", "/exhibitors/medatech/", "medatech.com"),
    ("Ochiba", "/exhibitors/ochiba/", "ochiba.com"),
    ("OneAdvanced", "/exhibitors/oneadvanced/", "oneadvanced.com"),
    ("Prerogative Limited", "/exhibitors/prerogative/", "prerogative.co.uk"),
    ("Seidor", "/exhibitors/seidor/", "seidor.com"),
    ("Syspro", "/exhibitors/syspro/", "syspro.com"),
    ("The Access Group", "/exhibitors/the-access-group/", "theaccessgroup.com"),
    ("thinc*", "/exhibitors/thinc/", "thinc.co.uk"),
    ("X3 Consulting", "/exhibitors/x3/", "x3consulting.com"),
]

CARD_DESCRIPTIONS = {
    "Advania": "A Microsoft Solutions Partner including Dynamics365.",
    "Enapps": "Empowering ambitious SMEs with tailored ERP solutions.",
    "Epicor": "45+ years' experience as a leading UK ERP solution provider.",
    "Exel Computer Systems": "UK author of flexible ERP and field-service management solutions since 1985.",
    "NoBlue2": "Delivering intelligent ERP solutions based on NetSuite.",
    "WinMan": "Off-the-shelf ERP with total flexibility.",
    "Cedar Bay": "Delivering business excellence through ERP investment.",
    "Cooper Software": "IFS Cloud ERP specialists with 20 years of experience.",
    "GenetiQ": "ERP software built for merchants, retailers, wholesalers and distributors.",
    "Inforlogic": "Experts in Infor SyteLine for manufacturing.",
    "Inixion": "ERP implementation partner with a 100% project success rate.",
    "iplicit": "Cloud-based accounting software.",
    "Medatech": "A rapid ERP implementation choice for small and medium-sized businesses.",
    "Ochiba": "SAP Business One experts.",
    "OneAdvanced": "Powering the world of work with business software.",
    "Prerogative Limited": "The UK's leading supplier of Greentree ERP.",
    "Seidor": "A global leader in SAP Cloud ERP solutions.",
    "Syspro": "ERP software built for manufacturers and distributors.",
    "The Access Group": "Business software that automates finance, drives growth and scales smart.",
    "thinc*": "Finance and ERP solutions for ambitious SMEs.",
    "X3 Consulting": "Sage X3 consultancy and rapid ERP implementation through Trax3ion Catalyst.",
}


def linkedin_url(value):
    value = value or ""
    parsed = urlparse(value if value.startswith("http") else "https:" + value)
    if parsed.netloc.lower().removeprefix("www.") not in {"linkedin.com", "uk.linkedin.com", "ca.linkedin.com"}:
        return ""
    if not re.search(r"/(company|school|in)/", parsed.path):
        return ""
    return value if value.startswith("http") else "https:" + value


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


def parse_profile(record):
    try:
        response = requests.get(record["profile_url"], headers=HEADERS, timeout=45)
        response.raise_for_status()
    except requests.RequestException:
        return record
    soup = BeautifulSoup(response.content, "html.parser")
    text = clean(soup.get_text(" ", strip=True))
    record["profile_text"] = text
    heading = soup.select_one("main h1, h1")
    if heading:
        record["exhibitor_name"] = clean(heading.get_text(" ", strip=True))

    about = next(
        (node for node in soup.find_all(["h2", "h3"])
         if "about" in clean(node.get_text(" ", strip=True)).lower()),
        None,
    )
    if about:
        description = []
        for node in about.find_all_next(["p", "div"], limit=12):
            value = clean(node.get_text(" ", strip=True))
            if value and not value.lower().startswith(("exhibitor name", "see this software")):
                description.append(value)
        record["desc"] = clean(" ".join(description))
    record["mail"] = email_from_soup(soup)
    record["contact_number"] = phone_from_text(text)
    for link in soup.select('a[href^="http"], a[href^="www."]'):
        candidate = root_domain(link.get("href", ""))
        if candidate:
            record["domain"] = candidate
            break
    linkedin = soup.select_one('a[href*="linkedin.com/"]')
    if linkedin:
        record["linkedin_url"] = linkedin_url(linkedin.get("href", ""))
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
                    record["linkedin_url"] = linkedin_url(link)
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
                record["linkedin_url"] = linkedin_url(link.get("href", ""))
    except requests.RequestException:
        pass
    return record


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = []
    for name, path, fallback_domain in EXHIBITORS:
        records.append({
            "exhibitor_name": name,
            "domain": fallback_domain,
            "contact_number": "",
            "mail": "",
            "location": "",
            "country": "United Kingdom",
            "booth_no": "",
            "desc": CARD_DESCRIPTIONS[name],
            "linkedin_url": "",
            "city": "",
            "profile_url": BASE_URL + path,
            "event_date": "2026-11-12",
            "event_venue": "Edgbaston Cricket Ground, Birmingham B5 7QU",
            "event_page_url": EVENT_URL,
            "source_url": LIST_URL,
            "source_status": "Listed exhibitor; profile checked for Birmingham Autumn",
        })

    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(parse_profile, records))
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(serper_enrich, records))
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(website_enrich, records))

    for record in records:
        record.pop("profile_text", None)
        if not record["city"] and record["location"]:
            parts = [part.strip() for part in record["location"].split(",") if part.strip()]
            if len(parts) > 1:
                record["city"] = parts[-2] if re.search(r"\d", parts[-1]) else parts[-1]
    records.sort(key=lambda item: item["exhibitor_name"].lower())

    fields = [
        "exhibitor_name", "domain", "contact_number", "mail", "location",
        "country", "booth_no", "desc", "linkedin_url", "city", "profile_url",
        "event_date", "event_venue", "event_page_url", "source_url", "source_status",
    ]
    base = OUT / f"{EVENT}_exhibitors"
    with base.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    base.with_suffix(".json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Exported {len(records)} Birmingham 2026 exhibitors")
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
