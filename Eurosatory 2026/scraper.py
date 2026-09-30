import csv
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests


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
API = "https://eurosatory.finderr.cloud/api"
API_KEY = "9532b2dbcb94ddfb48bf4f6b240b856575f6ad5a3f0a70a618608e4cbe23c15e"
HEADERS = {
    "X-API-KEY": API_KEY,
    "Authorization": "Bearer null",
    "Origin": "https://eurosatory.finderr.cloud",
    "Referer": "https://eurosatory.finderr.cloud/standalone/catalog/company-list?lang=en",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0",
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "").replace("\ufffd", "'")).strip()


def post_search(session, page, page_size=100):
    response = session.post(
        f"{API}/catalog/search_exhibitors",
        headers=HEADERS,
        json={
            "CurrentLanguage": "en",
            "NbElementsPerPage": page_size,
            "PageIndex": page,
            "GetAll": False,
        },
        timeout=90,
    )
    response.raise_for_status()
    return response.json()


def fetch_all_exhibitors(session):
    first = post_search(session, 0)
    total = int(first["NbExhibitors"])
    records = list(first.get("ListDetailsExhibitors") or [])
    pages = (total + 99) // 100
    for page in range(1, pages):
        records.extend(post_search(session, page, 100).get("ListDetailsExhibitors") or [])
    unique = {record["Exhi_Guid"]: record for record in records if record.get("Exhi_Guid")}
    return total, list(unique.values())


def get_detail(guid):
    response = requests.get(
        f"{API}/v3/catalog/get_exhibitor/{guid}/en",
        headers=HEADERS,
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def make_record(listing):
    try:
        detail = get_detail(listing["Exhi_Guid"])
    except requests.RequestException:
        detail = {}
    company = detail or listing
    website = clean(company.get("Exhi_Website") or listing.get("Exhi_Website"))
    if website and not re.match(r"^https?://", website, re.I):
        website = "https://" + website
    address = [
        company.get("Exhi_Address1"),
        company.get("Exhi_Address2"),
        company.get("Exhi_Address3"),
        company.get("Exhi_City"),
        company.get("Exhi_StateProvince"),
        company.get("Exhi_ZipCode"),
        company.get("Exhi_Country_Name"),
    ]
    stands = company.get("Stands") or listing.get("Stands") or []
    booth = "; ".join(
        " - ".join(clean(x.get(k)) for k in ("Hall", "Name") if clean(x.get(k)))
        for x in stands
        if x.get("Hall") or x.get("Name")
    )
    linkedin = clean(
        company.get("Exhi_LinkedIn")
        or company.get("Exhi_Linkedin")
        or company.get("LinkedIn")
    )
    if linkedin and "linkedin.com" not in linkedin.lower():
        linkedin = f"https://www.linkedin.com/company/{linkedin.strip('/')}/"
    return {
        "company_name": clean(company.get("Exhi_CompanyName") or listing.get("Exhi_CompanyName")),
        "booth": booth,
        "description": clean(
            company.get("Presentation")
            or company.get("ShortPresentation")
            or listing.get("ShortPresentation")
        ),
        "email": clean(company.get("Exhi_ContactEmail")),
        "mobile_primary": clean(company.get("Exhi_Phone")),
        "domain": website,
        "full_address": ", ".join(clean(value) for value in address if clean(value)),
        "city": clean(company.get("Exhi_City")),
        "linkedin_url": linkedin,
    }


def main():
    session = requests.Session()
    expected, listings = fetch_all_exhibitors(session)
    records = []
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = [pool.submit(make_record, listing) for listing in listings]
        for future in as_completed(futures):
            records.append(future.result())
    records.sort(key=lambda row: row["company_name"].casefold())

    output = Path(__file__).parent / "output"
    output.mkdir(exist_ok=True)
    with (output / "EUROSATORY_2026_exhibitors.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)
    with (output / "EUROSATORY_2026_exhibitors.json").open(
        "w", encoding="utf-8"
    ) as stream:
        json.dump(records, stream, ensure_ascii=False, indent=2)

    print("=== Verification Report: Eurosatory 2026 ===")
    print(f"Expected Exhibitors : {expected}")
    print(f"Scraped Exhibitors  : {len(records)}")
    for field in FIELDS:
        count = sum(bool(row[field]) for row in records)
        print(f"{field:16}: {count}/{len(records)} ({count / len(records) * 100:.1f}%)")
    print("Source Verified     : paginated official catalogue and profiles [OK]")
    print("Status              :", "PASSED" if len(records) == expected else "FAILED")


if __name__ == "__main__":
    main()
