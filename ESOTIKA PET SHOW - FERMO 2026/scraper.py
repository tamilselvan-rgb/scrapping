import csv
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "ESOTIKA_PET_SHOW_FERMO_2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LIST_URL = "https://www.esotikapetshow.it/espositori/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ExhibitorResearch/1.0)"}
BLOCKED = {
    "esotikapetshow.it", "facebook.com", "instagram.com", "linkedin.com",
    "twitter.com", "x.com", "youtube.com", "wikipedia.org", "yellowpages.com",
    "yelp.com", "google.com", "cookiedatabase.org", "complianz.io",
    "maxxdesign.it",
    "expofinder.com",
}
FIELDS = [
    "company_name", "domain", "description", "booth", "email", "city",
    "full_address", "mobile_primary",
]


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def root_domain(value):
    value = clean(value)
    if not value:
        return ""
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    host = (urlparse(value).hostname or "").lower().removeprefix("www.")
    if not host or "." not in host:
        return ""
    if any(host == item or host.endswith("." + item) for item in BLOCKED):
        return ""
    return host


def fetch(url):
    for attempt in range(4):
        try:
            response = requests.get(url, headers=HEADERS, timeout=60)
            response.raise_for_status()
            return response.content
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


def profile_urls():
    soup = BeautifulSoup(fetch(LIST_URL), "html.parser")
    urls = []
    seen = set()
    for link in soup.find_all("a", href=True):
        url = link.get("href", "")
        if "/espositore/" not in url:
            continue
        url = url.split("#", 1)[0]
        if url not in seen:
            seen.add(url)
            urls.append(url)
    if not urls:
        raise RuntimeError("No Esotika exhibitor profiles found")
    return urls


def parse_profile(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=60)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"Profile failed: {url}: {exc}")
        return None
    soup = BeautifulSoup(response.content, "html.parser")
    classes = " ".join(soup.body.get("class", [])) if soup.body else ""
    tags = " ".join(
        " ".join(node.get("class", []))
        for node in soup.find_all(class_=True)
    )
    page_text = clean(soup.get_text(" ", strip=True))
    if "fermo-2026" not in f"{classes} {tags} {page_text}".casefold():
        return None
    heading = soup.select_one("h1")
    name = clean(heading.get_text(" ", strip=True)) if heading else ""
    description = ""
    for label in ("Descrizione della attività:", "Descrizione dell'attività:"):
        marker = soup.find(string=lambda text: text and label.casefold() in text.casefold())
        if marker and marker.parent:
            description = clean(marker.parent.parent.get_text(" ", strip=True))
            description = re.sub(re.escape(label), "", description, flags=re.I).strip()
            break
    email = ""
    domain = ""
    for link in soup.select("a[href]"):
        href = link.get("href", "")
        if href.lower().startswith("mailto:"):
            email = href.split(":", 1)[1].split("?", 1)[0].lower()
        candidate = root_domain(href)
        if candidate:
            domain = candidate
    return {
        "company_name": name,
        "domain": domain,
        "description": description,
        "booth": "",
        "email": email,
        "city": "Fermo",
        "full_address": "",
        "mobile_primary": "",
        "profile_url": url,
    }


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
            json={
                "q": f'"{record["company_name"]}" official website 2026 Esotika Pet Show Fermo',
                "gl": "it", "hl": "en", "num": 10,
            },
            timeout=45,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph") or {}
        record["domain"] = root_domain(graph.get("website", ""))
        if not record["domain"]:
            for result in data.get("organic", []):
                candidate = root_domain(result.get("link", ""))
                if candidate:
                    record["domain"] = candidate
                    break
    except requests.RequestException as exc:
        print(f"Serper failed: {record['company_name']}: {exc}")
    return record


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    urls = profile_urls()
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = [record for record in pool.map(parse_profile, urls) if record]
    print(f"Found {len(records)} Fermo 2026 exhibitors from {len(urls)} profiles")
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
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
