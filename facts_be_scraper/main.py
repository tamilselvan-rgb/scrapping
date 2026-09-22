"""
Main orchestration pipeline for FACTS Belgium Exhibitor Scraper.
Coordinates directory scraping, individual profile visiting, Serper fallback,
and export to CSV (utf-8-sig) and JSON.
"""

import concurrent.futures
import json
import os
import sys
import pandas as pd
from typing import Dict, List

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from scraper import scrape_all_exhibitor_profiles
from enricher import enrich_record

CACHE_ENRICHED = os.path.join(CURRENT_DIR, "enriched_cache.json")
OUTPUT_CSV = os.path.join(CURRENT_DIR, "facts_be_exhibitors.csv")
OUTPUT_JSON = os.path.join(CURRENT_DIR, "facts_be_exhibitors.json")


def load_enriched_cache() -> Dict[str, Dict]:
    """Load existing enriched cache if available."""
    if os.path.exists(CACHE_ENRICHED):
        try:
            with open(CACHE_ENRICHED, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_enriched_cache(cache: Dict[str, Dict]):
    """Save enriched records incrementally to cache."""
    with open(CACHE_ENRICHED, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def run_pipeline(max_workers: int = 8):
    """Run full pipeline: scrape profiles -> enrich -> export."""
    print("==================================================")
    print("   FACTS Belgium Exhibitor Scraping Pipeline      ")
    print("==================================================")

    # 1. Scrape raw profiles from FACTS website
    raw_profiles = scrape_all_exhibitor_profiles()
    print(f"\n[INFO] Total raw exhibitor profiles to process: {len(raw_profiles)}")

    # 2. Enrich records with concurrency and cache
    enriched_cache = load_enriched_cache()
    to_process = [p for p in raw_profiles if p["name"] not in enriched_cache]
    print(f"[INFO] Profiles already cached: {len(enriched_cache)}, pending enrichment: {len(to_process)}")

    if to_process:
        print(f"[INFO] Enriching {len(to_process)} exhibitors with {max_workers} threads...")
        processed_count = 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_item = {executor.submit(enrich_record, item): item for item in to_process}
            for future in concurrent.futures.as_completed(future_to_item):
                item = future_to_item[future]
                try:
                    res = future.result()
                    enriched_cache[res["exhibitor_name"]] = res
                    processed_count += 1
                    if processed_count % 20 == 0 or processed_count == len(to_process):
                        print(f"[PROGRESS] Enriched {processed_count}/{len(to_process)} exhibitors...")
                        save_enriched_cache(enriched_cache)
                except Exception as e:
                    print(f"[ERR] Failed enriching '{item['name']}': {e}")

        save_enriched_cache(enriched_cache)
        print("[SUCCESS] All exhibitors enriched.")

    # 3. Assemble final records
    final_records: List[Dict] = []
    for item in raw_profiles:
        name = item["name"]
        if name in enriched_cache:
            final_records.append(enriched_cache[name])

    # 4. Standard Column Order
    column_order = [
        "exhibitor_name",
        "domain",
        "contact_number",
        "mail",
        "location",
        "country",
        "fair_stand",
        "detail_url",
        "enrichment_source",
    ]

    df = pd.DataFrame(final_records)
    for col in column_order:
        if col not in df.columns:
            df[col] = ""

    df = df[column_order]

    for col in column_order:
        df[col] = df[col].astype(str).str.strip()

    # 5. Export to CSV and JSON
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n[EXPORT] Exported CSV to: {OUTPUT_CSV}")

    df.to_json(OUTPUT_JSON, orient="records", indent=2, force_ascii=False)
    print(f"[EXPORT] Exported JSON to: {OUTPUT_JSON}")

    # 6. Quality & Completeness Report
    total = len(df)
    print("\n==================================================")
    print("           Data Completeness Report               ")
    print("==================================================")
    print(f"Total Exhibitors: {total}")
    for col in column_order:
        filled = (df[col] != "").sum()
        pct = (filled / total) * 100 if total > 0 else 0
        print(f" - {col:18}: {filled:3d} / {total:3d} ({pct:5.1f}%)")

    unique_countries = df["country"].unique()
    print(f"\nCountries represented ({len(unique_countries)} unique, all full English names):")
    for c in sorted(unique_countries):
        count = (df["country"] == c).sum()
        print(f"   • {c}: {count}")

    print("==================================================")
    print(" Pipeline completed successfully! ")
    print("==================================================\n")


if __name__ == "__main__":
    run_pipeline()
