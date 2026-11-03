"""Scrape/export the official India ITME 2026 exhibitor list.

The public exhibitor page is a React application.  Its official 2026 bundle
contains the same records rendered by the page, so this script downloads that
bundle and extracts the embedded list without inventing profile data.
"""
from __future__ import annotations

import csv
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

BASE = "https://corporate.india-itme.com/itme2026/"
MAIN = BASE + "static/js/main.ad04e6d3.js"
CHUNK = BASE + "static/js/4608.1348da8e.chunk.js"
OUT = Path(__file__).parent
CSV_PATH = OUT / "INDIA_ITME_2026_exhibitors.csv"
JSON_PATH = OUT / "INDIA_ITME_2026_exhibitors.json"
FIELDS = [
    "company_name", "booth", "description", "email", "mobile_primary",
    "domain", "full_address", "city", "linkedin_url",
]
COUNTRIES = {
    "INDIA": "India", "CHINA": "China", "TAIWAN": "Taiwan",
    "SWITZERLAND": "Switzerland", "ITALY": "Italy", "JAPAN": "Japan",
    "BELGIUM": "Belgium", "TURKIYE": "Türkiye", "EGYPT, ARAB REP.": "Egypt",
    "GERMANY": "Germany", "FRANCE": "France", "SPAIN": "Spain",
    "UNITED KINGDOM": "United Kingdom", "USA": "United States",
}
BAD_HOSTS = {"linkedin.com", "facebook.com", "instagram.com", "twitter.com",
             "x.com", "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com"}


def extract_records() -> list[dict]:
    r = requests.get(CHUNK, timeout=45)
    r.raise_for_status()
    match = re.search(r"JSON\.parse\('(\[.*?\])'\)", r.text)
    if not match:
        raise RuntimeError("Official exhibitor JSON was not found in the bundle")
    return json.loads(match.group(1))


def clean_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    host = (urlparse(value).hostname or "").lower().removeprefix("www.")
    if not host or any(host == bad or host.endswith("." + bad) for bad in BAD_HOSTS):
        return ""
    return "https://" + host


def serper_domains(records: list[dict]) -> dict[str, str]:
    """Use Serper only for missing domains; uncertain matches remain blank."""
    env = Path(__file__).resolve().parents[1] / ".env"
    key = os.getenv("SERPER_API_KEY", "")
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("SERPER_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if not key:
        return {}
    found: dict[str, str] = {}
    for rec in records:
        name = rec["org"]
        try:
            data = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": key, "Content-Type": "application/json"},
                json={"q": f'"{name}" official website {rec["country"]}'},
                timeout=30,
            ).json()
            candidates = []
            kg = data.get("knowledgeGraph") or {}
            if kg.get("website"):
                candidates.append(kg["website"])
            candidates += [x.get("link", "") for x in data.get("organic", [])[:5]]
            for candidate in candidates:
                domain = clean_url(candidate)
                if domain:
                    title = " ".join(str(x) for x in data.get("organic", []) if x.get("link") == candidate)
                    # Require the company name to be represented in the result.
                    tokens = [x for x in re.findall(r"[a-z0-9]+", name.lower()) if len(x) > 2]
                    if not tokens or sum(t in title.lower() for t in tokens) >= max(1, len(tokens) // 2):
                        found[name] = domain
                        break
        except requests.RequestException:
            pass
        time.sleep(0.05)
    return found


def main() -> None:
    records = extract_records()
    domains = serper_domains(records)
    output = []
    for rec in records:
        country = COUNTRIES.get(rec.get("country", ""), rec.get("country", "").title())
        output.append({
            "company_name": rec.get("org", "").strip(),
            "booth": "",
            "description": f"India ITME 2026 exhibitor; chapter: {rec.get('chapter', '')}",
            "email": "",
            "mobile_primary": "",
            "domain": domains.get(rec.get("org", ""), ""),
            "full_address": "",
            "city": "",
            "linkedin_url": "",
            "country": country,
            "chapter": rec.get("chapter", ""),
            "event_year": 2026,
            "source_url": "https://corporate.india-itme.com/itme2026/#/exhibitorList2026",
        })
    # Keep mandatory fields first while retaining source category/year.
    fields = FIELDS + ["country", "chapter", "event_year", "source_url"]
    with JSON_PATH.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output)
    print(f"Exported {len(output)} exhibitors; {sum(bool(x['domain']) for x in output)} domains")


if __name__ == "__main__":
    main()
