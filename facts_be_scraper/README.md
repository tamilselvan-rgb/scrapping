# FACTS Belgium Exhibitor Scraper

High-fidelity scraper and enrichment pipeline for the [FACTS Belgium 2026 Exhibitor Directory](https://www.facts.be/en/exhibitors/).

## Features
- **Comprehensive Profile Scraping**: Traverses all 28 directory pages and individual profile URLs (`https://www.facts.be/en/exhibitors/{slug}/`) to scrape company names, stands/booths, physical addresses, website links, and social channels.
- **Serper Google Search Integration**: Fallback search via `https://google.serper.dev/search` using API key from `d:\habsy\scrapping\.env` to discover missing domains, contact numbers, email addresses, and physical locations.
- **Website Contact Crawler**: Crawls company homepages and contact pages for official corporate emails and telephone numbers.
- **Strict Country Normalization**: Standardizes all country names to **Full English Country Names** (e.g. `Belgium`, `Netherlands`, `France`, `Germany`, `United Kingdom`, etc. — **never shortcodes**).
- **Standards-Compliant Exports**: Produces Excel-friendly UTF-8 with BOM CSV (`utf-8-sig`) and JSON datasets.

## Output Schema
1. `exhibitor_name`: Full legal company / exhibitor name
2. `domain`: Official root domain (`example.com`)
3. `contact_number`: Contact telephone / phone number
4. `mail`: Contact email address
5. `location`: Physical address (street, postal code, city, country)
6. `country`: Full English country name
7. `fair_stand`: Stand / booth identifier
8. `detail_url`: Profile URL on FACTS portal
9. `enrichment_source`: Source of data (`profile_direct`, `serper_search`, `profile_catalog`)

## Execution
```bash
pip install -r requirements.txt
python main.py
```
