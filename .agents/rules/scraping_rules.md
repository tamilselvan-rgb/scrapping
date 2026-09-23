# Web Scraping Extraction Rules

Whenever scraping company / exhibitor directories, ALWAYS extract and include the following required fields using **exactly** these column names:

| Column Name | Description |
|---|---|
| `company_name` | Official Company Name |
| `booth` | Booth / stand details for the exhibitor at the event (e.g. `Hall 7, Stand 159`). If multiple booths are listed, join them with `; `. |
| `description` | Full Company Description in English |
| `email` | Contact Email Address |
| `mobile_primary` | Primary Telephone / Phone Number (with country code) |
| `domain` | Company Official Website / Domain URL |
| `full_address` | Full Street / Physical Address including postal code and country |
| `city` | City Name |
| `linkedin_url` | Direct LinkedIn Company / Profile URL |

## Export Schema Restriction
Every CSV and JSON exhibitor export must contain exactly these nine columns and no event metadata or scraper-specific columns:

`company_name, booth, description, email, mobile_primary, domain, full_address, city, linkedin_url`

Use the same order in CSV headers and JSON object keys. Existing aliases such as `exhibitor_name`, `desc`, `booth_no`, `mail`, `contact_number`, `phone`, `address`, and `location` must be mapped to the canonical names above before export.

> [!IMPORTANT]
> These are the **canonical column names** to use in ALL CSV and JSON exports. Do NOT use old names such as `name`, `desc`, `boothname`, `phone`, `address`, or `exhibitor_name`. Always use the exact names in the table above.

---

## Output File Naming Rules
- For CSV exports, use the event name followed by exhibitors:
  - `{EVENT_NAME}_exhibitors.csv` (e.g. `MECSPE_BARI_2026_exhibitors.csv`)
- For JSON exports, match the same naming:
  - `{EVENT_NAME}_exhibitors.json` (e.g. `MECSPE_BARI_2026_exhibitors.json`)

---

## Booth Details (Required Rule)
- **Always scrape booth/stand information when the event site provides it.**
- Fill `booth` from hall, stand, pavilion, or special-area labels shown on the exhibitor card or detail overlay.
- Prefer the main booth (`booth_is_main`, primary stand, or equivalent) when the site distinguishes main vs. co-exhibitor stands.
- If multiple booths are shown, include all of them in `booth`, separated by `; `.
- Leave `booth` empty only when the event site truly has no booth/stand data for that exhibitor.

---

## Missing Company Details (Required Rule)
- **Only scrape 2026 event data.** Use the official 2026 exhibitor list / directory URL for the event. Do not mix in 2025 or older exhibitor pages.
- When exhibitor profile details are **not present on the event site** (for example: `domain`, `description`, `email`, `mobile_primary`, `full_address`, `city`, `linkedin_url`), enrich missing fields after scraping.
- **Domain fallback:** if `domain` is missing, use `SERPER_API_KEY` from the project root `.env` file and query Serper (`https://google.serper.dev/search`) with the company name plus the event year (`2026`) to find the official website.
- Prefer the company's own website over directories, marketplaces, and social profiles.
- If Serper returns a useful snippet or LinkedIn company page, fill `description` and `linkedin_url` only when those fields are still empty.
- Never write the API key into CSV/JSON output files.

---

## Language (Required Rule)
- **Export all text fields in English** in both CSV and JSON output files.
- Fields that must be in English: `company_name`, `description`, `full_address`, `city`, and `booth` (translate hall/area labels only when needed; keep stand numbers unchanged).
- If the event site already provides English text, use that English version directly.
- If scraped text is in another language, **translate it to English** before writing the CSV/JSON.
- Do not translate identifiers or structured values: keep `email`, `mobile_primary`, `domain`, and `linkedin_url` unchanged.
- Preserve company legal names only when an official English brand/name exists on the source; otherwise translate the displayed exhibitor name to clear English.

---

## Check & Verify (Required Rule)

After scraping and enriching all exhibitor data, **you must perform a verification pass** before saving the final CSV/JSON. This rule applies to every scraping task.

### What to Verify

1. **Field Completeness**
   - Check all 9 required fields are present as column headers in the exact names listed above.
   - Report coverage percentage for each field (e.g. `email: 78/85 (91.8%)`).



2. **Value Correctness**
   - `domain`: Must start with `http://` or `https://`. Remove bare domains without protocol. Reject LinkedIn, Facebook, or directory URLs as the primary domain.
   - `email`: Must contain `@` and a valid TLD. Reject placeholder emails (e.g. `example@domain.com`, `info@mysite.com`).
   - `mobile_primary`: Must contain at least 7 digits after stripping non-numeric characters. Reject values shorter than 7 digits.
   - `linkedin_url`: Must contain `linkedin.com/company/` or `linkedin.com/school/`. Reject profile URLs (`/in/`).
   - `city`: Must be a real city name (not a full address string, not a country name alone).
   - `full_address`: Must include a street-level detail. Reject values that only contain a city or country name.
   - `description`: Must be at least 30 characters. Reject boilerplate browser errors (e.g. text containing "enable JavaScript", "cookie", "just a moment").
   - `booth`: Accept empty only if the event site genuinely provides no booth data for any exhibitor.
   - `company_name`: Must not be empty. Must not contain raw HTML tags or encoding artifacts (e.g. `&amp;`, `&#39;`).

3. **Spot-Check Sample Records**
   - Always verify **at least 3 sample records** end-to-end by cross-referencing scraped values against the live event page or the company's official website.
   - Confirm the sample exhibitor mentioned in the user's request (if any) is present with correct values.

4. **Security Check**
   - Confirm the `SERPER_API_KEY` value from `.env` is **not present** anywhere in the CSV or JSON output files.

### Verification Output
After the verification pass, print or log a summary report in this format:
```
=== Verification Report: {EVENT_NAME} ===
Total Exhibitors : {N}
Field Coverage   :
  company_name   : {N}/{N} (100.0%)
  booth          : {N}/{N} (XX.X%)
  description    : {N}/{N} (XX.X%)
  email          : {N}/{N} (XX.X%)
  mobile_primary : {N}/{N} (XX.X%)
  domain         : {N}/{N} (XX.X%)
  full_address   : {N}/{N} (XX.X%)
  city           : {N}/{N} (XX.X%)
  linkedin_url   : {N}/{N} (XX.X%)
Sample Verified  : [company name] ✓
Security Check   : No API key leakage ✓
Status           : PASSED / FAILED
```
If the status is **FAILED**, fix all flagged issues before saving the final output files.