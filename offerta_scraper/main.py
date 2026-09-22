import os
import sys
import json
import logging
import pandas as pd

# Reconfigure stdout for utf-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from scraper import OffertaScraper
from enricher import OffertaEnricher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("offerta_main")

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "offerta_exhibitors.csv")
OUTPUT_JSON = os.path.join(OUTPUT_DIR, "offerta_exhibitors.json")

def main():
    logger.info("=== Starting Offerta 2026 Exhibitor Scraping & Enrichment Pipeline ===")
    
    # 1. Scrape all exhibitors from catalog search & detail endpoints
    scraper = OffertaScraper(max_workers=10)
    raw_records = scraper.scrape_all(use_cache=True)
    
    if not raw_records:
        logger.error("No exhibitor records retrieved! Aborting.")
        return

    logger.info(f"Retrieved {len(raw_records)} raw exhibitor profiles.")

    # 2. Enrich missing fields (Serper Google search fallback, full country name, clean domains)
    enricher = OffertaEnricher()
    enriched_records = enricher.enrich_records(raw_records)

    # 3. Build DataFrame
    df = pd.DataFrame(enriched_records)

    # Required column order matching workspace standard
    columns_order = [
        "exhibitor_name",
        "domain",
        "contact_number",
        "mail",
        "location",
        "country",
        "fair_hall",
        "fair_stand",
        "detail_url",
        "enrichment_source"
    ]

    # Ensure clean string formatting and empty string defaults
    for col in columns_order:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()
        else:
            df[col] = ""

    df_final = df[columns_order]

    # 4. Save to CSV and JSON
    df_final.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    logger.info(f"Exported clean CSV output to: {OUTPUT_CSV}")

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(df_final.to_dict(orient="records"), f, ensure_ascii=False, indent=2)
    logger.info(f"Exported structured JSON output to: {OUTPUT_JSON}")

    # 5. Print Summary Statistics
    total = len(df_final)
    name_count = (df_final["exhibitor_name"] != "").sum()
    domain_count = (df_final["domain"] != "").sum()
    phone_count = (df_final["contact_number"] != "").sum()
    mail_count = (df_final["mail"] != "").sum()
    loc_count = (df_final["location"] != "").sum()
    country_count = (df_final["country"] != "").sum()

    print("\n" + "=" * 62)
    print("             OFFERTA 2026 SCRAPING SUMMARY")
    print("=" * 62)
    print(f"Total Exhibitors Scraped:    {total}")
    print(f"Exhibitor Name Fill Rate:    {name_count}/{total} ({name_count/total*100:.1f}%)")
    print(f"Domain / Website Fill Rate:  {domain_count}/{total} ({domain_count/total*100:.1f}%)")
    print(f"Contact Number Fill Rate:    {phone_count}/{total} ({phone_count/total*100:.1f}%)")
    print(f"Email Address Fill Rate:     {mail_count}/{total} ({mail_count/total*100:.1f}%)")
    print(f"Location / Address Fill Rate:{loc_count}/{total} ({loc_count/total*100:.1f}%)")
    print(f"Country (Full Name) Rate:    {country_count}/{total} ({country_count/total*100:.1f}%)")
    print("=" * 62)
    print("Unique Countries in Dataset:")
    for country, count in df_final["country"].value_counts().items():
        print(f"  - {country}: {count}")
    print("=" * 62)
    print(f"Final CSV generated at:\n  {OUTPUT_CSV}\n")

if __name__ == "__main__":
    main()
