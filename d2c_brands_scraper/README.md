# D2C Stories Brand Scraper

Scrapes every company from the public D2C Stories brand directory:

https://d2cstories.com/d2c-brands/list

The live listing is JavaScript-rendered and currently shows **16 brands per page** (about **12 pages**). This script uses the same public API the website uses, walks every list page, then opens each brand profile to collect:

- company name
- official domain URL

## Output

| File | Description |
| --- | --- |
| `output/d2c_brands.csv` | One row per company |
| `output/d2c_brands.json` | Same data plus scrape metadata |

CSV / JSON fields:

- `company_name`
- `domain_url` — official website, normalized to `https://example.com`
- `domain` — hostname without `www`
- `profile_url` — D2C Stories brand page
- `category`
- `city`
- `source_page` — list page the brand was discovered on

## Install

```bash
cd d2c_brands_scraper
python -m pip install -r requirements.txt
```

## Run

```bash
python scrape.py
```

Optional:

```bash
python scrape.py --limit 16 --concurrency 8
```

`--limit 16` matches the website’s 12-page listing. The scraper still follows the API’s `totalPages` / empty-page stop conditions, so it will not loop forever if the site grows or shrinks.
