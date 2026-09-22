"""
Scrape Fashion brands from Discovering Brands and merge into clothing_brands.csv.

Source:
    https://discoveringbrands.com/category/fashion
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from csv_merge import CSV_FIELDS, CSV_PATH, JSON_PATH, OUTPUT_DIR, is_duplicate, load_csv, write_outputs

FASHION_URL = "https://discoveringbrands.com/category/fashion"
TIMEOUT_SECONDS = 120.0
DOMAIN_CONCURRENCY = 12

PARKING_HOSTS = {
    "hugedomains.com",
    "godaddy.com",
    "sedoparking.com",
    "afternic.com",
    "dan.com",
    "namecheap.com",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

BRAND_PATTERN = re.compile(
    r'\\"name\\":\\"([^\\]+)\\",\\"id\\":\\"[^\\]+\\",\\"path\\":\\"([^\\]+)\\",\\"image\\":\\"([^\\]*)\\"',
)
RSC_PATTERN = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', re.DOTALL)


def log(message: str) -> None:
    print(message, flush=True)


def domain_from_image(image: str) -> str:
    if not image:
        return ""
    host = urlparse(image).netloc.lower().removeprefix("www.")
    if not host or "cdn.shopify.com" in host:
        return ""
    return host


def slug_domain_candidates(path: str) -> list[str]:
    clean = re.sub(r"[^a-z0-9-]", "", path.casefold())
    compact = clean.replace("-", "")
    candidates = [
        f"{clean}.com",
        f"{clean}.in",
        f"{clean}.co.in",
        f"{clean}.store",
        f"{compact}.com",
        f"{compact}.in",
    ]
    return list(dict.fromkeys(candidates))


def parse_fashion_brands(html: str) -> list[dict[str, str]]:
    chunks = RSC_PATTERN.findall(html)
    if not chunks:
        raise ValueError("Could not find Next.js payload on fashion category page")

    combined = "\n".join(chunks)
    brands: list[dict[str, str]] = []
    seen_paths: set[str] = set()

    for name, path, image in BRAND_PATTERN.findall(combined):
        if path in seen_paths:
            continue
        seen_paths.add(path)
        brands.append(
            {
                "company_name": name.strip(),
                "domain": domain_from_image(image),
                "sector": "Fashion",
                "path": path,
            }
        )

    if not brands:
        raise ValueError("No fashion brands found in page payload")

    return brands


async def resolve_domain_from_slug(
    client: httpx.AsyncClient,
    path: str,
    semaphore: asyncio.Semaphore,
) -> str:
    async with semaphore:
        for candidate in slug_domain_candidates(path):
            for prefix in ("https://www.", "https://"):
                url = f"{prefix}{candidate}"
                try:
                    response = await client.get(url)
                    if response.status_code >= 400:
                        continue
                    host = (httpx.URL(str(response.url)).host or "").removeprefix("www.")
                    if not host or host in PARKING_HOSTS:
                        continue
                    if host != candidate and not host.endswith("." + candidate):
                        continue
                    return host
                except httpx.HTTPError:
                    continue
    return ""


async def fill_missing_domains(brands: list[dict[str, str]]) -> None:
    missing = [brand for brand in brands if not brand.get("domain")]
    if not missing:
        return

    log(f"Resolving domains for {len(missing)} brands without image URLs...")
    timeout = httpx.Timeout(15.0)
    semaphore = asyncio.Semaphore(DOMAIN_CONCURRENCY)

    async with httpx.AsyncClient(
        headers=HEADERS,
        timeout=timeout,
        follow_redirects=True,
    ) as client:
        tasks = [
            resolve_domain_from_slug(client, brand["path"], semaphore)
            for brand in missing
        ]
        results = await asyncio.gather(*tasks)

    resolved = 0
    for brand, domain in zip(missing, results):
        if domain:
            brand["domain"] = domain
            resolved += 1
    log(f"Resolved {resolved}/{len(missing)} missing domains from slug")


def fetch_fashion_page() -> str:
    with httpx.Client(
        headers=HEADERS,
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
    ) as client:
        response = client.get(FASHION_URL)
        response.raise_for_status()
        return response.text


def merge_discovering_fashion(resolve_missing: bool) -> tuple[list[dict[str, str]], list[str], list[str]]:
    log("[1/4] Fetching Discovering Brands fashion category...")
    html = fetch_fashion_page()
    discovered = parse_fashion_brands(html)
    log(f"Found {len(discovered)} fashion brands in page payload")

    if resolve_missing:
        log("[2/4] Filling missing domains...")
        asyncio.run(fill_missing_domains(discovered))
    else:
        log("[2/4] Skipping slug-based domain resolution")

    existing = load_csv(CSV_PATH)
    log(f"Existing brands in CSV: {len(existing)}")

    added: list[str] = []
    skipped: list[str] = []

    log("[3/4] Merging with deduplication...")
    for brand in discovered:
        row = {
            "company_name": brand["company_name"],
            "domain": brand.get("domain", ""),
            "sector": brand["sector"],
        }
        duplicate_of = is_duplicate(existing, row)
        if duplicate_of:
            skipped.append(f"{brand['company_name']} (duplicate of {duplicate_of})")
            continue
        existing.append(row)
        added.append(brand["company_name"])

    existing.sort(key=lambda row: row["company_name"].casefold())
    return existing, added, skipped


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scrape Discovering Brands fashion category into clothing_brands.csv"
    )
    parser.add_argument(
        "--no-resolve-domains",
        action="store_true",
        help="Skip slug-based domain resolution for brands without image URLs",
    )
    args = parser.parse_args()

    try:
        records, added, skipped = merge_discovering_fashion(
            resolve_missing=not args.no_resolve_domains
        )
    except KeyboardInterrupt:
        log("Interrupted.")
        return 130
    except Exception as exc:
        log(f"Scrape failed: {exc}")
        return 1

    sources = [
        "https://www.d2c.fyi/categories/clothing-brands-shark-tank-india",
        "https://cognitoitconsultancy.com/top-d2c-brands-india-2026/",
        FASHION_URL,
    ]
    write_outputs(records, sources)

    log("")
    log("[4/4] Results")
    log(f"Total brands in CSV: {len(records)}")
    log(f"Added from Discovering Brands: {len(added)}")
    log(f"Skipped duplicates: {len(skipped)}")
    if skipped:
        for item in skipped[:10]:
            log(f"  - {item}")
        if len(skipped) > 10:
            log(f"  ... and {len(skipped) - 10} more")
    log("")
    log(f"CSV:  {CSV_PATH}")
    log(f"JSON: {JSON_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
