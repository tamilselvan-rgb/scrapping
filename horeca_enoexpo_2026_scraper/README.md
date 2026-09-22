# HORECA/ENOEXPO 2026 Exhibitor Scraper

High-performance, isolated web scraper designed to extract clean exhibitor data from the official **HORECA/ENOEXPO 2026** exhibitor directory hosted on ExpoSupport (`horeca.exposupport.pl`).

---

## Event Details

- **Event Name**: HORECA/ENOEXPO 2026
- **Source Exhibitor URL**: `https://horeca.exposupport.pl/en-us/wystawcy-th`
- **Scraping Method**: API + HTML (Internal ASP.NET ASMX JSON endpoint + Profile Scraping & Website Probing)

---

## Architecture & Implementation

1. **Catalog Discovery (Direct JSON API)**:
   - Initial GET request establishes session cookies (`ASP.NET_SessionId`) and reads the `#hfParams` hidden parameter field.
   - Dispatches a POST request to `/Ajax/ajsel.asmx/LoadData2` retrieving the full 55 exhibitor catalog in structured JSON.
   - Extracts exhibitor metadata including `_ZAKEY`, `_FIKEY`, `NAZWA`, `MIASTO`, `KRAJ`, `HALA`, `NR_STOISKA`.

2. **Profile Extraction & Enrichment**:
   - Concurrently visits each exhibitor info URL (`https://horeca.exposupport.pl/en-us/exhibitor-info/{_ZAKEY}`).
   - Extracts:
     - Company Name from `<h3>` or `NAZWA`
     - Full registered address from `.ex-preview-card-address div`
     - Phone numbers via `.fa-phone`
     - Direct emails via `mailto:` links
     - Official company website via `.fa-globe` link -> cleaned to root domain (e.g. `sovrana,pl` -> `sovrana.pl`)
     - Normalized clean location `<City>, <Country>` with full English country names (e.g., `Poland` not `PL`, `United Kingdom` not `UK`).
   - For companies with missing contact information, probes the company's official website (`/`, `/kontakt`, `/contact`).
   - Fallback to Serper Google Search for missing domain/contact details.

3. **Deduplication & Quality Assurance**:
   - Deduplicates across clean domain, profile URL, and normalized company name.
   - Missing fields are stored as empty strings `""`, never `"N/A"`.
   - Exports CSV (`utf-8-sig` with BOM for Excel compatibility) and formatted JSON.

---

## Key Selectors & Endpoints

| Component | Target / Selector |
| :--- | :--- |
| **Catalog Page** | `https://horeca.exposupport.pl/en-us/wystawcy-th` |
| **API Endpoint** | `POST https://horeca.exposupport.pl/Ajax/ajsel.asmx/LoadData2` |
| **Profile URL** | `https://horeca.exposupport.pl/en-us/exhibitor-info/{_ZAKEY}` |
| **Address** | `.ex-preview-card-address div` |
| **Phone** | Text immediately following `.fa-phone` |
| **Email** | `.ex-preview-card-contact a[href^="mailto:"]` |
| **Website** | `.ex-preview-card-contact a[href]` containing `.fa-globe` |

---

## Output Fields

Every row contains these core fields:

| Field | Description | Example |
| :--- | :--- | :--- |
| `exhibitor_name` | Official company name | `SOVRANA POLSKA SP. Z O.O.` |
| `domain` | Clean root domain (lowercase, no protocol/www) | `sovrana.pl` |
| `contact` | Formatted contact email and phone (`email \| phone`) | `office@sovrana.com.pl \| 32 6450016` |
| `address` | Full registered street, postal code, city, country | `PRZEMYSŁOWA 3, 32-300 OLKUSZ, Poland` |
| `location` | Clean city and full country name | `Olkusz, Poland` |

---

## Output Deliverables

Generated inside `output/`:

- `output/exhibitors.csv` (UTF-8 with BOM for Excel compatibility)
- `output/exhibitors.json` (Structured JSON array)

---

## Installation & Setup

```bash
# Navigate to scraper directory
cd "d:\habsy\scrapping\horeca_enoexpo_2026_scraper"

# Install dependencies
pip install -r requirements.txt
```

---

## Running the Scraper

```bash
python scraper.py
```
