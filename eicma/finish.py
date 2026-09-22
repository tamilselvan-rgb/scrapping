"""
Post-process EICMA exhibitor output: re-fetch sparse cards, dedupe, normalize fields.
"""

from __future__ import annotations

import asyncio
import csv
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from scrape import (  # noqa: E402
    CSV_FIELDS,
    CSV_PATH,
    DETAIL_URL,
    EVENT_YEAR,
    HEADERS,
    clean_text,
    domain_from_description,
    norm_name,
    parse_detail_html,
    write_outputs,
)

CONCURRENCY = 12


def log(msg: str) -> None:
    print(msg, flush=True)


def ensure_fields(row: dict[str, str]) -> dict[str, str]:
    return {field: clean_text(row.get(field, "")) for field in CSV_FIELDS}


def richness(row: dict[str, str]) -> int:
    return sum(1 for field in CSV_FIELDS if row.get(field))


def dedupe_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    best: dict[str, dict[str, str]] = {}
    for row in rows:
        key = norm_name(row["name"])
        if not key:
            continue
        existing = best.get(key)
        if not existing or richness(row) > richness(existing):
            best[key] = row
    return list(best.values())


async def refetch_sparse(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    targets = [
        row
        for row in rows
        if row.get("azienda_id")
        and row.get("catalogo_id")
        and (not row.get("domain") or not row.get("desc") or not row.get("address"))
    ]
    if not targets:
        return rows

    log(f"Re-fetching {len(targets)} sparse catalog detail cards...")
    sem = asyncio.Semaphore(CONCURRENCY)
    catalog_rows = {
        f"{r['azienda_id']}:{r['catalogo_id']}:{r['brand_type']}": r
        for r in rows
        if r.get("azienda_id")
    }
    list_only = [r for r in rows if not r.get("azienda_id")]

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=60) as client:
        async def one(row: dict[str, str]) -> None:
            async with sem:
                response = await client.post(
                    DETAIL_URL,
                    data={
                        "aziendaId": row["azienda_id"],
                        "catalogoId": row["catalogo_id"],
                        "brandType": row["brand_type"],
                    },
                )
                response.raise_for_status()
                updated = parse_detail_html(response.text, row)
                key = f"{row['azienda_id']}:{row['catalogo_id']}:{row['brand_type']}"
                catalog_rows[key] = ensure_fields(updated)

        await asyncio.gather(*(one(row) for row in targets))

    return list(catalog_rows.values()) + list_only


def fill_domain_from_text(rows: list[dict[str, str]]) -> None:
    for row in rows:
        if row.get("domain"):
            continue
        domain = domain_from_description(row.get("desc", ""))
        if domain:
            row["domain"] = domain


def main() -> int:
    rows = [ensure_fields(r) for r in csv.DictReader(CSV_PATH.open(encoding="utf-8-sig"))]
    log(f"Loaded {len(rows)} rows")

    rows = dedupe_rows(rows)
    log(f"After dedupe: {len(rows)}")

    rows = asyncio.run(refetch_sparse(rows))
    fill_domain_from_text(rows)

    rows.sort(key=lambda r: r["name"].casefold())
    write_outputs(rows)

    log("")
    log("Final")
    log(f"Exhibitors: {len(rows)}")
    log(f"Domains: {sum(1 for r in rows if r['domain'])}")
    log(f"Descriptions: {sum(1 for r in rows if r['desc'])}")
    log(f"Addresses: {sum(1 for r in rows if r['address'])}")
    log(f"Saved: {CSV_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
