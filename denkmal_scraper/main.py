"""
Denkmal 2026 exhibitor scraping pipeline.
"""

import json
import os
import sys

import pandas as pd

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from enricher import enrich_records
from scraper import scrape_all_exhibitors

EVENT_NAME = "DENKMAL_2026"
OUTPUT_CSV = os.path.join(CURRENT_DIR, f"{EVENT_NAME}_exhibitors.csv")
OUTPUT_JSON = os.path.join(CURRENT_DIR, f"{EVENT_NAME}_exhibitors.json")
ENRICHED_CACHE = os.path.join(CURRENT_DIR, "enriched_cache.json")

COLUMN_ORDER = [
    "name",
    "desc",
    "email",
    "phone",
    "domain",
    "address",
    "city",
    "linkedin_url",
    "country",
    "detail_url",
    "fair_stand",
    "product_groups",
    "enrichment_source",
]


def load_enriched_cache() -> dict:
    if os.path.exists(ENRICHED_CACHE):
        with open(ENRICHED_CACHE, "r", encoding="utf-8") as handle:
            return json.load(handle)
    return {}


def save_enriched_cache(cache: dict) -> None:
    with open(ENRICHED_CACHE, "w", encoding="utf-8") as handle:
        json.dump(cache, handle, indent=2, ensure_ascii=False)


def run_pipeline(force_refresh: bool = False) -> None:
    print("=" * 50)
    print("   Denkmal 2026 Exhibitor Scraping Pipeline")
    print("=" * 50)

    raw_records = scrape_all_exhibitors(force_refresh=force_refresh)
    print(f"[INFO] Raw exhibitor records: {len(raw_records)}")

    cache = load_enriched_cache()
    pending = [r for r in raw_records if r.get("name") not in cache]
    if pending:
        print(f"[INFO] Enriching {len(pending)} exhibitors ({len(cache)} cached)...")
        for record in pending:
            from enricher import enrich_record

            enriched = enrich_record(record)
            cache[enriched["name"]] = enriched
        save_enriched_cache(cache)
    else:
        print(f"[INFO] Using enriched cache for {len(cache)} exhibitors.")

    final_records = []
    for record in raw_records:
        name = record.get("name")
        if name in cache:
            final_records.append(cache[name])

    df = pd.DataFrame(final_records)
    for column in COLUMN_ORDER:
        if column not in df.columns:
            df[column] = ""
    df = df[COLUMN_ORDER]
    for column in COLUMN_ORDER:
        df[column] = df[column].astype(str).str.strip()

    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    df.to_json(OUTPUT_JSON, orient="records", indent=2, force_ascii=False)

    total = len(df)
    print(f"\n[EXPORT] CSV: {OUTPUT_CSV}")
    print(f"[EXPORT] JSON: {OUTPUT_JSON}")
    print("\nData completeness:")
    for column in COLUMN_ORDER:
        filled = (df[column] != "").sum()
        pct = (filled / total * 100) if total else 0
        print(f" - {column:18}: {filled:3d} / {total:3d} ({pct:5.1f}%)")
    print("=" * 50)


if __name__ == "__main__":
    run_pipeline(force_refresh="--refresh" in sys.argv)
