"""
Scrape Fashion & Apparel brands from Cognito's Top 50 D2C list and merge
into the existing clothing_brands.csv (with deduplication).

Source:
    https://cognitoitconsultancy.com/top-d2c-brands-india-2026/
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

COGNITO_URL = "https://cognitoitconsultancy.com/top-d2c-brands-india-2026/"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
CSV_PATH = OUTPUT_DIR / "clothing_brands.csv"
JSON_PATH = OUTPUT_DIR / "clothing_brands.json"
CSV_FIELDS = ["company_name", "domain", "sector"]

# Parsed from Fashion & Apparel section (ranks 28–34)
FASHION_BRANDS: list[dict[str, str]] = [
    {
        "company_name": "The Souled Store",
        "sector": "Pop-culture; Licensed",
        "domain_candidates": ["thesouledstore.com"],
    },
    {
        "company_name": "Bewakoof",
        "sector": "Casualwear",
        "domain_candidates": ["bewakoof.com"],
    },
    {
        "company_name": "FableStreet",
        "sector": "Workwear; Women",
        "domain_candidates": ["fablestreet.com"],
    },
    {
        "company_name": "Bonkers Corner",
        "sector": "Streetwear",
        "domain_candidates": ["bonkerscorner.com"],
    },
    {
        "company_name": "Indya",
        "sector": "Ethnic wear; Indo-western",
        "domain_candidates": ["houseofindya.com", "indya.com"],
    },
    {
        "company_name": "Suta",
        "sector": "Handloom; Sarees",
        "domain_candidates": ["suta.in", "sutastore.com"],
    },
    {
        "company_name": "Snitch",
        "sector": "Men's fashion; Fast-fashion",
        "domain_candidates": ["snitch.co.in", "snitch.com"],
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


def log(message: str) -> None:
    print(message, flush=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def normalize_domain(domain: str) -> str:
    return domain.casefold().removeprefix("www.").strip()


def resolve_domain(candidates: list[str]) -> str:
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=15.0) as client:
        for candidate in candidates:
            for prefix in ("https://www.", "https://"):
                url = f"{prefix}{candidate}"
                try:
                    response = client.get(url)
                    if response.status_code < 400:
                        host = httpx.URL(str(response.url)).host or ""
                        return host.removeprefix("www.")
                except httpx.HTTPError:
                    continue
    return candidates[0] if candidates else ""


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def is_duplicate(existing: list[dict[str, str]], row: dict[str, str]) -> str | None:
    row_name = normalize_name(row["company_name"])
    row_domain = normalize_domain(row.get("domain", ""))

    for item in existing:
        item_name = normalize_name(item["company_name"])
        item_domain = normalize_domain(item.get("domain", ""))

        if row_domain and item_domain and row_domain == item_domain:
            return item["company_name"]
        if row_name and item_name and row_name == item_name:
            return item["company_name"]
    return None


def write_outputs(records: list[dict[str, str]], sources: list[str]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "sources": sources,
        "scraped_at": utc_now(),
        "total": len(records),
        "with_domain": sum(1 for row in records if row["domain"]),
        "without_domain": sum(1 for row in records if not row["domain"]),
        "brands": records,
    }
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with CSV_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in records:
            writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})


def merge_cognito_fashion() -> tuple[list[dict[str, str]], list[str], list[str]]:
    existing = load_csv(CSV_PATH)
    added: list[str] = []
    skipped: list[str] = []

    log(f"Existing brands in CSV: {len(existing)}")
    log("Resolving domains for Cognito Fashion & Apparel brands...")

    for brand in FASHION_BRANDS:
        domain = resolve_domain(brand["domain_candidates"])
        row = {
            "company_name": brand["company_name"],
            "domain": domain,
            "sector": brand["sector"],
        }

        duplicate_of = is_duplicate(existing, row)
        if duplicate_of:
            skipped.append(f"{brand['company_name']} (duplicate of {duplicate_of})")
            continue

        existing.append(row)
        added.append(brand["company_name"])

    existing.sort(key=lambda row: row["company_name"].casefold())
    sources = [
        "https://www.d2c.fyi/categories/clothing-brands-shark-tank-india",
        COGNITO_URL,
    ]
    return existing, added, skipped


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge Cognito Fashion & Apparel brands into clothing_brands.csv"
    )
    parser.parse_args()

    try:
        records, added, skipped = merge_cognito_fashion()
    except Exception as exc:
        log(f"Merge failed: {exc}")
        return 1

    sources = [
        "https://www.d2c.fyi/categories/clothing-brands-shark-tank-india",
        COGNITO_URL,
    ]
    write_outputs(records, sources)

    log("")
    log("Results")
    log(f"Total brands in CSV: {len(records)}")
    log(f"Added from Cognito: {len(added)}")
    for name in added:
        log(f"  + {name}")
    log(f"Skipped duplicates: {len(skipped)}")
    for item in skipped:
        log(f"  - {item}")
    log("")
    log(f"CSV:  {CSV_PATH}")
    log(f"JSON: {JSON_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
