import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader


EVENT = "RAILWAY_INFRASTRUCTURE_NETWORKING_2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
PDF_URL = "https://www.rinevents.co.uk/wp-content/uploads/2025/05/RIN__ExhibitorListGLASGOW25.pdf"
PDF_PATH = ROOT / "RIN_Glasgow_2026_exhibitor_list.pdf"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "google.com", "yellowpages.com", "yelp.com",
    "rinevents.co.uk", "10times.com", "zoominfo.com", "crunchbase.com",
    "find-and-update.company-information.service.gov.uk",
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
    return match.group(0).lower() if match else ""


def phone_from_text(text):
    for value in re.findall(r"(?<!\w)(?:\+|00)?\d[\d\s()./-]{7,}\d", text or ""):
        value = clean(value)
        digits = re.sub(r"\D", "", value)
        if re.search(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b", value):
            continue
        if re.search(r"\b(?:19|20)\d{2}\b", value) or "978-" in value:
            continue
        if 8 <= len(digits) <= 16:
            return value
    return ""


def relevant_search_result(result, name):
    title = clean(result.get("title", "")).casefold()
    host = (urlparse(result.get("link", "")).hostname or "").lower()
    normalized_name = re.sub(r"[^a-z0-9]", "", name.casefold())
    normalized_title = re.sub(r"[^a-z0-9]", "", title)
    normalized_host = re.sub(r"[^a-z0-9]", "", host)
    if normalized_name and normalized_name in normalized_title:
        return True
    tokens = [
        token.casefold() for token in re.findall(r"[A-Za-z0-9]{3,}", name)
        if token.casefold() not in {
            "ltd", "limited", "group", "uk", "international", "solutions",
            "services", "rail", "railway", "systems", "technology",
        }
    ]
    if not tokens:
        return False
    return any(token in normalized_host for token in tokens if len(token) >= 5)


def parse_pdf():
    response = requests.get(PDF_URL, headers=HEADERS, timeout=60)
    response.raise_for_status()
    PDF_PATH.write_bytes(response.content)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(PDF_PATH)).pages)
    raw = [clean(line) for line in text.splitlines() if clean(line)]
    names = []
    skip = {
        "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M",
        "N", "O", "P", "R", "S", "T", "U", "V", "W", "Y",
        "RIN EXHIBITOR LIST", "GLASGOW 2026", "-- 1 of 2 --", "-- 2 of 2 --",
    }
    continuations = {"Association", "Limited", "LTD", "Consultants Ltd"}
    for line in raw:
        if line in skip or re.fullmatch(r"\d+", line):
            continue
        if names and (
            line in continuations
            or line == "LT D"
            or names[-1].endswith(("Contractors", "Products UK", "Environmental"))
            or names[-1].startswith("Voestalpine Turnout Technology UK")
        ):
            names[-1] = clean(names[-1] + " " + line)
        else:
            names.append(line)
    # The PDF's text layer splits these compound names at page line breaks.
    records = []
    seen = set()
    for name in names:
        name = clean(name)
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        records.append({
            "exhibitor_name": name,
            "domain": "",
            "contact_number": "",
            "mail": "",
            "location": "",
            "country": "United Kingdom",
            "booth_no": "",
            "desc": "Exhibitor listed for Railway Infrastructure Networking Glasgow 2026.",
            "linkedin_url": "",
            "city": "",
            "profile_url": PDF_URL,
        })
    return records


def serper_key():
    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"\'')
    return ""


def serper_enrich(record):
    key = serper_key()
    if not key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website RIN Glasgow 2026'},
            timeout=30,
        )
        response.raise_for_status()
        graph = response.json().get("knowledgeGraph", {})
        record["domain"] = root_domain(graph.get("website", ""))
        if not record["domain"]:
            for result in response.json().get("organic", []):
                candidate = root_domain(result.get("link", ""))
                if candidate and relevant_search_result(result, record["exhibitor_name"]):
                    record["domain"] = candidate
                    break
        record["location"] = clean(graph.get("address", ""))
        record["contact_number"] = clean(graph.get("phone", ""))
        record["mail"] = clean(graph.get("email", ""))
    except requests.RequestException:
        pass
    return record


def website_enrich(record):
    if not record["domain"]:
        return record
    try:
        response = requests.get("https://" + record["domain"], headers=HEADERS, timeout=25)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        record["mail"] = record["mail"] or email_from_text(soup.get_text(" ", strip=True))
        record["contact_number"] = record["contact_number"] or phone_from_text(
            soup.get_text(" ", strip=True)
        )
        meta = soup.select_one('meta[name="description"], meta[property="og:description"]')
        if meta and meta.get("content"):
            record["desc"] = clean(meta["content"])
        linkedin = soup.select_one('a[href*="linkedin.com/"]')
        if linkedin:
            record["linkedin_url"] = linkedin.get("href", "")
    except requests.RequestException:
        pass
    return record


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = parse_pdf()
    print(f"Found {len(records)} 2026 exhibitors in PDF")
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(serper_enrich, records))
    with ThreadPoolExecutor(max_workers=16) as pool:
        records = list(pool.map(website_enrich, records))
    records.sort(key=lambda item: item["exhibitor_name"].lower())
    fields = [
        "exhibitor_name", "domain", "contact_number", "mail", "location",
        "country", "booth_no", "desc", "linkedin_url", "city", "profile_url",
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
