# Athens Bar Show Exhibitor Scraper

A Python scraper for extracting exhibitor records from the [Athens Bar Show](https://www.athensbarshow.gr/exhibitors) directory.

## Features
- Scrapes the official directory `https://www.athensbarshow.gr/exhibitors` using essential browser headers.
- Extracts exhibitor names and converts relative paths to full profile URLs.
- Visits each profile page with polite request delays and error handling.
- Extracts stand number, company website/domain, emails, phones, physical addresses, and full English country names.
- Deduplicates exhibitors and handles missing fields gracefully.
- Exports to CSV (with `utf-8-sig` encoding) and formatted Excel workbook (`.xlsx`).

## Directory Contents
- `scraper.py`: Main executable scraper script.
- `athens_bar_show_exhibitors.csv`: CSV export with `utf-8-sig` encoding.
- `athens_bar_show_exhibitors.xlsx`: Formatted Excel workbook.
- `athens_bar_show_exhibitors.json`: JSON export.
- `requirements.txt`: Python package requirements (`requests`, `beautifulsoup4`, `openpyxl`).

## Usage
To run the scraper:
```bash
python scraper.py
```
