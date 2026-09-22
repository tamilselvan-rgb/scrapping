import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "BEAUTY_PROFS_SHOW_2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LIST_URL = "https://beauty-profs.com/les-exposants/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "google.com", "beauty-profs.com",
    "yellowpages.com", "yelp.com",
}
CATEGORY_TRANSLATIONS = {
    "Produits et matériel pour ongles": "Nail products and equipment",
    "Esthétique du regard": "Eye beauty",
    "Soins experts/cosmétiques": "Professional skincare and cosmetics",
    "Formation & coaching business": "Business training and coaching",
    "Tattoos et piercings": "Tattoos and piercings",
    "Blanchiment dentaire": "Teeth whitening",
    "Bijoux": "Jewelry",
    "Dermopigmentation": "Dermopigmentation",
    "Shopping": "Shopping",
    "services": "Services",
    "bronzage": "Tanning",
    "Capillaire": "Haircare",
    "Technologies esthétiques": "Aesthetic technologies",
    "Epilation": "Hair removal",
    "Digital": "Digital",
    "Maquillage": "Makeup",
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


def listing():
    response = requests.get(LIST_URL, headers=HEADERS, timeout=60)
    response.encoding = response.apparent_encoding or "utf-8"
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    records = {}
    for card in soup.select("section.exposants-grid li.item"):
        link = card.select_one("a.exposant-infos[href]")
        image = card.select_one("img[alt]")
        if not link or not image:
            continue
        profile_url = link.get("href", "")
        name = clean(image.get("alt", ""))
        emplacement_node = card.select_one(".exposant-emplacement")
        category_node = card.select_one(".exposant-categorie")
        emplacement = clean(emplacement_node.get_text(" ", strip=True)) if emplacement_node else ""
        category = clean(category_node.get_text(" ", strip=True)) if category_node else ""
        stand_match = re.search(r"(?:stand)\s+(.+)$", emplacement, re.I)
        record = {
            "exhibitor_name": name,
            "domain": "",
            "contact_number": "",
            "mail": "",
            "location": "Parc Chanot, Rond-Point du Prado, 13008 Marseille, France",
            "country": "France",
            "booth_no": f"Stand {stand_match.group(1)}" if stand_match else "",
            "desc": CATEGORY_TRANSLATIONS.get(category, category),
            "linkedin_url": "",
            "city": "Marseille",
            "profile_url": profile_url,
            "event_source": LIST_URL,
        }
        records[profile_url] = record
    return list(records.values())


def parse_profile(record):
    try:
        response = requests.get(record["profile_url"], headers=HEADERS, timeout=45)
        response.encoding = response.apparent_encoding or "utf-8"
        response.raise_for_status()
    except requests.RequestException:
        return record
    soup = BeautifulSoup(response.text, "html.parser")
    title = soup.select_one(".expo")
    if title:
        record["exhibitor_name"] = clean(title.get_text(" ", strip=True))
    emplacement = soup.select_one(".exposant-emplacement")
    if emplacement:
        value = clean(emplacement.get_text(" ", strip=True))
        match = re.search(r"(?:stand)\s+(.+)$", value, re.I)
        record["booth_no"] = f"Stand {match.group(1)}" if match else record["booth_no"]
    category = soup.select_one(".exposant-categorie")
    description = soup.select_one(".exposant-description, .exposant-content p, article p")
    if category and not record["desc"]:
        category_text = clean(category.get_text(" ", strip=True))
        record["desc"] = CATEGORY_TRANSLATIONS.get(category_text, category_text)
    description = soup.select_one(".exposant-apropos")
    if description:
        record["desc"] = clean(description.get_text(" ", strip=True))
    text = soup.get_text(" ", strip=True)
    record["mail"] = email_from_text(text)
    record["contact_number"] = phone_from_text(text)
    return record


def serper_key():
    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"\'')
    return ""


def relevant_result(result, name):
    title = clean(result.get("title", "")).casefold()
    host = (urlparse(result.get("link", "")).hostname or "").lower()
    normalized_name = re.sub(r"[^a-z0-9]", "", name.casefold())
    normalized_title = re.sub(r"[^a-z0-9]", "", title)
    normalized_host = re.sub(r"[^a-z0-9]", "", host)
    if normalized_name and normalized_name in normalized_title:
        return True
    tokens = [t for t in re.findall(r"[A-Za-z0-9]{4,}", name.casefold())]
    return any(token in normalized_host for token in tokens)


def enrich_domain(record):
    key = serper_key()
    if not key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website Beauty Profs 2026'},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph", {})
        record["domain"] = root_domain(graph.get("website", ""))
        if not record["domain"]:
            for result in data.get("organic", []):
                candidate = root_domain(result.get("link", ""))
                if candidate and relevant_result(result, record["exhibitor_name"]):
                    record["domain"] = candidate
                    break
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
        record["mail"] = record["mail"] or email_from_text(text)
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
    print(f"Found {len(records)} official 2026 exhibitor profiles")
    with ThreadPoolExecutor(max_workers=16) as pool:
        records = list(pool.map(parse_profile, records))
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(enrich_domain, records))
    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(enrich_website, records))
    records.sort(key=lambda item: item["exhibitor_name"].lower())
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
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
