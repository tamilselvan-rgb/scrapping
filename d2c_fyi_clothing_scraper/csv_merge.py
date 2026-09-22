"""Shared CSV merge helpers for clothing brand scrapers."""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
CSV_PATH = OUTPUT_DIR / "clothing_brands.csv"
JSON_PATH = OUTPUT_DIR / "clothing_brands.json"
CSV_FIELDS = ["company_name", "domain", "sector"]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def normalize_domain(domain: str) -> str:
    return domain.casefold().removeprefix("www.").strip()


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
