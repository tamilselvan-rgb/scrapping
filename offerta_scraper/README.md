# Offerta 2026 Exhibitor Scraper

A specialized web scraper and data enrichment tool designed to extract the complete exhibitor catalog from the [Offerta 2026 Exhibitor Directory](https://www.offerta.de/offerta-live/ausstellendenverzeichnis/).

## Output Files

- `offerta_exhibitors.csv`: Clean CSV file containing all 333 exhibitors with contact, domain, and full location details. Encoded in `utf-8-sig`.
- `offerta_exhibitors.json`: Structured JSON representation of the final dataset.
- `raw_cache.json`: Local cache of raw exhibitor API responses for instant replay and fault tolerance.

## Dataset Fields

| Column | Description |
| :--- | :--- |
| `exhibitor_name` | Corporate or brand name of the exhibiting company |
| `domain` | Official root website domain (e.g. `example.com`, lowercase, no protocol/path) |
| `contact_number` | Telephone / mobile number |
| `mail` | Contact email address |
| `location` | Physical street address, postal code, and city |
| `country` | **Full English country name** (e.g. `Germany`, `Austria`, `Switzerland`, `France`, `Italy`, `Belgium`, `Netherlands`) |
| `fair_hall` | Exhibition hall/pavilion |
| `fair_stand` | Booth/stand identifier |
| `detail_url` | Direct URL to the exhibitor profile on Offerta |
| `enrichment_source` | Provenance of the domain/contact (`detail_api`, `corporate_email`, `curated_brand_domain`, `serper_search`) |

## Data Completeness (333 Exhibitors)

- **Exhibitor Name**: 333 / 333 (100.0%)
- **Domain / Website**: 322 / 333 (96.7%)
- **Email Address**: 326 / 333 (97.9%)
- **Physical Address**: 333 / 333 (100.0%)
- **Country (Full Name)**: 333 / 333 (100.0%)
- **Phone Number**: 284 / 333 (85.3%)

## How to Run

1. Ensure requirements are installed:
   ```bash
   pip install -r requirements.txt
   ```
2. Execute the pipeline:
   ```bash
   python main.py
   ```
