#!/usr/bin/env python3
"""
Main runner for FIA Futures & Options Expo Exhibitor Scraper.
Scrapes the 49 exhibitors from the official FIA Expo portal, enriches contact details
via direct website crawling & non-Serper enrichment, and exports to CSV with utf-8-sig encoding.
"""

import os
import sys
import csv
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.stdout.reconfigure(encoding='utf-8')

from scraper import scrape_fia_exhibitors
from enricher import enrich_exhibitor

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(OUTPUT_DIR, "fia_expo_exhibitors.csv")
JSON_FILE = os.path.join(OUTPUT_DIR, "fia_expo_exhibitors.json")

FIELDNAMES = [
    "exhibitor_name",
    "domain",
    "contact_number",
    "mail",
    "location",
    "country",
    "address"
]


def main():
    print("=" * 70)
    print("Starting FIA Expo Exhibitor Scraper Pipeline")
    print("=" * 70)

    # 1. Scrape raw exhibitors from FIA Expo
    raw_exhibitors = scrape_fia_exhibitors()
    total_count = len(raw_exhibitors)
    print(f"\n[INFO] Successfully extracted {total_count} exhibitors from FIA Expo.\n")

    # 2. Enrich exhibitors concurrently
    print("[INFO] Starting enrichment (crawling domains & contacts, no Serper)...")
    enriched_results = [None] * total_count

    # Maintain original order
    with ThreadPoolExecutor(max_workers=6) as executor:
        future_to_idx = {
            executor.submit(enrich_exhibitor, exh): idx
            for idx, exh in enumerate(raw_exhibitors)
        }

        completed = 0
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                result = future.result()
                enriched_results[idx] = result
                completed += 1
                print(f"[{completed}/{total_count}] Enriched: {result['exhibitor_name']} | Country: {result.get('country')}", flush=True)
            except Exception as e:
                print(f"[ERROR] Failed to enrich index {idx}: {e}", flush=True)
                enriched_results[idx] = raw_exhibitors[idx]

    # 3. Export to CSV with utf-8-sig
    print(f"\n[INFO] Writing CSV to: {CSV_FILE}")
    with open(CSV_FILE, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for row in enriched_results:
            writer.writerow(row)

    # 4. Export to JSON
    print(f"[INFO] Writing JSON to: {JSON_FILE}")
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(enriched_results, f, indent=2, ensure_ascii=False)

    # 5. Validation & Summary
    print("\n" + "=" * 70)
    print("SCRAPING & ENRICHMENT SUMMARY")
    print("=" * 70)
    print(f"Total Exhibitors Scraped : {len(enriched_results)}")
    print(f"Has Domain               : {sum(1 for r in enriched_results if r.get('domain'))}/{len(enriched_results)}")
    print(f"Has Contact Number       : {sum(1 for r in enriched_results if r.get('contact_number'))}/{len(enriched_results)}")
    print(f"Has Email                : {sum(1 for r in enriched_results if r.get('mail'))}/{len(enriched_results)}")
    print(f"Has Location             : {sum(1 for r in enriched_results if r.get('location'))}/{len(enriched_results)}")
    print(f"Has Country              : {sum(1 for r in enriched_results if r.get('country'))}/{len(enriched_results)}")

    countries = sorted(set(r.get("country") for r in enriched_results if r.get("country")))
    print(f"\nUnique Countries Found ({len(countries)}):")
    for c in countries:
        print(f"  - {c}")

    print(f"\n[SUCCESS] Pipeline completed successfully. Output saved to:\n  {CSV_FILE}")


if __name__ == "__main__":
    main()
