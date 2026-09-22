# LOUPE India Exhibitor Scraper

High-fidelity scraper and enrichment pipeline for the [LOUPE India 2026 Exhibitor Directory](https://www.loupe-india.com/exhibitor-list-visitor).

## Features
- **Directory Crawler**: Crawls all 10 paginated pages to extract 203 exhibitors with their company names, stands/booths, country flag codes, portal website links, and product categories.
- **Serper Google Search Integration**: Fallback search via `https://google.serper.dev/search` using credentials in `d:\habsy\scrapping\.env` to discover missing company domains, contact numbers, email addresses, and physical locations.
- **Website Contact Crawler**: Traverses company homepages and `/contact` pages for emails, telephone numbers, and addresses.
- **Country Normalization**: Normalizes all country codes to **Full English Country Names** (e.g. `India`, `United States`, `France`, `Germany`, etc. — **never shortcodes**).
- **Standards-Compliant Exports**: Produces Excel-friendly UTF-8 with BOM CSV (`utf-8-sig`) and JSON datasets.

## Output Schema
1. `exhibitor_name`: Full legal company / brand name
2. `domain`: Cleaned official root domain (`example.com`)
3. `contact_number`: Contact telephone / phone / mobile number
4. `mail`: Contact email address
5. `location`: Street address, city, state, or country
6. `country`: Full English country name
7. `fair_stand`: Stand / booth identifier
8. `enrichment_source`: Source of data (`portal_direct`, `serper_search`, `portal_catalog`)

## Execution
```bash
pip install -r requirements.txt
python main.py
```
