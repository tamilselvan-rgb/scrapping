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


EVENT = "HOME_BUILDING_EXPO_ARCHITECTURE_URBAN_PLANNING_EXPO_2026"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
LIST_URL = "https://www.omanhome-building.com/exhibitor-list/"
FIELDS = [
    "company_name", "booth", "description", "email", "mobile_primary",
    "domain", "full_address", "city", "linkedin_url",
]
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ExhibitorResearch/1.0)"}
BLOCKED = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com", "google.com",
    "omanhome-building.com",
}


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def domain_url(value):
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


def listing():
    soup = BeautifulSoup(fetch(LIST_URL), "html.parser")
    records = []
    seen = set()
    for image in soup.select("img[alt]"):
        alt = clean(image.get("alt"))
        source = image.get("data-src") or image.get("src") or ""
        if not alt or "wp-content/uploads" not in source:
            continue
        key = alt.casefold()
        if key in seen or key.startswith("ohb 2026"):
            continue
        seen.add(key)
        records.append({
            "company_name": alt,
            "booth": "",
            "description": "",
            "email": "",
            "mobile_primary": "",
            "domain": "",
            "full_address": "",
            "city": "",
            "linkedin_url": "",
        })
    if not records:
        raise RuntimeError("No 2026 exhibitor logo labels found")
    return records


def serper_key():
    env = ROOT.parent / ".env"
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip().strip("\"'")
    return ""


def name_tokens(name):
    return {
        token for token in re.findall(r"[a-z0-9]+", name.casefold())
        if len(token) >= 4 and token not in {"group", "company", "oman", "mamlkah"}
    }


def plausible_domain(name, domain):
    if not domain:
        return ""
    tokens = name_tokens(name)
    compact = re.sub(r"[^a-z0-9]", "", domain.casefold().split(".")[0])
    if not tokens or any(token in compact or compact in token for token in tokens):
        return domain
    return ""


def serper_enrich(record):
    key = serper_key()
    if not key:
        return record
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={
                "q": f'"{record["company_name"]}" official website Oman Home Building Expo 2026',
                "gl": "om", "hl": "en", "num": 10,
            },
            timeout=45,
        )
        response.raise_for_status()
        data = response.json()
        graph = data.get("knowledgeGraph") or {}
        candidates = [graph.get("website", "")]
        candidates.extend(result.get("link", "") for result in data.get("organic", []))
        for candidate in candidates:
            domain = plausible_domain(record["company_name"], domain_url(candidate))
            if domain:
                record["domain"] = domain
                break
        for result in data.get("organic", []):
            link = result.get("link", "")
            if "linkedin.com/company/" in link:
                record["linkedin_url"] = link.split("?", 1)[0]
                break
    except requests.RequestException as exc:
        print(f"Serper failed for {record['company_name']}: {exc}")
    return record


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    records = listing()
    print(f"Found {len(records)} unique 2026 logo exhibitors")
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(serper_enrich, records))
    records.sort(key=lambda item: item["company_name"].casefold())
    normalized = [{field: record.get(field, "") for field in FIELDS} for record in records]
    base = OUTPUT / f"{EVENT}_exhibitors"
    with base.with_suffix(".csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(normalized)
    base.with_suffix(".json").write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Domains found: {sum(bool(row['domain']) for row in normalized)}/{len(normalized)}")
    print(base.with_suffix(".csv"))
    print(base.with_suffix(".json"))


if __name__ == "__main__":
    main()
