# NICE Nusantara Convex Event Scraper

A specialized web scraper that extracts event information across all 3 pages of the [Nusantara International Convention Exhibition (NICE)](https://nice-nusantaraconvex.com/events).

## Features
- Scrapes all 3 pages from `https://nice-nusantaraconvex.com/events?page=1..3`
- Navigates into each event's detail page to extract official website links, hall assignments, calendar dates, and social links
- Standardizes start dates and end dates in ISO format (`YYYY-MM-DD`)
- Normalizes website domains (e.g., `trainers-asia.portal-pokemon.com`, `interzum-jakarta.com`)
- Enriches location information (Venue, City, and Country) based on NICE PIK 2 venue details (`Tangerang`, `Indonesia`)
- Produces clean CSV exports

## Output Files
- **`output/nice_events.csv`**: Contains the exact requested columns:
  - `s_no`
  - `event_name`
  - `domain`
  - `start_date`
  - `end_date`
  - `venue`
  - `city`
  - `country`
- **`output/nice_events_detailed.csv`**: Comprehensive report including `website_url`, `hall`, `instagram_url`, and `event_page_url`.

## Usage
```bash
python scraper.py
```
