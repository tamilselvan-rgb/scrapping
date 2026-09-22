import os
import sys
import json
import logging
import pandas as pd

# Reconfigure stdout for utf-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from scraper import InterpomaScraper
from enricher import ExhibitorEnricher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("interpoma_main")

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "interpoma_exhibitors.csv")
OUTPUT_JSON = os.path.join(OUTPUT_DIR, "interpoma_exhibitors.json")

def main():
    logger.info("=== Starting Interpoma Exhibitor Scraping & Enrichment Pipeline ===")
    
    # 1. Scrape all exhibitors from listing & individual detail pages
    scraper = InterpomaScraper(max_workers=15)
    records = scraper.scrape_all()
    
    if not records:
        logger.error("No records found! Terminating.")
        return

    logger.info(f"Scraped raw data for {len(records)} exhibitors.")

    # 2. Enrich missing fields (addresses, domains, contacts)
    enricher = ExhibitorEnricher()
    enriched_records = enricher.enrich_records(records)

    # 3. Format into DataFrame
    df = pd.DataFrame(enriched_records)

    # Clean and order requested columns
    columns_order = [
        "exhibitor_name",
        "domain",
        "number",
        "mail",
        "address",
        "fair_hall",
        "fair_stand",
        "country",
        "detail_url",
        "enrichment_source"
    ]

    COUNTRY_MAP = {
        "IT": "Italy", "DE": "Germany", "FR": "France", "NL": "Netherlands",
        "ES": "Spain", "BE": "Belgium", "AT": "Austria", "CH": "Switzerland",
        "GB": "United Kingdom", "UK": "United Kingdom", "US": "United States",
        "CA": "Canada", "CN": "China", "DK": "Denmark", "PL": "Poland",
        "SK": "Slovakia", "SI": "Slovenia", "CZ": "Czech Republic", "GR": "Greece",
        "PT": "Portugal", "SE": "Sweden", "NO": "Norway", "FI": "Finland",
        "TR": "Turkey", "IL": "Israel", "IN": "India", "BR": "Brazil",
        "AU": "Australia", "NZ": "New Zealand", "JP": "Japan", "KR": "South Korea"
    }

    # Fill NaN with empty string
    for col in columns_order:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()
        else:
            df[col] = ""

    # Normalize country to full name
    df["country"] = df["country"].apply(lambda c: COUNTRY_MAP.get(c.upper(), c) if c else "")

    df_final = df[columns_order]

    # 4. Save to CSV and JSON
    df_final.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    logger.info(f"Saved clean CSV output to: {OUTPUT_CSV}")

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(df_final.to_dict(orient="records"), f, ensure_ascii=False, indent=2)
    logger.info(f"Saved structured JSON output to: {OUTPUT_JSON}")

    # 5. Print Summary Statistics
    total_count = len(df_final)
    name_count = (df_final["exhibitor_name"] != "").sum()
    domain_count = (df_final["domain"] != "").sum()
    number_count = (df_final["number"] != "").sum()
    mail_count = (df_final["mail"] != "").sum()
    address_count = (df_final["address"] != "").sum()

    print("\n" + "=" * 60)
    print("           INTERPOMA 2026 SCRAPING SUMMARY")
    print("=" * 60)
    print(f"Total Exhibitors Scraped:  {total_count}")
    print(f"Exhibitor Name Fill Rate:  {name_count}/{total_count} ({name_count/total_count*100:.1f}%)")
    print(f"Domain / Website Fill Rate:{domain_count}/{total_count} ({domain_count/total_count*100:.1f}%)")
    print(f"Phone Number Fill Rate:    {number_count}/{total_count} ({number_count/total_count*100:.1f}%)")
    print(f"Email Address Fill Rate:   {mail_count}/{total_count} ({mail_count/total_count*100:.1f}%)")
    print(f"Address Fill Rate:         {address_count}/{total_count} ({address_count/total_count*100:.1f}%)")
    print("=" * 60)
    print(f"Final CSV file generated at:\n  {OUTPUT_CSV}\n")

if __name__ == "__main__":
    main()
