# CONGRÈS PETITE ENFANCE - CLERMONT-FERRAND 2026 Scraper

This directory contains the isolated scraper and output data for exhibitors participating in **CONGRÈS PETITE ENFANCE - CLERMONT-FERRAND 2026**.

## Overview

- **Event Name**: CONGRÈS PETITE ENFANCE - CLERMONT-FERRAND 2026
- **Source Exhibitor URL**: https://clermontferrand.petitenfance.net/les-exposants/
- **Scraping Method**: HTML Scraping (`requests` + `BeautifulSoup`) with official website profile enrichment

## Important Selectors & Architecture

- **Main Listing Container**:
  - Main exhibitor section identified by `<h1>Liste des exposants</h1>`.
  - Exhibitor cards targeted via `div.exposant_item` under `.wpb_wrapper`.
  - Exclusion of non-exhibitor content (navigation menus, sponsors, partners, footer links).
- **Extracted Fields**:
  - `exhibitor_name`: Located within `.titre_exposant strong`.
  - Activity baseline: Located within `.baseline_exposant`.
  - `domain`: Official company website extracted from `.site_exposant a[href]` and normalized to root domain.
  - Profile enrichment: Traverses official website (`/`, `/contact`, `/mentions-legales`) to extract phone, email, and physical address.
  - `location`: Clean city and country format (`<City>, France`).

## Installation

Ensure Python 3.9+ is installed, then install the dependencies:

```bash
pip install -r requirements.txt
```

## Running the Scraper

Execute the scraper script from within this directory:

```bash
python scraper.py
```

## Output Format

Outputs are saved in the `output/` directory:

1. `output/exhibitors.csv` (UTF-8 with BOM encoding for Excel compatibility)
2. `output/exhibitors.json` (Formatted JSON array)

### Standard Column Structure

| Column Name | Description | Example |
| :--- | :--- | :--- |
| `exhibitor_name` | Official company name | `WESCO` |
| `domain` | Clean root domain (no http/https/www) | `wesco.fr` |
| `contact` | Structured contact information (`email \| phone`) | `webmaster@wesco.fr \| +33 5 49 80 01 66` |
| `address` | Full physical address | `Route de Cholet, 79140 Cerizay, France` |
| `location` | City and country | `Cerizay, France` |

## Known Limitations

- Some company domains use Cloudflare bot protection on subpages; these are enriched via standardized legal entity fallback records.
- Exhibitor `MATHOU ET LOXOS` did not have an external hyperlink directly on the event card and is resolved to `mathou.com`.
