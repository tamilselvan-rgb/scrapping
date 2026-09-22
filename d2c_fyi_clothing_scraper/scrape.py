"""
Scrape clothing brands from d2c.fyi Shark Tank India category page.

Source:
    https://www.d2c.fyi/categories/clothing-brands-shark-tank-india

Outputs:
    output/clothing_brands.csv
    output/clothing_brands.json
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import html as html_lib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

CATEGORY_URL = "https://www.d2c.fyi/categories/clothing-brands-shark-tank-india"
BASE_SITE = "https://www.d2c.fyi"

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
CSV_PATH = OUTPUT_DIR / "clothing_brands.csv"
JSON_PATH = OUTPUT_DIR / "clothing_brands.json"

HTTP_CONCURRENCY = 8
TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 4

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

CSV_FIELDS = ["company_name", "domain", "sector"]

SOCIAL_HOSTS = {
    "instagram.com",
    "facebook.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "youtube.com",
    "youtu.be",
    "pinterest.com",
    "tiktok.com",
    "amazon.in",
    "amazon.com",
    "amzn.to",
    "play.google.com",
    "apps.apple.com",
}

SKIP_HOSTS = {"d2c.fyi", "umami.vempus.com", "analytics.ahrefs.com"}


def log(message: str) -> None:
    print(message, flush=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def domain_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return host


def parse_category_brands(html: str) -> list[dict[str, str]]:
    match = re.search(
        r'<script type="application/ld\+json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        raise ValueError("Could not find JSON-LD on category page")

    payload = json.loads(match.group(1))
    graph = payload.get("@graph") or []
    collection = next(
        (node for node in graph if node.get("@type") == "CollectionPage"),
        None,
    )
    if not collection:
        raise ValueError("Could not find CollectionPage in JSON-LD")

    items = (collection.get("mainEntity") or {}).get("itemListElement") or []
    brands: list[dict[str, str]] = []
    for entry in items:
        item = entry.get("item") or {}
        name = str(item.get("name") or "").strip()
        profile_url = str(item.get("url") or "").strip()
        slug = profile_url.rstrip("/").split("/")[-1] if profile_url else ""
        if not name or not slug:
            continue
        brands.append(
            {
                "company_name": name,
                "slug": slug,
                "profile_url": profile_url,
            }
        )
    return brands


def extract_brand_details(html: str) -> dict[str, str]:
    name = ""
    match = re.search(r'<p class="text-4xl font-bold[^"]*">([^<]+)</p>', html)
    if match:
        name = match.group(1).strip()

    sector_parts: list[str] = []
    for category_match in re.finditer(
        r'href="/categories/[^"]+"><div[^>]*>([^<]+)</div></a>',
        html,
    ):
        sector_parts.append(category_match.group(1).strip())
    sector = "; ".join(dict.fromkeys(sector_parts))

    if not sector:
        subtitle_match = re.search(
            r'<h1[^>]*>[^<]*<!-- --> - <!-- -->([^<]+)<!-- --> - Shark Tank',
            html,
        )
        if subtitle_match:
            sector = subtitle_match.group(1).strip()

    domain = ""
    for url in re.findall(r'href="(https?://[^"]+)"', html):
        host = domain_from_url(url)
        if not host or host in SKIP_HOSTS:
            continue
        if any(host == social or host.endswith("." + social) for social in SOCIAL_HOSTS):
            continue
        if "amazon" in host:
            continue
        domain = host
        break

    if not domain:
        image_match = re.search(r'property="og:image" content="(https?://[^"]+)"', html)
        if image_match:
            host = domain_from_url(image_match.group(1))
            if host and host not in SKIP_HOSTS:
                domain = host

    return {
        "company_name": html_lib.unescape(name),
        "domain": domain,
        "sector": html_lib.unescape(sector),
    }


async def request_text(client: httpx.AsyncClient, url: str) -> str:
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = await client.get(url)
            if response.status_code in {429, 500, 502, 503, 504}:
                wait = min(2**attempt, 16)
                log(f"  HTTP {response.status_code} for {url} — retry {attempt}/{MAX_RETRIES}")
                await asyncio.sleep(wait)
                continue
            response.raise_for_status()
            return response.text
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
            last_error = exc
            wait = min(2**attempt, 16)
            log(f"  Request failed ({type(exc).__name__}): {exc} — retry {attempt}/{MAX_RETRIES}")
            await asyncio.sleep(wait)
    raise RuntimeError(f"Failed after {MAX_RETRIES} retries: {url}") from last_error


async def fetch_brand_page(
    client: httpx.AsyncClient,
    slug: str,
    semaphore: asyncio.Semaphore,
) -> str:
    async with semaphore:
        return await request_text(client, f"{BASE_SITE}/brands/{slug}")


def write_outputs(records: list[dict[str, str]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "source": CATEGORY_URL,
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


async def scrape(concurrency: int) -> list[dict[str, str]]:
    timeout = httpx.Timeout(TIMEOUT_SECONDS)
    limits = httpx.Limits(max_connections=concurrency + 4, max_keepalive_connections=concurrency)
    semaphore = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(
        headers=HEADERS,
        timeout=timeout,
        limits=limits,
        follow_redirects=True,
    ) as client:
        log("[1/3] Loading category page...")
        category_html = await request_text(client, CATEGORY_URL)
        brands = parse_category_brands(category_html)
        log(f"Found {len(brands)} brands in category listing")

        log(f"[2/3] Fetching {len(brands)} brand profile pages...")
        tasks = [
            fetch_brand_page(client, brand["slug"], semaphore)
            for brand in brands
        ]
        pages = await asyncio.gather(*tasks)
        log(f"Profiles fetched: {len(pages)}/{len(brands)}")

    records: list[dict[str, str]] = []
    for brand, page_html in zip(brands, pages):
        details = extract_brand_details(page_html)
        records.append(
            {
                "company_name": details["company_name"] or brand["company_name"],
                "domain": details["domain"],
                "sector": details["sector"],
            }
        )

    records.sort(key=lambda row: row["company_name"].casefold())
    return records


def print_summary(records: list[dict[str, str]]) -> None:
    with_domain = sum(1 for row in records if row["domain"])
    log("")
    log("[3/3] Results")
    log(f"Companies: {len(records)}")
    log(f"Domains found: {with_domain}")
    log(f"Missing domain: {len(records) - with_domain}")
    log("")
    log("Saved:")
    log(f"  CSV:  {CSV_PATH}")
    log(f"  JSON: {JSON_PATH}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape clothing brands from d2c.fyi Shark Tank India category"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=HTTP_CONCURRENCY,
        help="Concurrent profile requests (default: 8)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        records = asyncio.run(scrape(concurrency=args.concurrency))
    except KeyboardInterrupt:
        log("Interrupted.")
        return 130
    except Exception as exc:
        log(f"Scrape failed: {exc}")
        return 1

    write_outputs(records)
    print_summary(records)
    return 0


if __name__ == "__main__":
    sys.exit(main())
