from __future__ import annotations

import csv
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://www.icfexpo.com"
LIST_URL = BASE + "/en/exhibitor-list"
OUT = Path(__file__).parent
FIELDS = [
    "company_name", "booth", "description", "email", "mobile_primary",
    "domain", "full_address", "city", "linkedin_url",
]
BAD_DOMAINS = {
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com",
    "x.com", "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com",
}


def clean_domain(value: str) -> str:
    value = html.unescape((value or "").strip()).rstrip(".,;)")
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    host = (urlparse(value).hostname or "").lower().removeprefix("www.")
    if not host or any(host == bad or host.endswith("." + bad) for bad in BAD_DOMAINS):
        return ""
    return "https://" + host


def text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)) if node else ""


def decode_cfemail(encoded: str) -> str:
    try:
        raw = bytes.fromhex(encoded)
        key = raw[0]
        return bytes(value ^ key for value in raw[1:]).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return ""


def list_profiles(session: requests.Session) -> list[dict]:
    profiles = {}
    for page in range(1, 100):
        url = LIST_URL if page == 1 else f"{LIST_URL}?page={page}"
        response = session.get(url, timeout=60)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        cards = soup.select(".brand-item")
        if not cards:
            break
        for card in cards:
            link = card.select_one("a.brand-link[href]")
            name = card.select_one(".brand-name")
            if link and name:
                profile_url = urljoin(BASE, "/en/" + link["href"].lstrip("/"))
                profiles[profile_url] = {
                    "company_name": text(name),
                    "profile_url": profile_url,
                }
        if not soup.select_one(f'a.page-link[href*="page={page + 1}"]'):
            # The final page may show a jump link but no direct next page.
            next_link = soup.select_one('a[rel="next"]')
            if not next_link:
                break
        time.sleep(0.05)
    return list(profiles.values())


def profile_details(session: requests.Session, row: dict) -> dict:
    response = session.get(row["profile_url"], timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    result = {field: "" for field in FIELDS}
    result["company_name"] = text(soup.select_one(".company-title")) or row["company_name"]
    location = text(soup.select_one(".company-title + span"))
    hall = ""
    booth = ""
    for item in soup.select(".schedule-sidebar .schedule-list li, .widget.d-lg-none li"):
        value = text(item)
        if "Hall" in value:
            hall = value.split(":", 1)[-1].strip()
        elif "Booth" in value:
            booth = value.split(":", 1)[-1].strip()
    result["booth"] = "; ".join(x for x in [f"Hall {hall}" if hall else "",
                                            f"Booth {booth}" if booth else ""] if x)
    result["country"] = location
    result["description"] = text(soup.select_one("meta[name='description']"))
    result["description"] = "" if result["description"].startswith("Review the ICF") else result["description"]
    result["full_address"] = location
    # Decode Cloudflare-protected contact emails when the profile exposes them.
    emails = []
    for node in soup.select(".schedule-sidebar [data-cfemail], .schedule-detail-info [data-cfemail]"):
        decoded = decode_cfemail(node.get("data-cfemail", ""))
        if decoded and "@" in decoded:
            emails.append(decoded)
    for link in soup.select("a[href]"):
        href = link.get("href", "")
        if href.lower().startswith("mailto:"):
            emails.append(href[7:].split("?", 1)[0])
        elif href.lower().startswith(("http://", "https://")):
            candidate = clean_domain(href)
            if candidate and "icfexpo.com" not in candidate and "cdn.mytuyap.com" not in candidate:
                result["domain"] = candidate
    result["email"] = next((x for x in emails if "@" in x), "")
    # No city/phone/LinkedIn is exposed when the profile does not contain it.
    return {field: result.get(field, "") for field in FIELDS}


def main():
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; exhibitor research)"
    profiles = list_profiles(session)
    records = []
    with ThreadPoolExecutor(max_workers=16) as executor:
        jobs = {executor.submit(profile_details, session, profile): profile for profile in profiles}
        for index, job in enumerate(as_completed(jobs), 1):
            profile = jobs[job]
            try:
                records.append(job.result())
            except requests.RequestException as exc:
                print(f"Profile failed: {profile['profile_url']} ({exc})")
                fallback = {field: "" for field in FIELDS}
                fallback["company_name"] = profile["company_name"]
                records.append(fallback)
            if index % 25 == 0:
                print(f"Visited {index}/{len(profiles)} profiles")
    records.sort(key=lambda row: row["company_name"].casefold())
    assert all(list(row) == FIELDS for row in records)
    with (OUT / "ICF_EXPO_2027_exhibitors.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)
    (OUT / "ICF_EXPO_2027_exhibitors.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Exported {len(records)} exhibitors; "
          f"{sum(bool(row['email']) for row in records)} emails; "
          f"{sum(bool(row['domain']) for row in records)} domains")


if __name__ == "__main__":
    main()
