# Ecomondo Exhibitor Scraper

This directory contains the isolated scraper and output datasets for exhibitors at **Ecomondo** (The Green Technology Expo).

## Overview

- **Event Name**: Ecomondo
- **Source Exhibitor URL**: https://www.ecomondo.com/it/catalogo/espositori
- **Scraping Method**: Direct JSON API Endpoint + Multi-Threaded Profile Enrichment

## Important Endpoints & Selectors

- **Direct API Endpoint**:
  - `POST https://www.ecomondo.com/it/api/v1/filterDataObjects`
  - Payload parameters:
    - `folder`: `"7435571"`
    - `type`: `"digital-profiles"`
    - `exhibitionEdition`: `"7306136"`
    - `itemsPerPage`: `"2000"`
    - `page`: `1`
- **Exhibitor Profile URL**:
  - Extracted from `a.btn[href]` on each exhibitor card: `https://www.ecomondo.com/it/dettaglio-profilo/<company_slug>?digitalProfileId=<id>`
- **Extracted Profile Fields**:
  - `exhibitor_name`: Located in `h1` and `.card-digitalprofile-name`.
  - `domain`: Official company website located in the `website` container, normalized to root domain.
  - `address`: Registered corporate address located in the `Riferimenti` container.
  - `contact`: Structured contact string (`email | phone`) extracted from `Riferimenti` and `mailto:` / `tel:` tags.
  - `location`: Standardized `<City>, <Country>` format using full English country names (e.g. `Roma, Italy`, `Milano, Italy`).

## Installation

Ensure Python 3.9+ is installed:

```bash
pip install -r requirements.txt
```

## Running the Scraper

Run the scraper script directly from within this directory:

```bash
python scraper.py
```

## Output Format

The output files are generated inside `output/`:

1. `output/exhibitors.csv` (UTF-8 with BOM encoding for Excel compatibility)
2. `output/exhibitors.json` (Structured JSON array)

### Standard Column Structure

| Column Name | Description | Example |
| :--- | :--- | :--- |
| `exhibitor_name` | Official company name | `FOR REC S.P.A.` |
| `domain` | Clean root domain (no http/https/www) | `forrec.eu` |
| `contact` | Structured contact (`email \| phone`) | `info@forrec.it \| +39 0490990015` |
| `address` | Full physical registered address | `Viale dell'Artigianato 24, 35010 Santa Giustina in Colle , PD - Italia` |
| `location` | Clean city and full country name | `Santa Giustina In Colle, Italy` |

## Known Limitations

- Exhibitor profiles without published websites or contact details on the portal are retained with clean blank strings per project rules.
- Rate limiting is handled respectfully via an 8-worker thread pool.
