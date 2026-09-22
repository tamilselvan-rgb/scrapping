# DATA CENTRE WORLD EUROPE - MADRID 2026 Exhibitor Scraper

High-performance, isolated web scraper designed to extract clean exhibitor data from the official **DATA CENTRE WORLD EUROPE - MADRID 2026** exhibitor directory hosted on Tech Show Madrid (`techshowmadrid.es`).

---

## Event Details

- **Event Name**: DATA CENTRE WORLD EUROPE - MADRID 2026
- **Source Exhibitor URL**: `https://www.techshowmadrid.es/expositores?filters.events=Data%20Centre%20World`
- **Scraping Method**: HTML Document & Profile Scraping (`requests` + `BeautifulSoup`)

---

## Architecture & Implementation

1. **Exhibitor Discovery**:
   - Queries the official exhibitor directory filtered specifically for Data Centre World Europe.
   - Extracts all exhibitor cards matching `.m-exhibitors-list__items__item`.
   - Resolves profile modal slugs from `data-href` (e.g. `javascript:openRemoteModal('exhibitors/22-vatios-sl', ...)`).

2. **Profile Extraction & Enrichment**:
   - Direct HTTP requests to profile endpoints (`https://www.techshowmadrid.es/exhibitors/{slug}`).
   - Extracts verified company details:
     - Official company website / domain
     - Stand location (e.g., `Stand: 5G68`)
     - Complete registered address lines
     - Country (normalized to full English name e.g. `Spain`, `United Kingdom`, `China`, `Germany`, etc.)
     - Clean location: `<City>, <Country>`
   - Probes company's official website contact pages (`/`, `/contacto`, `/contact`, `/aviso-legal`) for contact email and telephone.
   - Fallback to Serper Google Search for missing domain, address, or phone.

3. **Deduplication & Formatting**:
   - Deduplicates records across domain, profile URL, and normalized company name.
   - Retains the most complete entry.
   - Exports CSV (`utf-8-sig`) and JSON.

---

## Key Selectors & Endpoints

| Item | Selector / Target |
| :--- | :--- |
| **Exhibitor Directory** | `https://www.techshowmadrid.es/expositores?filters.events=Data%20Centre%20World` |
| **Exhibitor Card** | `.m-exhibitors-list__items__item` |
| **Company Name** | `.m-exhibitors-list__items__item h2` / `.m-exhibitor-entry__item__header__title` |
| **Profile Path** | `data-href` regex `openRemoteModal\('([^']+)'` |
| **Profile Endpoint** | `https://www.techshowmadrid.es/exhibitors/{slug}` |
| **Website** | `.m-exhibitor-entry__item__body__contacts__additional__website a[href]` |
| **Address** | `.m-exhibitor-entry__item__body__contacts__address` |
| **Stand** | `.m-exhibitor-entry__item__header__stand` |

---

## Output Fields

Every row contains these core fields:

| Field | Description | Example |
| :--- | :--- | :--- |
| `exhibitor_name` | Official company name | `22 VATIOS SL` |
| `domain` | Clean root domain (lowercase, no protocol/www) | `22vatios.com` |
| `contact` | Formatted contact email and phone (`email \| phone`) | `info@22vatios.com \| +34912620457` |
| `address` | Full registered street, postal code, city, country | `Avenida de los Pirineos 9, San Sebastián de los Reyes, M, 28703, Spain` |
| `location` | Clean city and full country name | `San Sebastián de los Reyes, Spain` |

---

## Output Deliverables

The scraper generates files in `output/` and the root folder:

- `output/exhibitors.csv` (UTF-8 with BOM for Excel compatibility)
- `output/exhibitors.json` (Structured JSON array)
- `output/DATA CENTRE WORLD EUROPE .csv` (Requested file name)
- `DATA CENTRE WORLD EUROPE .csv` (Root directory copy)

---

## Installation & Setup

```bash
# Navigate to scraper directory
cd "d:\habsy\scrapping\data_centre_world_europe_scraper"

# Install dependencies
pip install -r requirements.txt
```

---

## Running the Scraper

```bash
python scraper.py
```

---

## Known Limitations

- Exhibitor profiles on Tech Show Madrid use an embedded contact form (`rapportForm`) rather than publicizing raw emails directly in the HTML. The scraper enriches contact details by inspecting the company's official website and using Serper fallback.
- Website availability depends on each company's server responsiveness; timeouts and request errors on third-party websites are gracefully ignored to prevent stalls.
