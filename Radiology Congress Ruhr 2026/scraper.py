import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "RADIOLOGY_CONGRESS_RUHR_2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LIST_URL = "https://radiologiekongress.ruhr/aussteller-2026/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "radiologiekongress.ruhr", "linkedin.com", "facebook.com", "instagram.com",
    "twitter.com", "x.com", "youtube.com", "wikipedia.org", "yellowpages.com",
    "yelp.com", "google.com", "tracxn.com", "kununu.com", "10times.com",
    "feedbax.ai", "arbeitnow.com", "medica-tradefair.com", "pmc.ncbi.nlm.nih.gov",
    "leadiq.com", "kompass.com", "patsnap.com", "europeantechmap.eu",
    "airmed2026.com", "deephealth.com", "longevity.haus", "mednux.com",
    "lifehealthcare.co.za", "maptons.com", "springer.com", "jobv.eu",
}

EXHIBITORS = [
    "Alliance Medical GmbH",
    "b.e.imaging GmbH",
    "Bayer Vital GmbH",
    "Bracco Imaging Deutschland GmbH",
    "Canon Medical Systems GmbH",
    "Coreline Europe GmbH",
    "Curagita AG",
    "Dedalus HealthCare GmbH",
    "DIW-MTA Akademie GmbH",
    "Dr. Wolf, Beckelmann und Partner mbH",
    "DVTA – Dachverband für Technologen/-innen und Analytiker/-innen in der Medizin Deutschland e.V.",
    "easy Radiology AG",
    "EDL Software GmbH",
    "EIZO Europe GmbH",
    "Elsevier GmbH",
    "Evidia GmbH",
    "EXAMION GmbH und Informatics Systemhaus GmbH & Co. KG",
    "febromed GmbH & Co. KG",
    "Floy GmbH",
    "FUJIFILM Healthcare DE GmbH",
    "FUSE-AI",
    "Gleamer SAS",
    "Guerbet GmbH",
    "ICN GmbH + Co. KG",
    "INFINITT Europe GmbH",
    "Innovative Tomography Products GmbH",
    "Konica Minolta Business Solutions Deutschland GmbH",
    "medavis GmbH",
    "meddix GmbH",
    "MedEcon",
    "Medical Index GmbH",
    "Mediform GmbH",
    "Medi-ManAge Innovation GmbH",
    "mediquip Medizintechnik e.K.",
    "MEDTRON AG",
    "Merit Medical GmbH",
    "MeVis Medical Solutions AG",
    "Mint Medical GmbH",
    "MVZ Uhlenbrock U&P Service GmbH",
    "Philips GmbH Market DACH",
    "RA Radiology Advanced GmbH",
    "RADTOP Dr. Topcu & Kollegen",
    "Raya Diagnostics",
    "reif & möller diagnostic-network ag",
    "Saegeling Medizintechnik Service- und Vertriebs GmbH",
    "Siemens Healthineers AG",
    "Terumo Deutschland GmbH",
    "ulrich GmbH & Co. KG",
    "VISUS Health IT GmbH",
    "Youtilix GmbH",
    "VITAS GmbH",
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


def linkedin_url(value):
    value = value or ""
    href = value if value.startswith("http") else "https:" + value
    parsed = urlparse(href)
    if parsed.netloc.lower().removeprefix("www.") not in {
        "linkedin.com", "uk.linkedin.com", "de.linkedin.com"
    }:
        return ""
    if not re.search(r"/(company|school|in)/", parsed.path):
        return ""
    if "/admin" in parsed.path or "mycompany" in parsed.path:
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
        if "." in value and not re.search(r"[+()/ -]", value):
            continue
        if re.fullmatch(r"\d{8,16}", value) and not value.startswith(("0", "00")):
            continue
        if re.search(r"\b(?:am|pm|hours?|monday|friday)\b", value, re.I):
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


def serper_enrich(record):
    key = serper_key()
    if not key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website 2026 Germany'},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph", {})
        record["domain"] = root_domain(graph.get("website", ""))
        record["location"] = clean(graph.get("address", ""))
        record["contact_number"] = phone_from_text(clean(graph.get("phone", "")))
        record["desc"] = clean(graph.get("description", ""))
        for result in data.get("organic", []):
            if not record["domain"]:
                candidate = root_domain(result.get("link", ""))
                if candidate:
                    record["domain"] = candidate
            if not record["linkedin_url"]:
                candidate = linkedin_url(result.get("link", ""))
                if candidate:
                    record["linkedin_url"] = candidate
            if record["domain"] and record["linkedin_url"]:
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
    for name in EXHIBITORS:
        records.append({
            "exhibitor_name": name,
            "domain": "",
            "contact_number": "",
            "mail": "",
            "location": "",
            "country": "Germany",
            "booth_no": "",
            "desc": "",
            "linkedin_url": "",
            "city": "",
            "profile_url": "",
            "event_date": "2026-11-12 to 2026-11-13",
            "event_venue": "Messe Dortmund, Dortmund, Germany",
            "source_url": LIST_URL,
            "source_status": "Listed on official Radiologiekongress Ruhr 2026 exhibitor page",
        })

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
        "event_date", "event_venue", "source_url", "source_status",
    ]
    base = OUT / f"{EVENT}_exhibitors"
    with base.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    base.with_suffix(".json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Exported {len(records)} Radiologiekongress Ruhr 2026 exhibitors")
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
