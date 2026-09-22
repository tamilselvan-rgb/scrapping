# Exhibitor Scraper

A production-ready, asynchronous Python web scraping tool designed to automatically extract exhibitor lists and details from a given event directory URL. The scraper is built with a hybrid design: first attempting fast HTTP/API request logic, and falling back to Playwright browser automation only when dynamic JS or user interaction is required.

## Project Structure

```text
exhibitor_scraper/
│
├── main.py                     # CLI entry point
├── requirements.txt            # Package dependencies
├── .env.example                # Sample environment config
├── README.md                   # Documentation
│
├── crawler/
│   ├── __init__.py
│   ├── page_detector.py        # Detects cards and DOM structures
│   ├── http_crawler.py         # Level 1: Static HTTP crawler (httpx)
│   ├── playwright_crawler.py   # Level 3: Browser automation (Playwright)
│   ├── pagination.py           # Handles limit/offset, next buttons, scroll
│   └── api_detector.py         # Level 2: API/XHR detection
│
├── extractors/
│   ├── __init__.py
│   ├── list_extractor.py       # Extracts exhibitor profiles from listing pages
│   └── profile_extractor.py    # Extracts structured information from detail pages
│
├── enrichment/
│   ├── __init__.py
│   ├── website_search.py       # Serper API website search
│   └── website_verifier.py     # Verifies candidate websites
│
├── utils/
│   ├── __init__.py
│   ├── url_utils.py            # Normalisation and absolute resolution
│   ├── text_utils.py           # Text cleaning and company suffix removal
│   ├── retry.py                # Exponential backoff and retry logic
│   ├── logger.py               # Informative terminal logging
│   └── checkpoint.py           # Resuming and checkpoint management
│
└── output/                     # Generated CSV files and checkpoints
```

## Installation

1. Ensure you have Python 3.11+ installed.
2. Clone or copy the repository to your workspace.
3. Install the required python packages:
   ```bash
   pip install -r requirements.txt
   ```

## Playwright Setup

Playwright requires system-level browser binaries to run. Install them using:
```bash
playwright install chromium
```

## Environment Variables

Copy `.env.example` to `.env`:
```bash
copy .env.example .env
```
Inside `.env`, define your Serper API key for website search/enrichment:
```env
SERPER_API_KEY=your_serper_api_key_here
```

## How to Run

Run the script by providing the exhibitor list URL:
```bash
python main.py "https://example.com/exhibitors"
```

### Options
* `--output <filename.csv>`: Custom output filename. By default, output is placed in `output/exhibitors_<domain>_<timestamp>.csv`.
* `--concurrency <num>`: Max concurrent HTTP profile scrapers (default: `10`).
* `--browser-concurrency <num>`: Max concurrent browser instances/pages (default: `3`).
* `--search-missing-websites`: Enable enrichment of missing websites via Serper API.
* `--resume`: Resume scraping from `output/checkpoint.json` if a previous run was interrupted.
* `--verbose`: Show detailed debug logs.

### Examples

```bash
# Simple scrape using defaults:
python main.py "https://example.com/exhibitors"

# Scrape and search for missing websites with custom concurrency:
python main.py "https://example.com/exhibitors" --search-missing-websites --concurrency 15

# Resume an interrupted scraping job:
python main.py "https://example.com/exhibitors" --resume
```

## CSV Format

The output CSV file contains the following columns:
* `company_name`
* `website`
* `website_source` (Values: `exhibitor_page`, `profile_page`, `web_search`, `not_found`)
* `website_confidence` (Values: `high`, `medium`, `low`, `none`)
* `website_verification_reason`
* `exhibitor_profile_url`
* `category`
* `industry`
* `description`
* `country`
* `city`
* `address`
* `email`
* `phone`
* `booth_number`
* `hall_number`
* `contact_person`
* `linkedin`
* `facebook`
* `instagram`
* `products`
* `brands`
* `source_page`
* `scraped_at`

## Website-Search Setup & Verification

When `--search-missing-websites` is active:
1. If the exhibitor page or profile page does not contain a website, the script executes a search query via **Serper API**.
2. Queries are constructed using:
   - `"<company name>" official website`
   - `"<company name>" company`
   - etc.
3. Candidate results are filtered to exclude business directories, events, and social sites (e.g. `linkedin.com`, `facebook.com`, `crunchbase.com`).
4. Candidate sites are verified in `enrichment/website_verifier.py` check criteria:
   - Similarity of domain to company name.
   - Company name inclusion in homepage title/meta description.
   - Text match on title/meta.
5. The result is saved with confidence scores and source attributes.

## Resume/Checkpoint Behavior

* During scraping, intermediate results are periodically flushed to the output CSV.
* Checkpoints are written to `output/checkpoint.json`. It tracks:
  - Discovered profile URLs.
  - Successfully scraped profile URLs.
  - Basic list metrics.
* Running with `--resume` reads `output/checkpoint.json`, matches the target URL, and skips already scraped URLs.

## Known Limitations

1. **Anti-Bot Protection**: Highly protected sites (e.g. Cloudflare, datadome) may block headless playwright browsers. Running in headful mode or configuring proxy headers can mitigate this, but bypasses are not built-in.
2. **Dynamic DOM structures**: Heuristics are used to detect listings, but highly complex, nested, or obscure SPA frameworks might require custom adapters.

## How to Add a Site-Specific Adapter

The architecture supports pluggable adapters to bypass the generic heuristics for specific directories.
Create a new adapter module in `extractors/adapters/` (or specify custom selectors in `extractors/list_extractor.py` and `extractors/profile_extractor.py`) matching the target domain.

For instance, in `extractors/list_extractor.py`, detect the domain and use custom parser functions:
```python
def parse_my_specific_site(html_content: str):
    # custom selector logic
    return [url1, url2]
```
This keeps the application extensible without changing the main crawler/enrichment pipelines.
