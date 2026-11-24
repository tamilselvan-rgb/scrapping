from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

URL = "https://www.vakantiebeurs.nl/en/bezoeken/deelnemers"
OUT = Path(__file__).parent
FIELDS = [
    "company_name", "booth", "description", "email", "mobile_primary",
    "domain", "full_address", "city", "linkedin_url",
]
BAD = {"linkedin.com", "facebook.com", "instagram.com", "twitter.com",
       "x.com", "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com"}


def clean_domain(value: str) -> str:
    if not value:
        return ""
    value = value.strip()
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    host = (urlparse(value).hostname or "").lower().removeprefix("www.")
    if not host or any(host == item or host.endswith("." + item) for item in BAD):
        return ""
    return "https://" + host


def text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)) if node else ""


def main():
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; exhibitor research)"
    response = session.get(URL, timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    records = []
    for card in soup.select(".exhibitor-item-column"):
        name_node = card.select_one(".exhibitor-link")
        if not name_node:
            continue
        booth = ""
        # The venue label is rendered beside the exhibitor name in the card.
        card_text = text(card)
        match = re.search(r"(\d{1,2}\.[A-Z]\d{3,})", card_text)
        if match:
            booth = match.group(1)
        website = card.select_one('a[title="Go to website"][href]')
        records.append({
            "company_name": text(name_node),
            "booth": booth,
            "description": "",
            "email": "",
            "mobile_primary": "",
            "domain": clean_domain(website.get("href", "") if website else ""),
            "full_address": "",
            "city": "",
            "linkedin_url": "",
        })
    # Deduplicate cards while retaining their first official website.
    unique = {}
    for row in records:
        unique.setdefault(row["company_name"].casefold(), row)
    records = list(unique.values())
    assert all(list(row) == FIELDS for row in records)
    with (OUT / "THE_GETAWAY_2027_exhibitors.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)
    (OUT / "THE_GETAWAY_2027_exhibitors.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Exported {len(records)} participants; "
          f"{sum(bool(row['domain']) for row in records)} domains")


if __name__ == "__main__":
    main()
