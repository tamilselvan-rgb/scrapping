# Vendelux Event Scraper (November 2026)

High-performance, asynchronous web scraper built to extract B2B event data from Vendelux for **November 2026** upcoming events.

## Output Schema

The output CSV file matches the exact requested schema:

| Column | Description | Example |
| :--- | :--- | :--- |
| `event_name` | Name of the event / trade show | `APHA Annual Meeting and Expo 2026` |
| `event_start_date` | Event start date (`YYYY-MM-DD`) | `2026-11-01` |
| `event_end_` | Event end date (`YYYY-MM-DD`) | `2026-11-04` |
| `venue` | Convention center / facility name | `Henry B. González Convention Center` |
| `city` | Host city | `San Antonio` |
| `country` | Host country | `United States` |
| `event_domain` | Official website root domain | `apha.org` |

---

## How It Works

1. **Bypasses Cloudflare**: Uses `curl_cffi` with Chrome 120 TLS fingerprint impersonation.
2. **Multi-Hop Traversal**:
   - **Hop 1**: Scrapes the [Vendelux November 2026](https://vendelux.com/b2b-events/november-2026) directory for all events listed under *"Upcoming events"*.
   - **Hop 2**: Traverses into each event's attendee list page to discover its *"View event insights"* link.
   - **Hop 3**: Visits the app event page and extracts `application/ld+json` event metadata (dates, venue, address, and official website URL).
   - **Domain Extraction**: Normalizes and cleans the official event URL to its root domain (`event_domain`).
3. **Resumable & Fault-Tolerant**: Writes rows incrementally to CSV with async locks. If re-run, it automatically skips already scraped events.

---

## How to Run

### 1. Install Requirements
```bash
pip install -r requirements.txt
```

### 2. Run the Scraper
```bash
python scrape.py
```

### Options:
* `--output <path>`: Custom output CSV file path (default: `output/vendelux_november_2026_events.csv`).
* `--concurrency <num>`: Number of concurrent HTTP requests (default: `6`).
* `--limit <num>`: Limit number of events to scrape (e.g. `--limit 20`). Default is `0` (all 390 events).

---

## Output File

All results are saved to:
`output/vendelux_november_2026_events.csv`
