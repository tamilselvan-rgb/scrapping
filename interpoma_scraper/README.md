# Interpoma 2026 Exhibitor Scraper

A robust web scraper and data enrichment tool designed to scrape the complete exhibitor catalog from [Fiera Bolzano Interpoma](https://www.fierabolzano.it/en/interpoma/exhibitor-list).

## Output Files

- `interpoma_exhibitors.csv`: The main CSV output containing all 332 exhibitors with contact and address details.
- `interpoma_exhibitors.json`: Full JSON representation of the final dataset.
- `raw_cache.json`: Local cache of raw exhibitor detail pages for instant replay and resilience against network drops.

## Dataset Fields

| Column | Description |
| :--- | :--- |
| `exhibitor_name` | Official trade name of the exhibitor or exhibiting brand |
| `domain` | Cleaned domain of the exhibitor's website |
| `number` | Contact telephone number |
| `mail` | Contact email address |
| `address` | Full physical address (street, city, province/state, country) |
| `fair_hall` | Trade show exhibition hall |
| `fair_stand` | Booth / stand number |
| `country` | Country code |
| `detail_url` | Direct URL to the exhibitor's profile on Fiera Bolzano |
| `enrichment_source` | Source of information (`detail_page`, `parent_exhibitor`, `website_footer`, `brand_directory`, `email_domain`) |

## Data Completeness (332 Exhibitors)

- **Exhibitor Name**: 332 / 332 (100.0%)
- **Domain / Website**: 332 / 332 (100.0%)
- **Email Address**: 332 / 332 (100.0%)
- **Address**: 332 / 332 (100.0%)
- **Phone Number**: 316 / 332 (95.2%)

## How to Run

1. Ensure requirements are installed:
   ```bash
   pip install -r requirements.txt
   ```
2. Execute the pipeline:
   ```bash
   python main.py
   ```
