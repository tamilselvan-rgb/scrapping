"""
Scrape all D2C brand listings from https://d2cstories.com/d2c-brands/list

The public directory is JavaScript-rendered. This script uses the same public
API the website uses, paginates every list page, then opens each brand profile
to collect company name and official domain URL.

Outputs:
    output/d2c_brands.json
    output/d2c_brands.csv
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
from urllib.parse import urlparse, urlunparse

import httpx

BASE_SITE = "https://d2cstories.com"
API_BASE = "https://api.d2cstories.com"
LIST_URL = f"{API_BASE}/api/brand"
DETAILS_URL = f"{API_BASE}/api/brand/get-brand-details"

# The live directory UI shows 16 brands per page (12 pages at ~192 brands).
PAGE_SIZE = 16
MAX_PAGES = 50
HTTP_CONCURRENCY = 8
TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 4

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
JSON_PATH = OUTPUT_DIR / "d2c_brands.json"
CSV_PATH = OUTPUT_DIR / "d2c_brands.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Origin": BASE_SITE,
    "Referer": f"{BASE_SITE}/d2c-brands/list",
}

CSV_FIELDS = [
    "company_name",
    "domain_url",
    "domain",
    "profile_url",
    "category",
    "city",
    "source_page",
]


def log(message: str) -> None:
    print(message, flush=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", text).strip()


def normalize_domain_url(raw: str | None) -> tuple[str, str]:
    """Return (domain_url, domain). Never invent a URL."""
    if not raw:
        return "", ""

    value = str(raw).strip()
    if not value or value.lower() in {"n/a", "na", "none", "null", "-"}:
        return "", ""

    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
        value = "https://" + value.lstrip("/")

    parsed = urlparse(value)
    host = (parsed.netloc or parsed.path.split("/")[0]).strip().lower()
    host = host.split("@")[-1]
    host = host.split(":")[0].strip(".")
    if host.startswith("www."):
        host = host[4:]

    if not host or "." not in host or " " in host:
        return "", ""
    if host in {"d2cstories.com", "api.d2cstories.com"}:
        return "", ""

    domain_url = urlunparse(("https", host, "", "", "", ""))
    return domain_url, host


def profile_url_for(slug: str) -> str:
    return f"{BASE_SITE}/d2c-brands/{slug}"


def categories_from(item: dict[str, Any]) -> str:
    details = item.get("brand_category_details") or []
    names: list[str] = []
    if isinstance(details, list):
        for row in details:
            if isinstance(row, dict):
                name = str(row.get("value") or "").strip()
                if name:
                    names.append(name)
    return "; ".join(dict.fromkeys(names))


async def request_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = await client.get(url, params=params)
            if response.status_code in {429, 500, 502, 503, 504}:
                wait = min(2 ** attempt, 16)
                log(f"  HTTP {response.status_code} for {url} — retry {attempt}/{MAX_RETRIES}")
                await asyncio.sleep(wait)
                continue
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError(f"Unexpected JSON type: {type(data)}")
            return data
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError, ValueError) as exc:
            last_error = exc
            wait = min(2 ** attempt, 16)
            log(f"  Request failed ({type(exc).__name__}): {exc} — retry {attempt}/{MAX_RETRIES}")
            await asyncio.sleep(wait)
    raise RuntimeError(f"Failed after {MAX_RETRIES} retries: {url}") from last_error


async def fetch_list_page(
    client: httpx.AsyncClient,
    page: int,
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = await request_json(client, LIST_URL, params={"page": page, "limit": limit})
    items = payload.get("data") or []
    pagination = payload.get("pagination") or {}
    if not isinstance(items, list):
        items = []
    if not isinstance(pagination, dict):
        pagination = {}
    return items, pagination


async def fetch_brand_details(
    client: httpx.AsyncClient,
    slug: str,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    async with semaphore:
        payload = await request_json(client, f"{DETAILS_URL}/{slug}")
        data = payload.get("data") or {}
        return data if isinstance(data, dict) else {}


def record_from_brand(
    list_item: dict[str, Any],
    details: dict[str, Any] | None,
    source_page: int,
) -> dict[str, str]:
    merged = dict(list_item)
    if details:
        for key, value in details.items():
            if value not in (None, "", [], {}):
                merged[key] = value

    name = str(merged.get("brand_name") or "").strip()
    slug = str(merged.get("slug") or "").strip()
    site_link = merged.get("site_link") or merged.get("website") or ""
    domain_url, domain = normalize_domain_url(str(site_link) if site_link else "")

    return {
        "company_name": name,
        "domain_url": domain_url,
        "domain": domain,
        "profile_url": profile_url_for(slug) if slug else "",
        "category": categories_from(merged),
        "city": str(merged.get("city_name") or "").strip(),
        "source_page": str(source_page),
        "slug": slug,
        "about": strip_html(str(merged.get("about") or "")),
    }


def dedupe(records: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for row in records:
        key = (
            row.get("slug")
            or row.get("profile_url")
            or row.get("domain")
            or row.get("company_name", "").casefold()
        )
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def write_outputs(records: list[dict[str, str]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_rows = [
        {
            "company_name": row["company_name"],
            "domain_url": row["domain_url"],
            "domain": row["domain"],
            "profile_url": row["profile_url"],
            "category": row["category"],
            "city": row["city"],
            "source_page": int(row["source_page"]) if str(row["source_page"]).isdigit() else row["source_page"],
        }
        for row in records
    ]
    payload = {
        "source": f"{BASE_SITE}/d2c-brands/list",
        "scraped_at": utc_now(),
        "total": len(json_rows),
        "with_domain": sum(1 for row in json_rows if row["domain_url"]),
        "without_domain": sum(1 for row in json_rows if not row["domain_url"]),
        "brands": json_rows,
    }
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with CSV_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in records:
            writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})


async def scrape(limit: int, concurrency: int) -> list[dict[str, str]]:
    timeout = httpx.Timeout(TIMEOUT_SECONDS)
    limits = httpx.Limits(max_connections=concurrency + 4, max_keepalive_connections=concurrency)
    semaphore = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(headers=HEADERS, timeout=timeout, limits=limits, follow_redirects=True) as client:
        log("[1/4] Analysing D2C Stories brand directory...")
        first_items, pagination = await fetch_list_page(client, page=1, limit=limit)
        total_items = int(pagination.get("totalItems") or 0)
        total_pages = int(pagination.get("totalPages") or 0) or 1
        if total_pages > MAX_PAGES:
            total_pages = MAX_PAGES

        log(f"Detected: API-backed directory ({LIST_URL})")
        log(f"Pagination: page/limit  |  {total_items} brands across {total_pages} pages (limit={limit})")
        log("")

        brands_by_slug: dict[str, tuple[dict[str, Any], int]] = {}
        page_items = first_items
        page = 1

        while page <= total_pages and page <= MAX_PAGES:
            if page > 1:
                page_items, pagination = await fetch_list_page(client, page=page, limit=limit)
                total_pages = max(total_pages, int(pagination.get("totalPages") or total_pages))

            if not page_items:
                log(f"Pages processed: {page}  |  no more brands — stopping")
                break

            new_count = 0
            for item in page_items:
                slug = str(item.get("slug") or "").strip()
                if not slug or slug in brands_by_slug:
                    continue
                brands_by_slug[slug] = (item, page)
                new_count += 1

            log(
                f"Pages processed: {page}/{total_pages}  |  "
                f"Exhibitors discovered: {len(brands_by_slug)}  |  new this page: {new_count}"
            )

            if new_count == 0:
                log("No new brands on this page — stopping pagination")
                break
            page += 1

        discovered = list(brands_by_slug.items())
        log("")
        log(f"[2/4] Opening {len(discovered)} brand profile pages...")

        async def load_one(slug: str, list_item: dict[str, Any], source_page: int) -> dict[str, str]:
            details: dict[str, Any] = {}
            try:
                details = await fetch_brand_details(client, slug, semaphore)
            except Exception as exc:
                log(f"  Profile failed for {slug}: {exc} — using list data")
            return record_from_brand(list_item, details, source_page)

        tasks = [
            load_one(slug, list_item, source_page)
            for slug, (list_item, source_page) in discovered
        ]
        records: list[dict[str, str]] = []
        completed = 0
        for coro in asyncio.as_completed(tasks):
            records.append(await coro)
            completed += 1
            if completed % 20 == 0 or completed == len(tasks):
                log(f"Profiles scraped: {completed}/{len(tasks)}")

    records = [row for row in records if row.get("company_name")]
    records = dedupe(records)
    records.sort(key=lambda row: row["company_name"].casefold())
    return records


def print_summary(records: list[dict[str, str]]) -> None:
    with_domain = sum(1 for row in records if row["domain_url"])
    without_domain = len(records) - with_domain
    log("")
    log("[3/4] Results")
    log(f"Companies: {len(records)}")
    log(f"Official domains found: {with_domain}")
    log(f"Missing domain: {without_domain}")
    log("")
    log("[4/4] Saving files")
    log(f"JSON: {JSON_PATH}")
    log(f"CSV:  {CSV_PATH}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape company names and domain URLs from d2cstories.com/d2c-brands/list"
    )
    parser.add_argument("--limit", type=int, default=PAGE_SIZE, help="Brands per list page (default: 16)")
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
        records = asyncio.run(scrape(limit=args.limit, concurrency=args.concurrency))
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
