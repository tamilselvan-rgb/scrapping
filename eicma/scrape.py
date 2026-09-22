"""
Scrape EICMA 2026 exhibitors from catalogo.eicma.it with 2026 list filtering.

Sources:
    https://catalogo.eicma.it/Espositore
    https://www.eicma.it/en/exhibitors-list-2026/  (2026 exhibitor filter)

Outputs:
    output/EICMA_exhibitors.csv
    output/EICMA_exhibitors.json
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

CATALOG_URL = "https://catalogo.eicma.it/Espositore"
DETAIL_URL = "https://catalogo.eicma.it/Espositore/GetBrandDetail"
LIST_2026_URL = "https://www.eicma.it/en/exhibitors-list-2026/"
EVENT_NAME = "EICMA"
EVENT_YEAR = "2026"

ROOT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT_DIR / "output"
CSV_PATH = OUTPUT_DIR / f"{EVENT_NAME}_exhibitors.csv"
JSON_PATH = OUTPUT_DIR / f"{EVENT_NAME}_exhibitors.json"
CHECKPOINT_PATH = OUTPUT_DIR / "checkpoint.json"
CHECKPOINT_EVERY = 25

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
}

CSV_FIELDS = [
    "name",
    "desc",
    "email",
    "phone",
    "domain",
    "address",
    "city",
    "linkedin_url",
    "stand",
    "country",
    "sector",
    "azienda_id",
    "catalogo_id",
    "brand_type",
    "source",
]

HTTP_CONCURRENCY = 10
TIMEOUT_SECONDS = 90.0
MAX_RETRIES = 4

SOCIAL_HOSTS = {
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "tiktok.com",
    "pinterest.com",
}

BLACKLISTED_DOMAINS = SOCIAL_HOSTS | {
    "eicma.it",
    "catalogo.eicma.it",
    "wikipedia.org",
    "yellowpages.com",
}


def log(message: str) -> None:
    print(message, flush=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def norm_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def domain_from_description(desc: str) -> str:
    if not desc:
        return ""
    for match in re.finditer(
        r"(?:https?://)?(?:www\.)?([a-z0-9][a-z0-9.-]+\.[a-z]{2,})",
        desc,
        re.I,
    ):
        host = match.group(1).lower()
        if host not in BLACKLISTED_DOMAINS and "eicma" not in host:
            return host
    return ""


def normalize_domain(raw: str) -> str:
    if not raw:
        return ""
    value = raw.strip()
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
        value = "https://" + value.lstrip("/")
    host = urlparse(value).netloc.lower().removeprefix("www.")
    if not host or "." not in host:
        return ""
    if any(blocked in host for blocked in BLACKLISTED_DOMAINS):
        return ""
    return host


def is_social_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(social in host for social in SOCIAL_HOSTS)


async def request_text(
    client: httpx.AsyncClient,
    url: str,
    *,
    method: str = "GET",
    data: dict[str, str] | None = None,
) -> str:
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if method == "POST":
                response = await client.post(url, data=data)
            else:
                response = await client.get(url)
            if response.status_code in {429, 500, 502, 503, 504}:
                await asyncio.sleep(min(2**attempt, 16))
                continue
            response.raise_for_status()
            return response.text
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
            last_error = exc
            await asyncio.sleep(min(2**attempt, 16))
    raise RuntimeError(f"Failed after {MAX_RETRIES} retries: {url}") from last_error


def fetch_2026_exhibitor_names(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    names: list[str] = []
    for row in soup.select("table tr"):
        text = clean_text(row.get_text())
        if text and text.upper() != "A-Z":
            names.append(text)
    if not names:
        raise ValueError("Could not parse 2026 exhibitor list from eicma.it")
    return names


def build_2026_lookup(names: list[str]) -> tuple[set[str], dict[str, str]]:
    norm_set = {norm_name(name) for name in names}
    lookup: dict[str, str] = {}
    for name in names:
        lookup[norm_name(name)] = name
    return norm_set, lookup


def matches_2026_list(card_name: str, norm_set: set[str]) -> bool:
    normalized = norm_name(card_name)
    if normalized in norm_set:
        return True
    for part in re.split(r"\s*-\s*", card_name):
        part_norm = norm_name(part)
        if part_norm and part_norm in norm_set:
            return True
    if len(normalized) >= 5:
        for candidate in norm_set:
            if len(candidate) >= 5 and (normalized in candidate or candidate in normalized):
                return True
    return False


def parse_catalog_cards(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    cards: list[dict[str, str]] = []
    for card in soup.select(".card.scheda-blocco.divOpenPopupBrand"):
        name_el = card.select_one(".padiglione")
        stand_el = card.select_one("h5.rappresentato")
        country_el = card.select_one("p.brand")
        if not name_el:
            continue
        cards.append(
            {
                "name": clean_text(name_el.get_text()),
                "stand": clean_text(stand_el.get_text()) if stand_el else "",
                "country": clean_text(country_el.get_text()) if country_el else "",
                "azienda_id": str(card.get("data-aziendaid", "")),
                "catalogo_id": str(card.get("data-catalogoid", "")),
                "brand_type": str(card.get("data-brandtype", "")),
            }
        )
    if not cards:
        raise ValueError("No exhibitor cards found on catalog page")
    return cards


def h5_by_icon(soup: BeautifulSoup, icon_class: str) -> str:
    for heading in soup.select(".address-espositore h5"):
        icon = heading.select_one("span")
        if icon and icon_class in " ".join(icon.get("class", [])):
            text = clean_text(heading.get_text(" ", strip=True))
            link = heading.select_one("a[href]")
            if link and link.get("href", "").startswith("http"):
                return clean_text(link.get_text()) or link["href"]
            return text
    return ""


def parse_detail_html(html: str, base: dict[str, str]) -> dict[str, str]:
    soup = BeautifulSoup(html, "lxml")
    record = dict(base)

    header = soup.select_one(".header-scheda-eespositore h3")
    if header:
        record["name"] = clean_text(header.get_text())

    stand_el = soup.select_one(".label-padiglione")
    if stand_el:
        stand_text = clean_text(stand_el.get_text())
        stand_text = re.sub(r"^PAD\s*", "Pad. ", stand_text, flags=re.I)
        stand_text = re.sub(r"\s*STAND\s*", " - Stand ", stand_text, flags=re.I)
        record["stand"] = clean_text(stand_text)

    record["address"] = h5_by_icon(soup, "fa-map-marked")
    country_line = h5_by_icon(soup, "fa-city")
    if country_line:
        record["country"] = country_line

    sector_line = h5_by_icon(soup, "fa-wrench")
    if sector_line:
        record["sector"] = sector_line

    website = ""
    for heading in soup.select(".address-espositore h5"):
        link = heading.select_one("a[href^='http']")
        if link and not is_social_url(link["href"]):
            website = link["href"]
            break
    record["domain"] = normalize_domain(website)

    desc_el = soup.select_one(".desc-espositore")
    if desc_el:
        record["desc"] = clean_text(desc_el.get_text(" ", strip=True))

    linkedin = ""
    for anchor in soup.select("a[href*='linkedin.com']"):
        href = anchor.get("href", "")
        if href and "eicma" not in href.lower():
            linkedin = href.split("?")[0]
            break
    record["linkedin_url"] = linkedin

    for anchor in soup.select("a[href^='mailto:']"):
        record["email"] = clean_text(anchor["href"].replace("mailto:", ""))
        break

    phone_match = re.search(
        r"(?:\+?\d[\d\s()./-]{7,}\d)",
        record.get("desc", "") + " " + record.get("address", ""),
    )
    if phone_match and not record.get("phone"):
        record["phone"] = clean_text(phone_match.group(0))

    if not record.get("city") and record.get("address"):
        parts = [p.strip() for p in record["address"].split(",") if p.strip()]
        if len(parts) >= 2:
            record["city"] = parts[-1]

    if not record.get("domain"):
        record["domain"] = domain_from_description(record.get("desc", ""))

    for field in CSV_FIELDS:
        record.setdefault(field, "")

    record["source"] = "catalogo.eicma.it"
    return record


class SerperEnricher:
    def __init__(self, api_key: str | None) -> None:
        self.api_key = api_key
        self.endpoint = "https://google.serper.dev/search"

    async def enrich(self, client: httpx.AsyncClient, record: dict[str, str]) -> dict[str, str]:
        if not self.api_key:
            return record

        needs_domain = not record.get("domain")
        needs_desc = not record.get("desc")
        needs_linkedin = not record.get("linkedin_url")
        if not (needs_domain or needs_desc or needs_linkedin):
            return record

        query = f'"{record["name"]}" official website {EVENT_YEAR}'
        headers = {"X-API-KEY": self.api_key, "Content-Type": "application/json"}
        try:
            response = await client.post(
                self.endpoint,
                headers=headers,
                json={"q": query, "num": 10},
                timeout=20.0,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            log(f"  Serper failed for {record['name']}: {exc}")
            return record

        organic = data.get("organic", [])
        knowledge = data.get("knowledgeGraph") or {}

        if needs_domain:
            website = knowledge.get("website")
            if website:
                record["domain"] = normalize_domain(website)
            if not record.get("domain"):
                for item in organic:
                    domain = normalize_domain(item.get("link", ""))
                    if domain:
                        record["domain"] = domain
                        break

        if needs_desc:
            snippet = knowledge.get("description") or (organic[0].get("snippet") if organic else "")
            if snippet:
                record["desc"] = clean_text(snippet)

        if needs_linkedin:
            for item in organic:
                link = item.get("link", "")
                if "linkedin.com/company" in link.lower() or "linkedin.com/in/" in link.lower():
                    record["linkedin_url"] = link.split("?")[0]
                    break

        return record


def card_key(card: dict[str, str]) -> str:
    return f"{card['azienda_id']}:{card['catalogo_id']}:{card['brand_type']}"


def load_checkpoint() -> tuple[set[str], list[dict[str, str]]]:
    if not CHECKPOINT_PATH.exists():
        return set(), []
    try:
        payload = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
        done = set(payload.get("completed_keys", []))
        records = payload.get("records", [])
        return done, records
    except (json.JSONDecodeError, OSError):
        return set(), []


def save_checkpoint(done: set[str], records: list[dict[str, str]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": utc_now(),
        "completed_keys": sorted(done),
        "records": records,
    }
    CHECKPOINT_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def empty_record(name: str) -> dict[str, str]:
    return {
        "name": name,
        "desc": "",
        "email": "",
        "phone": "",
        "domain": "",
        "address": "",
        "city": "",
        "linkedin_url": "",
        "stand": "",
        "country": "",
        "sector": "",
        "azienda_id": "",
        "catalogo_id": "",
        "brand_type": "",
        "source": "eicma.it/list-2026",
    }


async def scrape(concurrency: int, enrich: bool) -> list[dict[str, str]]:
    timeout = httpx.Timeout(TIMEOUT_SECONDS)
    limits = httpx.Limits(max_connections=concurrency + 4, max_keepalive_connections=concurrency)
    semaphore = asyncio.Semaphore(concurrency)

    load_dotenv(ROOT_DIR.parent / ".env")
    serper = SerperEnricher(os.getenv("SERPER_API_KEY"))

    async with httpx.AsyncClient(
        headers=HEADERS,
        timeout=timeout,
        limits=limits,
        follow_redirects=True,
    ) as client:
        log("[1/5] Loading official EICMA 2026 exhibitor list...")
        list_html = await request_text(client, LIST_2026_URL)
        names_2026 = fetch_2026_exhibitor_names(list_html)
        norm_set, lookup = build_2026_lookup(names_2026)
        log(f"Official 2026 exhibitors: {len(names_2026)}")

        log("[2/5] Loading catalogo.eicma.it exhibitor cards...")
        catalog_html = await request_text(client, CATALOG_URL)
        cards = parse_catalog_cards(catalog_html)
        matched_cards = [card for card in cards if matches_2026_list(card["name"], norm_set)]
        log(f"Catalog cards: {len(cards)} | matched to 2026 list: {len(matched_cards)}")

        done_keys, records = load_checkpoint()
        pending_cards = [card for card in matched_cards if card_key(card) not in done_keys]
        if done_keys:
            log(f"Resuming checkpoint: {len(done_keys)} done, {len(pending_cards)} remaining")

        log(f"[3/5] Fetching detail cards for {len(pending_cards)} exhibitors...")

        async def load_detail(card: dict[str, str]) -> dict[str, str]:
            async with semaphore:
                html = await request_text(
                    client,
                    DETAIL_URL,
                    method="POST",
                    data={
                        "aziendaId": card["azienda_id"],
                        "catalogoId": card["catalogo_id"],
                        "brandType": card["brand_type"],
                    },
                )
            return parse_detail_html(html, card)

        completed = len(done_keys)
        total = len(matched_cards)
        for index in range(0, len(pending_cards), CHECKPOINT_EVERY):
            batch = pending_cards[index : index + CHECKPOINT_EVERY]
            batch_tasks = [load_detail(card) for card in batch]
            batch_results = await asyncio.gather(*batch_tasks)
            for card, result in zip(batch, batch_results):
                records.append(result)
                done_keys.add(card_key(card))
            completed = len(done_keys)
            save_checkpoint(done_keys, records)
            log(f"Detail cards fetched: {completed}/{total}")

        covered_norm = {norm_name(row["name"]) for row in records}
        for card in matched_cards:
            covered_norm.add(norm_name(card["name"]))
            for part in re.split(r"\s*-\s*", card["name"]):
                covered_norm.add(norm_name(part))

        missing_names = [
            lookup[n]
            for n in lookup
            if n not in covered_norm
            and not any(n in c or c in n for c in covered_norm if len(c) >= 5)
        ]
        log(f"[4/5] Adding {len(missing_names)} 2026 exhibitors not found in catalog cards...")

        for name in missing_names:
            records.append(empty_record(name))

        if enrich:
            missing_domains = [row for row in records if not row.get("domain")]
            log(f"Enriching {len(missing_domains)} exhibitors via Serper...")
            enriched = 0
            for row in records:
                if row.get("domain"):
                    continue
                before = row.get("domain", "")
                row.update(await serper.enrich(client, row))
                if row.get("domain") and not before:
                    enriched += 1
            log(f"Serper resolved domains for {enriched}/{len(missing_domains)} exhibitors")
        else:
            log("[4/5] Skipping Serper enrichment")

    records.sort(key=lambda row: row["name"].casefold())
    return records


def write_outputs(records: list[dict[str, str]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "event": "EICMA",
        "year": EVENT_YEAR,
        "sources": [CATALOG_URL, LIST_2026_URL],
        "scraped_at": utc_now(),
        "total": len(records),
        "with_domain": sum(1 for row in records if row["domain"]),
        "without_domain": sum(1 for row in records if not row["domain"]),
        "exhibitors": records,
    }
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in records:
            writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})


def print_summary(records: list[dict[str, str]]) -> None:
    log("")
    log("[5/5] Results")
    log(f"Exhibitors: {len(records)}")
    log(f"Domains: {sum(1 for row in records if row['domain'])}")
    log(f"Descriptions: {sum(1 for row in records if row['desc'])}")
    log(f"Emails: {sum(1 for row in records if row['email'])}")
    log(f"Phones: {sum(1 for row in records if row['phone'])}")
    log(f"LinkedIn: {sum(1 for row in records if row['linkedin_url'])}")
    log("")
    log("Saved:")
    log(f"  CSV:  {CSV_PATH}")
    log(f"  JSON: {JSON_PATH}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape EICMA 2026 exhibitors")
    parser.add_argument("--concurrency", type=int, default=HTTP_CONCURRENCY)
    parser.add_argument("--no-enrich", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        records = asyncio.run(scrape(concurrency=args.concurrency, enrich=not args.no_enrich))
    except KeyboardInterrupt:
        log("Interrupted.")
        return 130
    except Exception as exc:
        log(f"Scrape failed: {exc}")
        return 1

    write_outputs(records)
    print_summary(records)
    if CHECKPOINT_PATH.exists() and CSV_PATH.exists():
        CHECKPOINT_PATH.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
