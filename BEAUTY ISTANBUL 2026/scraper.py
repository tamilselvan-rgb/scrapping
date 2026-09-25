import csv
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from pypdf import PdfReader


EVENT = "BEAUTY_ISTANBUL_2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
PDF_URL = "http://beauty-istanbul.com/Exhibitors-BEAUTYISTANBUL2026.pdf"
PDF_PATH = ROOT / "Exhibitors-BEAUTYISTANBUL2026.pdf"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ExhibitorResearch/1.0)"}
FIELDS = [
    "company_name", "booth", "description", "email", "mobile_primary",
    "domain", "full_address", "city", "linkedin_url",
]
BLOCKED = {
    "beauty-istanbul.com", "facebook.com", "instagram.com", "linkedin.com",
    "twitter.com", "x.com", "youtube.com", "wikipedia.org", "yellowpages.com",
    "yelp.com", "google.com",
}
COUNTRIES = [
    "UNITED STATES OF AMERICA", "UNITED ARAB EMIRATES", "UNITED KINGDOM",
    "SOUTH AFRICA", "CZECH REPUBLIC", "HONG KONG", "NORTH MACEDONIA",
    "REPUBLIC OF KOREA", "KOREA, REPUBLIC OF", "SAUDI ARABIA",
    "NEW ZEALAND", "THE NETHERLANDS", "ALBANIA", "ALGERIA", "AUSTRALIA",
    "BELARUS", "BELGIUM", "BRAZIL", "BULGARIA", "CANADA", "CHINA",
    "CROATIA", "CYPRUS", "EGYPT", "FRANCE", "GEORGIA", "GERMANY",
    "GREECE", "INDIA", "INDONESIA", "IRAN", "ISRAEL", "ITALY", "JAPAN",
    "KAZAKHSTAN", "MALAYSIA", "MEXICO", "NETHERLANDS", "PAKISTAN",
    "POLAND", "PORTUGAL", "QATAR", "ROMANIA", "RUSSIA", "SERBIA",
    "SINGAPORE", "SLOVAKIA", "SLOVENIA", "SOUTH KOREA", "SPAIN",
    "SWITZERLAND", "TAIWAN", "THAILAND", "TUNISIA", "TURKEY", "UKRAINE",
    "VIETNAM",
]


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def domain_url(value):
    value = clean(value)
    if not value:
        return ""
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if not host or "." not in host:
        return ""
    if any(host == item or host.endswith("." + item) for item in BLOCKED):
        return ""
    return f"{parsed.scheme or 'https'}://{host}"


def website_from_text(text):
    tld = (
        r"\.com|\.co\.uk|\.net|\.org|\.eu|\.dz|\.by|\.br|\.cn|\.de|\.fr|"
        r"\.it|\.tr|\.ru|\.ae|\.in|\.jp|\.kr|\.my|\.us|\.co|\.es|\.pl|\.ro"
    )
    match = re.search(
        rf"((?:https?://|www\.)[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+?"
        rf"(?:{tld}))(?=[A-Z; ]|$)",
        text,
        re.I,
    )
    return domain_url(match.group(1)) if match else ""


def parse_row(text):
    text = clean(text)
    stand_match = re.search(
        r"Hall\s+([A-Za-z0-9]+)\s+([A-Za-z0-9]+)\s+([A-Za-z0-9]+)\s*$",
        text, re.I,
    )
    range_match = re.search(
        r"Hall\s+(\d)([A-Za-z])\s+(\d+)-([A-Za-z]\w*)\s+(\d+)\s*$",
        text, re.I,
    )
    if range_match and (not stand_match or range_match.start() > stand_match.start()):
        booth = f"Hall {range_match.group(1)} / {range_match.group(2)} {range_match.group(3)}-{range_match.group(4)} {range_match.group(5)}"
        prefix = text[:range_match.start()].strip()
    elif stand_match:
        booth = f"Hall {stand_match.group(1)} / {stand_match.group(2)} {stand_match.group(3)}"
        prefix = text[:stand_match.start()].strip()
    else:
        return None
    website_marker = re.search(r"(?:https?://|www\.)", prefix, re.I)
    country_matches = []
    for candidate in COUNTRIES:
        country_matches.extend(
            match for match in re.finditer(rf"\b{re.escape(candidate)}\b", prefix, re.I)
            if not website_marker or match.start() < website_marker.start()
        )
    if not country_matches:
        return None
    country_match = max(country_matches, key=lambda match: match.start())
    country = country_match.group(0)
    company = prefix[:country_match.start()].strip()
    trailing_data = prefix[country_match.end():].strip()
    website = website_from_text(trailing_data)
    return {
        "company_name": clean(company),
        "booth": booth,
        "description": "",
        "email": "",
        "mobile_primary": "",
        "domain": website,
        "full_address": "",
        "city": "",
        "linkedin_url": "",
    }


def parse_pdf():
    response = requests.get(PDF_URL, headers=HEADERS, timeout=90)
    response.raise_for_status()
    PDF_PATH.write_bytes(response.content)
    reader = PdfReader(str(PDF_PATH))
    records = []
    for page in reader.pages:
        lines = (page.extract_text() or "").splitlines()
        buffer = []
        for line in lines:
            line = clean(line)
            if not line or line.isdigit() or line.startswith("COMPANY COUNTRY"):
                continue
            buffer.append(line)
            if re.search(
                r"(?:Hall\s+[A-Za-z0-9]+\s+[A-Za-z0-9]+\s+[A-Za-z0-9]+|"
                r"Hall\s+\d[A-Za-z]\s+\d+-[A-Za-z]\w*\s+\d+)\s*$",
                line, re.I,
            ):
                record = parse_row(" ".join(buffer))
                if record and record["company_name"]:
                    records.append(record)
                buffer = []
    unique = {f"{r['company_name'].casefold()}|{r['booth']}": r for r in records}
    return list(unique.values())


def serper_key():
    path = ROOT.parent / ".env"
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip().strip("\"'")
    return ""


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
            json={"q": f'"{record["company_name"]}" official website Beauty Istanbul 2026',
                  "gl": "tr", "hl": "en", "num": 10},
            timeout=45,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph") or {}
        record["domain"] = domain_url(graph.get("website", ""))
        if not record["domain"]:
            for result in data.get("organic", []):
                candidate = domain_url(result.get("link", ""))
                if candidate:
                    record["domain"] = candidate
                    break
    except requests.RequestException as exc:
        print(f"Serper failed: {record['company_name']}: {exc}")
    return record


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = parse_pdf()
    print(f"Found {len(records)} PDF exhibitors")
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(serper_enrich, [record for record in records if not record["domain"]]))
    records.sort(key=lambda item: item["company_name"].casefold())
    normalized = [{field: record.get(field, "") for field in FIELDS} for record in records]
    base = OUT / f"{EVENT}_exhibitors"
    with base.with_suffix(".csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(normalized)
    base.with_suffix(".json").write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print(f"Domain coverage: {sum(bool(r['domain']) for r in records)}/{len(records)}")
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
