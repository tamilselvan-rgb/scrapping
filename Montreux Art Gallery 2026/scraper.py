import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "MONTREUX_ART_GALLERY_2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LIST_URL = "https://www.montreux.art/montreuxartgallery/exposants/galeries"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "google.com", "montreux.art",
    "squarespace.com", "squarespace-cdn.com",
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
        if 8 <= len(digits) <= 16 and not re.search(r"(?<!\d)20\d{2}(?!\d)", value):
            return value
    return ""


def address_from_json_ld(soup):
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        objects = data if isinstance(data, list) else [data]
        for item in objects:
            if not isinstance(item, dict):
                continue
            address = item.get("address", {})
            if isinstance(address, dict):
                value = ", ".join(
                    clean(address.get(key, "")) for key in
                    ("streetAddress", "postalCode", "addressLocality", "addressRegion", "addressCountry")
                    if clean(address.get(key, ""))
                )
            else:
                value = clean(address)
            if value:
                yield value, clean(item.get("telephone", "")), clean(item.get("email", ""))


def split_location(location):
    location = clean(location)
    if not location:
        return "", ""
    parts = [clean(part) for part in re.split(r",|\n", location) if clean(part)]
    return location, parts[-1] if len(parts) > 1 else ""


def listing():
    response = requests.get(LIST_URL, headers=HEADERS, timeout=60)
    response.encoding = response.apparent_encoding or "utf-8"
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    records = []
    for figure in soup.select(".gallery-masonry-item"):
        image = figure.select_one("img[data-image], img[data-src]")
        if not image:
            continue
        image_url = image.get("data-image") or image.get("data-src")
        filename = unquote(urlparse(image_url).path.rsplit("/", 1)[-1])
        name = clean(re.sub(r"\.(?:png|jpe?g|webp|gif)$", "", filename, flags=re.I))
        name = re.sub(r"\s+", " ", name.replace("+", " "))
        website = figure.select_one("a.gallery-masonry-image-link[href]")
        href = website.get("href", "") if website else ""
        records.append({
            "exhibitor_name": name,
            "domain": root_domain(href),
            "contact_number": "",
            "mail": "",
            "location": "",
            "country": "Switzerland",
            "booth_no": "",
            "desc": "",
            "linkedin_url": "",
            "profile_url": href or LIST_URL,
            "event_source": LIST_URL,
        })
    return records


def enrich_website(record):
    if not record["domain"]:
        return record
    root = "https://" + record["domain"]
    urls = [root]
    try:
        response = requests.get(root, headers=HEADERS, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for address, phone, email in address_from_json_ld(soup):
            record["location"] = record["location"] or address
            record["contact_number"] = record["contact_number"] or phone
            record["mail"] = record["mail"] or email
        text = soup.get_text(" ", strip=True)
        record["mail"] = record["mail"] or email_from_text(text)
        record["contact_number"] = record["contact_number"] or phone_from_text(text)
        for link in soup.select("a[href]"):
            label = clean(link.get_text(" ", strip=True) + " " + link.get("href", "")).lower()
            if any(word in label for word in ("contact", "kontakt", "contacto", "impressum", "about")):
                candidate = urljoin(root, link.get("href", ""))
                if urlparse(candidate).hostname == urlparse(root).hostname:
                    urls.append(candidate)
        for url in urls[1:3]:
            try:
                page = requests.get(url, headers=HEADERS, timeout=20)
                page.raise_for_status()
                detail = BeautifulSoup(page.text, "html.parser")
                for address, phone, email in address_from_json_ld(detail):
                    record["location"] = record["location"] or address
                    record["contact_number"] = record["contact_number"] or phone
                    record["mail"] = record["mail"] or email
                text = detail.get_text(" ", strip=True)
                record["mail"] = record["mail"] or email_from_text(text)
                record["contact_number"] = record["contact_number"] or phone_from_text(text)
            except requests.RequestException:
                continue
    except requests.RequestException:
        pass
    return record


def serper_key():
    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"\'')
    return ""


def enrich_missing_domain(record):
    if record["domain"]:
        return record
    key = serper_key()
    if not key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website Montreux Art Gallery 2026'},
            timeout=30,
        )
        response.raise_for_status()
        graph = response.json().get("knowledgeGraph", {})
        record["domain"] = root_domain(graph.get("website", ""))
        record["location"] = clean(graph.get("address", "")) or record["location"]
        record["contact_number"] = clean(graph.get("phone", "")) or record["contact_number"]
    except requests.RequestException:
        pass
    return record


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = listing()
    print(f"Found {len(records)} current gallery cards")
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(enrich_website, records))
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(enrich_missing_domain, records))
    for record in records:
        record["location"], record["city"] = split_location(record["location"])
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
    print(f"Scraped {len(records)} galleries")
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
