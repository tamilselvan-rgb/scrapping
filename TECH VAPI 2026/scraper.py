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

LIST_URL = "https://visitor.industrialexpoindia.com/"
PROFILE_URL = "https://visitor.industrialexpoindia.com/exhibitor-detail.php?eid={}"
OUT = Path(__file__).parent
FIELDS = [
    "company_name", "booth", "description", "email", "mobile_primary",
    "domain", "full_address", "city", "linkedin_url",
]
BAD_DOMAINS = {
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "yellowpages.com", "yelp.com",
}


def clean_domain(value: str) -> str:
    value = (value or "").strip().rstrip(".,;)")
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    host = (urlparse(value).hostname or "").lower().removeprefix("www.")
    if not host or any(host == bad or host.endswith("." + bad) for bad in BAD_DOMAINS):
        return ""
    return "https://" + host


def parse_js_json(html: str) -> dict:
    match = re.search(r"exhibitorData\s*=\s*JSON\.parse\('(.*?)'\);", html, re.S)
    if not match:
        raise ValueError("exhibitorData was not found in the profile")
    return json.loads(match.group(1).replace(r"\"", '"').replace(r"\/", "/"))


def get_exhibitors(session: requests.Session) -> list[dict]:
    response = session.get(LIST_URL, timeout=60)
    response.raise_for_status()
    match = re.search(r"let allExhibitors\s*=\s*(\[.*?\]);", response.text, re.S)
    if not match:
        raise ValueError("allExhibitors was not found on the official directory")
    return json.loads(match.group(1))


def serper_domain(company: str, key: str) -> str:
    result = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        json={"q": f'"{company}" official website Tech Vapi 2026 India'},
        timeout=30,
    ).json()
    if result.get("message") == "Not enough credits":
        raise RuntimeError("Serper API has no credits")
    kg = result.get("knowledgeGraph") or {}
    candidates = [kg.get("website", "")]
    candidates += [x.get("link", "") for x in result.get("organic", [])[:5]]
    tokens = [x for x in re.findall(r"[a-z0-9]+", company.lower()) if len(x) > 2]
    for candidate in candidates:
        domain = clean_domain(candidate)
        if domain and any(token in domain for token in tokens):
            return domain
    return ""


def main():
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; exhibitor research)"
    source_records = get_exhibitors(session)
    output = []
    serper_key = os.getenv("SERPER_API_KEY", "")
    env = Path(__file__).resolve().parents[1] / ".env"
    if not serper_key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("SERPER_API_KEY="):
                serper_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    serper_available = bool(serper_key)
    for index, item in enumerate(source_records, 1):
        data = dict(item)
        try:
            response = session.get(PROFILE_URL.format(item["eid"]), timeout=45)
            response.raise_for_status()
            data.update(parse_js_json(response.text))
        except (requests.RequestException, ValueError) as exc:
            print(f"Profile {item.get('eid')} failed: {exc}")
        domain = clean_domain(data.get("website", ""))
        if not domain and serper_available:
            try:
                domain = serper_domain(data.get("CompanyName", ""), serper_key)
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                print(f"Domain fallback stopped: {exc}")
                serper_available = False
        booth = "; ".join(x for x in [
            f"Hall {data.get('Dome', '').strip()}" if data.get("Dome") else "",
            f"Stall {data.get('StallNo', '').strip()}" if data.get("StallNo") else "",
        ] if x)
        emails = [data.get("ContactPersonEmail1", ""), data.get("ContactPersonEmail2", "")]
        output.append({
            "company_name": (data.get("CompanyName") or item.get("CompanyName", "")).strip(),
            "booth": booth,
            "description": (data.get("Products") or "").strip(),
            "email": next((x.strip() for x in emails if x and "@" in x), ""),
            "mobile_primary": "",
            "domain": domain,
            "full_address": "",
            "city": (data.get("Location") or "").strip(),
            "linkedin_url": data.get("Linkedin", "") or "",
        })
        if index % 25 == 0:
            print(f"Visited {index}/{len(source_records)} profiles")
        time.sleep(0.03)
    assert output and all(list(row) == FIELDS for row in output)
    with (OUT / "TECH_VAPI_2026_exhibitors.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(output)
    (OUT / "TECH_VAPI_2026_exhibitors.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Exported {len(output)} exhibitors; {sum(bool(x['domain']) for x in output)} domains; "
          f"{sum(bool(x['email']) for x in output)} emails")


if __name__ == "__main__":
    main()
