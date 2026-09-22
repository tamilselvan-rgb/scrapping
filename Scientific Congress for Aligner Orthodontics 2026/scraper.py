import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "SCIENTIFIC_CONGRESS_FOR_ALIGNER_ORTHODONTICS_2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LIST_URL = "https://www.dgao-kongress.de/aussteller"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36"}
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "google.com", "dgao-kongress.de",
    "dgao.com", "yellowpages.com", "yelp.com", "pmc.ncbi.nlm.nih.gov",
}
KNOWN_NAMES = {
    "align": "Align Technology",
    "logo_angel aligner_neu": "Angel Aligner",
    "dentalmonitoring": "DentalMonitoring",
    "graphy_2026": "Graphy",
    "ormco": "Ormco",
    "scheu_neu": "SCHEU-DENTAL",
    "solventum-logo": "Solventum",
    "abz-c9e406ef": "ABZ",
    "airflow aligner": "Airflow Aligner",
    "smartee": "Smartee",
    "elygn_2026": "Elygn",
    "logo-kachel web_forestadentneu": "FORESTADENT",
    "ortho_penthin_logo": "Ortho Penthin",
    "4_oscident-d24a8dfd": "Oscident",
    "smartee_2026": "Smartee",
    "straumann": "Straumann",
    "4_tpsolution": "TP Solution",
    "siladent logo": "siladent",
    "orthos_logo": "Orthos",
    "dmd logo sw kachel": "DMD",
    "dreve_logo_2-4bd79a72": "Dreve",
    "hammacher-57e7566c": "Hammacher",
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
        token.casefold() for token in re.findall(r"[A-Za-z0-9]{4,}", name)
        if token.casefold() not in {"aligner", "dental", "solution"}
    ]
    return any(token in normalized_host for token in tokens)


def sponsor_name(image_url):
    filename = unquote(urlparse(image_url).path.rsplit("/", 1)[-1])
    filename = re.sub(r"-1920w\.(?:png|jpe?g|webp)$", "", filename, flags=re.I)
    filename = re.sub(r"\.(?:png|jpe?g|webp)$", "", filename, flags=re.I)
    key = re.sub(r"\s+", " ", filename.replace("+", " ")).strip().casefold()
    for known, name in sorted(KNOWN_NAMES.items(), key=lambda item: len(item[0]), reverse=True):
        if known in key:
            return name
    return clean(filename.replace("+", " "))


def listing():
    response = requests.get(LIST_URL, headers=HEADERS, timeout=60)
    response.encoding = response.apparent_encoding or "utf-8"
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    records = {}
    for image in soup.select(".dmPhotoGallery img[data-src]"):
        gallery = image.find_parent(class_="dmPhotoGallery")
        heading = gallery.find_previous("h2") if gallery else None
        tier = clean(heading.get_text(" ", strip=True)) if heading else ""
        wrapper = image.find_parent(class_="image-container")
        link = wrapper.select_one("a[href]") if wrapper else None
        href = link.get("href", "") if link else ""
        name = sponsor_name(image.get("data-src", ""))
        domain = root_domain(href)
        key = name.casefold()
        if key not in records:
            records[key] = {
                "exhibitor_name": name,
                "domain": domain,
                "contact_number": "",
                "mail": "",
                "location": "",
                "country": "Germany",
                "booth_no": "",
                "desc": f"{tier} sponsor/exhibitor at the Scientific Congress for Aligner Orthodontics 2026.",
                "linkedin_url": "",
                "city": "",
                "profile_url": href or LIST_URL,
                "sponsor_tier": tier,
            }
        elif domain and not records[key]["domain"]:
            records[key]["domain"] = domain
    return list(records.values())


def serper_key():
    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"\'')
    return ""


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
            json={"q": f'"{record["exhibitor_name"]}" official website DGAO 2026'},
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
    except requests.RequestException:
        pass
    return record


def enrich_website(record):
    if not record["domain"]:
        return record
    try:
        response = requests.get("https://" + record["domain"], headers=HEADERS, timeout=25)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text(" ", strip=True)
        record["mail"] = email_from_text(text)
        record["contact_number"] = record["contact_number"] or phone_from_text(text)
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
    records = listing()
    print(f"Found {len(records)} unique 2026 exhibitors")
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(enrich_domain, records))
    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(enrich_website, records))
    for record in records:
        record.pop("sponsor_tier", None)
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
