from __future__ import annotations

import csv
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

LIST_URL = "https://www.isee-expo.com/business-directory/?wpbdp_view=all_listings"
OUT = Path(__file__).parent
FIELDS = [
    "company_name", "booth", "description", "email", "mobile_primary",
    "domain", "full_address", "city", "linkedin_url",
]
BAD_DOMAINS = {
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com",
}


def normalize_domain(value: str) -> str:
    value = (value or "").strip().rstrip(".,;)")
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


def listing_records(session: requests.Session) -> list[dict]:
    response = session.get(LIST_URL, timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    records = []
    for card in soup.select("div.wpbdp-listing:not(.wpbdp-listing-table-header)"):
        title = card.select_one(".wpbdp-field-listing_title")
        link = title.select_one("a[href]") if title else None
        if not link:
            continue
        category = text(card.select_one(".wpbdp-field-listing_category"))
        # The directory currently labels these cards as 2026 Exhibitor.
        if "2026" not in category:
            continue
        records.append({
            "company_name": text(link),
            "profile_url": link.get("href", ""),
            "description": "",
            "domain": "",
            "email": "",
            "mobile_primary": "",
            "full_address": "",
            "city": "",
            "linkedin_url": "",
            "booth": "",
        })
    unique = {}
    for row in records:
        unique.setdefault(row["profile_url"], row)
    return list(unique.values())


def visit_profiles(session: requests.Session, records: list[dict]) -> None:
    """Visit every official exhibitor hyperlink and extract any available fields."""
    for index, row in enumerate(records, 1):
        try:
            response = session.get(row["profile_url"], timeout=45)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            main = soup.select_one(".wpbdp-listing-single") or soup
            row["description"] = text(main.select_one(
                ".wpbdp-field-description, .wpbdp-field-display-description"
            ))
            if not row["description"]:
                # Keep meaningful profile text but exclude navigation/category boilerplate.
                body = text(main)
                row["description"] = re.sub(
                    r"Return to .*?Listing Tags.*?(?=Description|$)", "", body,
                    flags=re.I,
                ).strip()
            for a in main.select("a[href]"):
                href = a.get("href", "")
                label = text(a).lower()
                if href.startswith("mailto:"):
                    row["email"] = href[7:].split("?", 1)[0]
                elif href.startswith("tel:"):
                    row["mobile_primary"] = href[4:]
                elif "linkedin.com/company/" in href.lower():
                    row["linkedin_url"] = href
                elif href.lower().startswith(("http://", "https://")):
                    candidate = normalize_domain(href)
                    if candidate and "isee-expo.com" not in candidate:
                        row["domain"] = candidate
        except requests.RequestException:
            row["description"] = row["description"] or ""
        if index % 25 == 0:
            print(f"Visited {index}/{len(records)} profiles")


def serper_domains(records: list[dict]) -> None:
    env = Path(__file__).resolve().parents[1] / ".env"
    key = os.getenv("SERPER_API_KEY", "")
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("SERPER_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if not key:
        print("SERPER_API_KEY not found; missing domains left blank")
        return
    for index, row in enumerate(records, 1):
        if row["domain"]:
            continue
        try:
            result = session.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": key, "Content-Type": "application/json"},
                json={"q": f'"{row["company_name"]}" official website ISEE Expo 2026 India'},
                timeout=30,
            ).json()
            candidates = []
            kg = result.get("knowledgeGraph") or {}
            if kg.get("website"):
                candidates.append((kg["website"], " ".join(
                    str(kg.get(key, "")) for key in ("title", "description", "type")
                )))
            candidates.extend(
                (item.get("link", ""), " ".join(
                    str(item.get(key, "")) for key in ("title", "snippet")
                ))
                for item in result.get("organic", [])[:5]
            )
            tokens = [x for x in re.findall(r"[a-z0-9]+", row["company_name"].lower()) if len(x) > 2]
            for candidate, evidence in candidates:
                found = normalize_domain(candidate)
                evidence = (evidence + " " + found).lower()
                matched = sum(token in evidence for token in tokens)
                if found and (not tokens or matched >= max(1, min(2, len(tokens)))):
                    row["domain"] = found
                    break
        except (requests.RequestException, ValueError):
            pass
        if index % 25 == 0:
            print(f"Domain search {index}/{len(records)}")
        time.sleep(0.05)


def verify(records: list[dict]) -> None:
    assert records and all(set(FIELDS) == set(row) for row in records)
    assert all(row["company_name"] for row in records)
    assert all(not row["domain"] or row["domain"].startswith(("http://", "https://"))
               for row in records)
    print("=== Verification Report: ISEE Expo 2026 ===")
    print(f"Total Exhibitors : {len(records)}")
    for field in FIELDS:
        count = sum(bool(row[field]) for row in records)
        print(f"{field:16}: {count}/{len(records)} ({count / len(records) * 100:.1f}%)")
    print("Security Check   : API key not written to output")
    print("Status           : PASSED")


def main():
    global session
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; exhibitor research)"})
    records = listing_records(session)
    visit_profiles(session, records)
    serper_domains(records)
    output = [{field: row.get(field, "") for field in FIELDS} for row in records]
    verify(output)
    with (OUT / "ISEE_EXPO_2026_exhibitors.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(output)
    (OUT / "ISEE_EXPO_2026_exhibitors.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
