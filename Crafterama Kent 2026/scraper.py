import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


EVENT = "CRAFTERAMA_KENT"
YEAR = "2026"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LIST_URL = "https://www.stamperama.com/kent-exhibitors"
EVENT_URL = "https://www.stamperama.com/kent-venue"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"}
BLOCKED = {
    "stamperama.com", "linkedin.com", "facebook.com", "instagram.com",
    "twitter.com", "x.com", "youtube.com", "wikipedia.org", "yellowpages.com",
    "yelp.com", "google.com", "10times.com", "kompass.com", "tracxn.com",
}
FIELDS = [
    "exhibitor_name", "domain", "contact_number", "mail", "location",
    "country", "booth_no", "desc", "linkedin_url", "city", "profile_url",
    "event_date", "event_venue", "source_url", "source_year",
]


def clean(value):
    value = html.unescape(str(value or "")).replace("\xa0", " ").replace("\u200b", "")
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
        "craft", "crafts", "design", "studio", "products", "limited",
        "ltd", "company", "the", "and", "cards", "education",
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
    return href


def serper_key():
    env = ROOT.parent / ".env"
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"\'')
    return ""


def listing():
    response = requests.get(LIST_URL, headers=HEADERS, timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    heading = next(
        (node for node in soup.find_all("h2")
         if clean(node.get_text(" ", strip=True)).upper() == "KENT LINEUP"),
        None,
    )
    if not heading:
        raise RuntimeError("Kent 2026 lineup heading not found")
    records = []
    seen = set()
    for node in heading.find_all_next("p"):
        if node.find_previous(["h2", "h3"]) is not heading:
            break
        text = clean(node.get_text(" ", strip=True))
        if not text or text.lower().startswith(("november 2026", "supported by")):
            continue
        if " - " not in text:
            continue
        name, desc = text.split(" - ", 1)
        name, desc = clean(name), clean(desc)
        if not name or name in seen:
            continue
        seen.add(name)
        records.append({
            "exhibitor_name": name,
            "domain": "",
            "contact_number": "",
            "mail": "",
            "location": "",
            "country": "United Kingdom",
            "booth_no": "",
            "desc": desc,
            "linkedin_url": "",
            "city": "",
            "profile_url": "",
            "event_date": "2026-11-14",
            "event_venue": "Kent Event Centre, Kent Showground, Detling, Kent ME14 3JF, United Kingdom",
            "source_url": LIST_URL,
            "source_year": YEAR,
        })
    if not records:
        raise RuntimeError("No Kent 2026 exhibitors found")
    return records


def serper_enrich(record):
    key = serper_key()
    if not key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": f'"{record["exhibitor_name"]}" official website 2026 craft'},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph", {})
        candidate = root_domain(graph.get("website", ""))
        if candidate and plausible_domain(record["exhibitor_name"], candidate):
            record["domain"] = candidate
        if not record["domain"]:
            for item in data.get("organic", []):
                candidate = root_domain(item.get("link", ""))
                if candidate and plausible_domain(record["exhibitor_name"], candidate):
                    record["domain"] = candidate
                    break
        for item in data.get("organic", []):
            candidate = linkedin_url(item.get("link", ""))
            if candidate:
                record["linkedin_url"] = candidate
                break
    except requests.RequestException:
        pass
    return record


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = listing()
    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(serper_enrich, records))
    records.sort(key=lambda item: item["exhibitor_name"].casefold())
    base = OUT / f"{EVENT}_2026_exhibitors"
    with base.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    base.with_suffix(".json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Exported {len(records)} 2026 Crafterama Kent exhibitors")
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
