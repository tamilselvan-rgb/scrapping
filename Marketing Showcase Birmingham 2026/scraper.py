import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "MARKETING_SHOWCASE_BIRMINGHAM_2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
BASE_URL = "https://mktgshowcase.co.uk"
LIST_URL = f"{BASE_URL}/"
EVENT_URL = f"{BASE_URL}/events/birmingham/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "mktgshowcase.co.uk", "linkedin.com", "facebook.com", "instagram.com",
    "twitter.com", "x.com", "youtube.com", "wikipedia.org", "yellowpages.com",
    "yelp.com", "google.com",
}

EXHIBITORS = [
    ("Force24", "force24.co.uk"),
    ("Leadoo Marketing Technologies", "leadoo.com"),
    ("Webmart", "webmartuk.com"),
    ("Workbooks CRM", "workbooks.com"),
    ("Allwag Promotions", "allwag.co.uk"),
    ("Beyond the Book", "beyondthebook.co.uk"),
    ("Bobble Digital", "bobbledigital.com"),
    ("Campaigner", "campaigner.com"),
    ("Canny Creative", "canny-creative.com"),
    ("Dark Horse", "darkhorsedesign.co.uk"),
    ("Digital Landscope", "digitallandscope.com"),
    ("Dotdigital", "dotdigital.com"),
    ("etc Branding", "etcbranding.co.uk"),
    ("Hot House Digital", "hothousedigital.co.uk"),
    ("Innovation Visual", "innovationvisual.com"),
    ("Lulu Animation", "luluanimation.com"),
    ("Manic Merchandise", "manicmerchandise.com"),
    ("Morf", "morf.tech"),
    ("Nautilus Marketing", "nautilusmarketing.co.uk"),
    ("Nimlok", "nimlok.co.uk"),
    ("Phoenix Digital Ltd", "phoenix-digital.co.uk"),
    ("Pop-Up Banners Ltd", "popupbanners.net"),
    ("The SEO Works", "seoworks.com"),
    ("So Contented", "socontented.com"),
    ("Sound Media", "soundmedia.co.uk"),
    ("Spotler", "spotler.com"),
    ("The Animation Guys", "theanimationguys.com"),
    ("The Video Ad Agency", "thevideoadagency.co.uk"),
    ("OTB", "otb.agency"),
    ("Updesigners", "updesigners.co.uk"),
    ("Uplyft", "uplyft.com"),
    ("Userboost", "userboost.com"),
    ("WebBox", "webbox.co.uk"),
    ("Wild Thang", "wildthang.co.uk"),
]

DESCRIPTIONS = {
    "Force24": "Marketing automation beyond email.",
    "Leadoo Marketing Technologies": "Lead generation technology helping businesses convert web visitors to customers.",
    "Webmart": "Sustainable print and digital marketing services.",
    "Workbooks CRM": "A no-nonsense CRM provider.",
    "Allwag Promotions": "Ethically sourced promotional products and corporate clothing.",
    "Beyond the Book": "Trusted to deliver exceptional recruitment.",
    "Bobble Digital": "An agile digital marketing agency.",
    "Campaigner": "Email and SMS marketing software.",
    "Canny Creative": "Branding, websites and content that get results.",
    "Dark Horse": "Digital marketing designed to avoid mediocre results.",
    "Digital Landscope": "Conversion growth through Google organic and paid search.",
    "Dotdigital": "Marketing automation technology.",
    "etc Branding": "Branded merchandise consultancy.",
    "Hot House Digital": "Simplifying the search for organic growth.",
    "Innovation Visual": "Transforming results through AI technology and people.",
    "Lulu Animation": "Real-world connections through animation.",
    "Manic Merchandise": "Eco promotional items with a twist.",
    "Morf": "Limitless customisation, instantly visualised.",
    "Nautilus Marketing": "Marketing services for businesses seeking practical growth.",
    "Nimlok": "Exhibition and exhibiting-performance solutions.",
    "Phoenix Digital Ltd": "Web and digital experts.",
    "Pop-Up Banners Ltd": "Portable branding solutions.",
    "The SEO Works": "Digital growth experts offering SEO, PPC and web services.",
    "So Contented": "Brand voice and conversion copy that drives action.",
    "Sound Media": "Podcast strategies and solutions.",
    "Spotler": "Marketing technology for businesses looking to improve customer engagement.",
    "The Animation Guys": "Thoughtful video production services.",
    "The Video Ad Agency": "Video advertising planning, production and execution.",
    "OTB": "Creative marketing agency for ambitious brands.",
    "Updesigners": "Design services shaping the future in graphic design.",
    "Uplyft": "Risk-free conversion rate optimisation for ecommerce brands.",
    "Userboost": "Conversion optimisation for considered-purchase brands.",
    "WebBox": "Websites built to convert and marketing that drives growth.",
    "Wild Thang": "Branded merchandise, clothing and print.",
}


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


def linkedin_url(value):
    value = value or ""
    href = value if value.startswith("http") else "https:" + value
    parsed = urlparse(href)
    if parsed.netloc.lower().removeprefix("www.") not in {"linkedin.com", "uk.linkedin.com", "ca.linkedin.com"}:
        return ""
    if not re.search(r"/(company|school|in)/", parsed.path):
        return ""
    return href


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
        if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", value):
            continue
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
    slug = re.sub(r"[^a-z0-9]+", "-", record["exhibitor_name"].lower()).strip("-")
    record["profile_url"] = f"{BASE_URL}/exhibitors/{slug}/"
    try:
        response = requests.get(record["profile_url"], headers=HEADERS, timeout=40)
        response.raise_for_status()
    except requests.RequestException:
        return record
    soup = BeautifulSoup(response.content, "html.parser")
    text = clean(soup.get_text(" ", strip=True))
    record["mail"] = email_from_soup(soup)
    record["contact_number"] = phone_from_text(text)
    about = next(
        (node for node in soup.find_all(["h2", "h3"])
         if "about" in clean(node.get_text(" ", strip=True)).lower()),
        None,
    )
    if about:
        parts = []
        for node in about.find_all_next(["p"], limit=8):
            value = clean(node.get_text(" ", strip=True))
            if value and "see this" not in value.lower():
                parts.append(value)
        if parts:
            record["desc"] = clean(" ".join(parts))
    for link in soup.select('a[href^="http"], a[href^="www."]'):
        candidate = root_domain(link.get("href", ""))
        if candidate:
            record["domain"] = candidate
            break
    link = soup.select_one('a[href*="linkedin.com/"]')
    if link:
        record["linkedin_url"] = linkedin_url(link.get("href", ""))
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
                candidate = linkedin_url(result.get("link", ""))
                if candidate:
                    record["linkedin_url"] = candidate
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
    for name, domain in EXHIBITORS:
        records.append({
            "exhibitor_name": name,
            "domain": domain,
            "contact_number": "",
            "mail": "",
            "location": "",
            "country": "United Kingdom",
            "booth_no": "",
            "desc": DESCRIPTIONS[name],
            "linkedin_url": "",
            "city": "",
            "profile_url": "",
            "event_date": "2026-11-12",
            "event_venue": "Edgbaston Stadium, Birmingham",
            "event_page_url": EVENT_URL,
            "source_url": LIST_URL,
            "source_status": "Listed in current marketingSHOWCASE 2026 exhibitor section",
        })

    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(profile, records))
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(serper_enrich, records))
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(website_enrich, records))

    for record in records:
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
    print(f"Exported {len(records)} Birmingham 2026 marketing exhibitors")
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
