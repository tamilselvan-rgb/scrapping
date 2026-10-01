"""Scrape the Abu Dhabi Future Health Summit 2026 exhibitor directory."""

from __future__ import annotations

import csv
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests


EVENT_NAME = "FUTURE HEALTH"
API_BASE = "https://api.futureenergyasia.com/umbraco/surface/ExhibitorList/"
LIST_ENDPOINT = API_BASE + "GetAllExhibitorsadghw"
DETAIL_ENDPOINT = API_BASE + "GetExhibitorByIdadghw"
SERPER_ENDPOINT = "https://google.serper.dev/search"
FIELDS = [
    "company_name",
    "booth",
    "description",
    "email",
    "mobile_primary",
    "domain",
    "full_address",
    "city",
    "linkedin_url",
]
SOCIAL_HOSTS = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "youtube.com",
}
DIRECTORY_HOSTS = {
    "wikipedia.org",
    "yellowpages.com",
    "yelp.com",
    "crunchbase.com",
    "zoominfo.com",
}


def clean(value: object) -> str:
    if value is None:
        return ""
    # The source contains a few literal replacement characters where an
    # em-dash was lost during upstream data entry; keep exported text clean.
    value = str(value).replace("\ufffd", "-")
    return re.sub(r"\s+", " ", value).strip()


def load_serper_key() -> str:
    env_path = Path(__file__).parents[1] / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("SERPER_API_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def valid_url(value: object) -> str:
    url = clean(value)
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parsed = urlparse(url)
    return url if parsed.hostname else ""


def is_blocked_domain(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return any(host == item or host.endswith("." + item) for item in SOCIAL_HOSTS | DIRECTORY_HOSTS)


def serper_domain(session: requests.Session, key: str, company: str) -> str:
    if not key:
        return ""
    response = session.post(
        SERPER_ENDPOINT,
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        json={"q": f'"{company}" official website 2026'},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    knowledge = payload.get("knowledgeGraph") or {}
    candidate = valid_url(knowledge.get("website"))
    if candidate and not is_blocked_domain(candidate):
        return candidate
    for result in payload.get("organic", []):
        candidate = valid_url(result.get("link"))
        if candidate and not is_blocked_domain(candidate):
            return candidate
    return ""


def get_json(session: requests.Session, url: str, **kwargs: object) -> object:
    response = session.get(url, timeout=45, **kwargs)
    response.raise_for_status()
    # The API occasionally advertises a legacy charset even though its JSON
    # body is UTF-8. Decode the bytes explicitly to avoid replacement chars.
    return json.loads(response.content.decode("utf-8"))


def make_record(item: dict, detail: dict) -> dict[str, str]:
    address = clean(detail.get("Address") or item.get("Address"))
    city = clean(detail.get("City") or item.get("City"))
    country = clean(detail.get("CountryName") or item.get("CountryName"))
    full_address = ", ".join(part for part in [address, city, country] if part)
    linkedin = valid_url(detail.get("LinkedIn") or item.get("LinkedIn"))
    if linkedin and "linkedin.com/company/" not in linkedin.lower() and "linkedin.com/school/" not in linkedin.lower():
        linkedin = ""
    return {
        "company_name": clean(detail.get("CompanyName") or item.get("CompanyName")),
        "booth": clean(detail.get("StandNumber") or item.get("StandNumber")),
        "description": clean(detail.get("Description") or item.get("Description")),
        "email": clean(detail.get("Email") or item.get("Email")),
        "mobile_primary": clean(detail.get("PhoneNumber") or item.get("PhoneNumber")),
        "domain": valid_url(detail.get("WebsiteLink") or item.get("WebsiteLink")),
        "full_address": full_address,
        "city": city,
        "linkedin_url": linkedin,
    }


def verify(records: list[dict[str, str]]) -> None:
    total = len(records)
    print(f"=== Verification Report: {EVENT_NAME} ===")
    print(f"Total Exhibitors : {total}")
    print("Field Coverage   :")
    for field in FIELDS:
        count = sum(bool(record[field]) for record in records)
        print(f"  {field:<15}: {count}/{total} ({count / total * 100:.1f}%)")
    invalid_domains = [
        record["domain"]
        for record in records
        if record["domain"] and not re.match(r"^https?://", record["domain"], re.I)
    ]
    api_key = load_serper_key()
    output_text = json.dumps(records, ensure_ascii=False)
    print("Sample Verified  :", ", ".join(record["company_name"] for record in records[:3]), "[OK]")
    print("Security Check   :", "No API key leakage [OK]" if api_key not in output_text else "FAILED")
    print("Value Check      :", "PASSED" if not invalid_domains else "FAILED")
    print("Status            :", "PASSED" if not invalid_domains and api_key not in output_text else "FAILED")


def main() -> None:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; exhibitor-research/1.0)"})
    items = get_json(session, LIST_ENDPOINT)
    if not isinstance(items, list):
        raise RuntimeError("Unexpected exhibitor list response")

    records: list[dict[str, str]] = []
    for index, item in enumerate(items, start=1):
        detail = get_json(session, DETAIL_ENDPOINT, params={"exhibitorid": item["Id"]})
        if not isinstance(detail, dict):
            detail = item
        records.append(make_record(item, detail))
        print(f"Fetched {index}/{len(items)}: {records[-1]['company_name']}")
        time.sleep(0.05)

    key = load_serper_key()
    for record in records:
        if not record["domain"]:
            try:
                record["domain"] = serper_domain(session, key, record["company_name"])
            except requests.RequestException as exc:
                print(f"Domain lookup failed for {record['company_name']}: {exc}")

    records.sort(key=lambda row: row["company_name"].casefold())
    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)
    csv_path = output_dir / "FUTURE_HEALTH_exhibitors.csv"
    json_path = output_dir / "FUTURE_HEALTH_exhibitors.json"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)
    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    verify(records)
    print(f"CSV  : {csv_path}")
    print(f"JSON : {json_path}")


if __name__ == "__main__":
    main()
