from __future__ import annotations

import csv
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

LIST_URL = "https://www.saltlakehomeshow.com/exhibitor-list/exhibitors/all-exhibitors"
BASE = "https://www.saltlakehomeshow.com"
OUT = Path(__file__).parent
FIELDS = [
    "company_name", "booth", "description", "email", "mobile_primary",
    "domain", "full_address", "city", "linkedin_url",
]
BAD = {"linkedin.com", "facebook.com", "instagram.com", "twitter.com",
       "x.com", "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com"}


def domain(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    host = (urlparse(value).hostname or "").lower().removeprefix("www.")
    if not host or any(host == bad or host.endswith("." + bad) for bad in BAD):
        return ""
    return "https://" + host


def text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)) if node else ""


def get_profiles(session: requests.Session) -> list[dict]:
    response = session.get(LIST_URL, timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    profiles = {}
    for link in soup.select("h2 a[href]"):
        if "/exhibitor-list/exhibitors/detail/" not in link.get("href", ""):
            continue
        url = urljoin(BASE, link["href"])
        profiles[url] = {"profile_url": url, "company_name": text(link)}
    return list(profiles.values())


def scrape_profile(session: requests.Session, profile: dict) -> dict:
    response = session.get(profile["profile_url"], timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    name = text(soup.select_one(".primary-content h1")) or profile["company_name"]
    website = soup.select_one(".container.info a[href^='http']")
    match = re.search(r"Booth\s*#:\s*([A-Za-z0-9\-]+)", response.text, re.I)
    description = ""
    # Keep exhibitor-authored product/service text when present.
    sections = []
    for heading in soup.select(".primary-content h2"):
        parent = heading.parent
        value = text(parent)
        if value and "more info" not in value.lower():
            sections.append(value)
    if sections:
        description = " ".join(dict.fromkeys(sections))
    return {
        "company_name": name,
        "booth": f"Booth {match.group(1)}" if match else "",
        "description": description,
        "email": "",
        "mobile_primary": "",
        "domain": domain(website.get("href", "") if website else ""),
        "full_address": "",
        "city": "Salt Lake City",
        "linkedin_url": "",
    }


def main():
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; exhibitor research)"
    profiles = get_profiles(session)
    records = []
    with ThreadPoolExecutor(max_workers=16) as executor:
        jobs = {executor.submit(scrape_profile, session, p): p for p in profiles}
        for index, job in enumerate(as_completed(jobs), 1):
            profile = jobs[job]
            try:
                records.append(job.result())
            except requests.RequestException as exc:
                print(f"Profile failed: {profile['profile_url']} ({exc})")
                records.append({field: profile["company_name"] if field == "company_name" else ""
                                for field in FIELDS})
            if index % 25 == 0:
                print(f"Visited {index}/{len(profiles)} profiles")
    records.sort(key=lambda row: row["company_name"].casefold())
    assert all(list(row) == FIELDS for row in records)
    with (OUT / "SALT_LAKE_HOME_SHOW_2027_exhibitors.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)
    (OUT / "SALT_LAKE_HOME_SHOW_2027_exhibitors.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Exported {len(records)} exhibitors; "
          f"{sum(bool(row['domain']) for row in records)} domains; "
          f"{sum(bool(row['booth']) for row in records)} booths")


if __name__ == "__main__":
    main()
