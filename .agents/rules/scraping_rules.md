Web Scraping Extraction Rules
When scraping a company or exhibitor directory, use the official 2026 event
listing, visit every linked exhibitor profile, and extract the following fields:

name: Company or exhibiting brand name
booth_no: Booth, stand, hall, or exhibition-space number
desc: Full company or exhibitor description
email: Contact email address
phone: Telephone or mobile number, including country or area code
domain: Official company website root domain
address: Street or full physical address
city: City name
country: Full English country name, never a shortcode
linkedin_url: Direct LinkedIn company or profile URL

The `booth_no` field is required whenever the event listing, exhibitor profile,
floor plan, or structured data provides a booth or stand number. Preserve the
complete reference, including hall information when shown, such as
`Hall 25 / 25G19`. If no booth number is published, leave `booth_no` blank and
never invent a value. Do not mistake event dates, postal codes, registration
numbers, or company IDs for booth numbers.

For compatibility with existing exports, `exhibitor_name`, `mail`, and
`contact_number` may be included as aliases for `name`, `email`, and `phone`.
Output File Naming Rules
For CSV exports, use the event name followed by exhibitors:
{EVENT_NAME}_exhibitors.csv (e.g. MECSPE_BARI_2026_exhibitors.csv)
For JSON exports, match the same naming:
{EVENT_NAME}_exhibitors.json (e.g. MECSPE_BARI_2026_exhibitors.json)
Missing Company Details (Required Rule)
Only scrape 2026 event data. Use the official 2026 exhibitor list / directory URL for the event. Do not mix in 2025 or older exhibitor pages.
When exhibitor profile details are not present on the event site (for example:
domain, desc, email, phone, address, city, country, booth_no, or linkedin_url),
enrich missing fields after scraping. Only use a booth number when it is
published by a reliable event source.
Domain fallback: if domain is missing, use SERPER_API_KEY from the project root .env file and query Serper (https://google.serper.dev/search) with the company name plus the event year (2026) to find the official website.
Prefer the company’s own website over directories, marketplaces, and social profiles.
If Serper returns a useful snippet or LinkedIn company page, fill desc and linkedin_url only when those fields are still empty.
Never write the API key into CSV/JSON output files.
## Language (Required Rule)
- **Export all text fields in English** in both CSV and JSON output files.
- Fields that must be in English: `name`, `desc`, `address`, and `city`.
- If the event site already provides English text, use that English version directly.
- If scraped text is in another language, **translate it to English** before writing the CSV/JSON.
- Do not translate identifiers or structured values: keep `email`, `phone`, `domain`, and `linkedin_url` unchanged.
- Preserve company legal names only when an official English brand/name exists on the source; otherwise translate the displayed exhibitor name to clear English.

## Output column order

Use this standard leading column order in CSV and JSON records:

`exhibitor_name, domain, contact_number, mail, location, country, booth_no, ...`

CSV files must use `utf-8-sig` encoding so accented characters display correctly
in spreadsheet applications.