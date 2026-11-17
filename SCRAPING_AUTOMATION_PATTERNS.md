# Exhibitor Scraping Automation Patterns

This document describes the recurring event-directory patterns in this
workspace and the extraction strategy an automated scraper should select for
each one.

The goal is to make a new event scraper mostly configuration plus a small
site-specific adapter, instead of a completely new script every time.

## 1. Non-negotiable output contract

Every final CSV and JSON export must contain exactly these nine fields, in this
order:

```text
company_name, booth, description, email, mobile_primary, domain,
full_address, city, linkedin_url
```

Rules:

- CSV encoding: `utf-8-sig`.
- JSON object keys use the same nine names and order.
- `domain` must be an official website URL beginning with `http://` or
  `https://`; do not export `www.`-only or social/directory URLs.
- Preserve every booth, hall, stand, pavilion, or co-exhibitor location. Join
  multiple values with `; `.
- Only use the requested event year. Do not merge a previous-year directory.
- Missing values remain empty strings after enrichment has been attempted.
- Do not add `event_year`, `source_url`, `chapter`, scraper status, or API
  metadata to the final CSV/JSON. Keep those in a private audit file if needed.

## 2. Select a scraper pattern

Start with a cheap inspection before using a browser:

1. Download the page with `requests`.
2. Look for exhibitor names, links, pagination controls, embedded JSON, iframe
   URLs, script bundles, PDF links, and image URLs.
3. Inspect the network/data source only if the HTML does not contain the
   records.
4. Use browser automation only for a genuinely interactive or protected flow.

| Pattern | Detection signals | Preferred strategy |
|---|---|---|
| Static HTML cards/table | Names are in downloaded HTML | Parse cards/rows with BeautifulSoup |
| Detail-link directory | Company name links to a profile page | Collect every profile URL, then visit each profile |
| Numbered pagination | `?page=`, `/page/2`, Next button, page count | Iterate until the final page; deduplicate by canonical URL/name |
| Form/POST pagination | Page selector submits a form or sends POST | Reproduce the form request and iterate all page values |
| Load-more button | `Load more`, `Show more`, `View more` | Trigger repeatedly; stop only when button disappears/disabled and the record count stops increasing |
| Infinite scroll | Cards appear after scrolling; no page links | Scroll/trigger the UI or call the underlying API until no next cursor remains |
| API/JSON directory | XHR/fetch returns JSON records | Call the endpoint directly with the same parameters and cursor/page |
| GraphQL directory | `/api/graphql`, query names such as `Exhibitors` | Reproduce the query and follow `pageInfo.hasNextPage`/`endCursor` |
| iframe/widget directory | Main page contains an exhibitor iframe | Fetch and inspect the iframe; scrape its API rather than the parent page |
| React/Vue/Next SPA | Empty HTML plus JS bundles or `__NEXT_DATA__` | Inspect source maps/bundles and extract the data endpoint or embedded JSON |
| Embedded bundle data | Bundle contains `JSON.parse('[...]')` or a large object | Parse the official bundle data, while recording the bundle URL as the source |
| PDF exhibitor guide | `.pdf` link, page range supplied by user | Download PDF, extract text/tables, then inspect image pages if text is absent |
| Image/PDF image directory | Logos or scanned exhibitor pages | Download original images and use OCR; manually spot-check names |
| Map/listing directory | Map cards, filters, booth map, category tabs | Enumerate all filters/tabs and collect unique cards |
| Third-party event platform | Swapcard, MapYourShow, Connect, ExpoFP, etc. | Identify the platform API; retain platform profile URLs for auditing |
| Search-only fallback | Portal has no website/domain | Query Serper with the exact company name, event year, and location |

## 3. Common extraction patterns

### A. Static cards and tables

Use stable semantic selectors first:

```python
for card in soup.select(".exhibitor-card, .exhibitor, [data-exhibitor]"):
    name = text(card.select_one(".company-name, .name, h2, h3"))
    booth = text(card.select_one(".booth, .stand, .hall"))
    profile = absolute_url(card.select_one("a[href]"))
```

Do not assume CSS class names are stable. Fall back to labels such as
`Booth`, `Stand`, `Hall`, `Website`, `Email`, and `Phone`.

### B. Profile-link directories

Directory pages often contain only names and a link. The workflow is:

1. Collect all profile links from every list page.
2. Normalize and deduplicate URLs.
3. Request each profile with retry/backoff.
4. Extract the full description and contact fields.
5. Extract the official website link from the profile before using search.

Never stop at the listing page when profile links are present.

### C. Numbered pages and filters

Support all of these forms:

```text
?page=2
?p=2
?pageNumber=2
/page/2
POST {"page": 2}
```

For filter-based directories, enumerate:

- Every page for the default filter.
- Every category/letter/region filter if it changes the result set.
- Every “all” or “featured” section when it contains distinct exhibitors.

Use a set of canonical profile URLs and normalized company names to prevent
duplicates between filters.

### D. Load more and infinite scroll

Load-more sites commonly render only the first 25/50/100 records. The
automation must:

- Capture the initial records.
- Click the control or invoke its underlying request.
- Wait for the DOM/network state to settle.
- Confirm the record count increased.
- Repeat until the control is absent, disabled after a successful final load,
  or the API reports `hasNextPage=false`.
- Detect a stuck request and fail with a diagnostic rather than looping forever.

The RE+ directory is an example of this pattern. Its visible page is an
iframe widget, while the reliable source is a paginated GraphQL query:

```graphql
query($viewId: ID!, $endCursor: String) {
  view: Core_eventExhibitorListView(viewId: $viewId) {
    exhibitors(cursor: {first: 50, after: $endCursor}) {
      nodes { name description booth }
      pageInfo { hasNextPage endCursor }
    }
  }
}
```

### E. API and GraphQL directories

Prefer the data API over rendering thousands of cards. Record:

- Endpoint.
- HTTP method and required headers.
- Query/body parameters.
- Page size and cursor.
- Response path containing records.
- Response path containing next-page state.

Stop on `hasNextPage=false`, a missing cursor, or no new unique records.
Preserve the API's profile ID/link when it is available.

### F. SPA and embedded bundle directories

For React/Vue/Next sites:

1. Download the initial HTML.
2. Find script bundles and `__NEXT_DATA__`.
3. Search scripts/source maps for `exhibitor`, `company`, `fetch(`,
   `axios`, `/api/`, `graphql`, and route names.
4. Identify either the API request or embedded JSON.
5. Parse only the requested event/year dataset.

India ITME 2026 is an embedded-bundle example: its public route loads a
lazy React chunk containing a JSON exhibitor list. A bundle is acceptable as a
source only when it is the official event application and the records are
clearly labeled for the requested year.

### G. PDF guides and scanned pages

When the user specifies a page range:

1. Download the PDF once and save a source copy outside the final export.
2. Extract text from the specified pages.
3. Detect rows using booth/stand patterns and company-name boundaries.
4. Render only pages with poor/no text to images.
5. OCR those pages and normalize OCR errors.
6. Deduplicate entries across page breaks.
7. Verify a sample against the PDF visually.

Do not treat a PDF's table of contents, advertisements, sponsors, or venue
map as exhibitors unless the page clearly identifies them as such.

### H. Image and logo directories

For image-only exhibitor lists:

- Download the highest-resolution image available.
- OCR the company name, then retain the image URL as an audit reference.
- Do not infer a company from a logo alone if OCR is inconclusive.
- Use exact visual spelling for the initial `company_name`.
- Search for the official domain only after the name is normalized.
- Spot-check ambiguous names manually.

### I. Detail-page domain and contact extraction

On each profile, inspect in this order:

1. Explicit `Website`/`Official website` link.
2. `mailto:` email link.
3. Telephone link or labeled phone field.
4. Address and city labels.
5. Description text for contact details.
6. JSON-LD (`application/ld+json`) or Open Graph metadata.
7. Search fallback for still-missing fields.

Normalize domains:

```python
host = (urlparse(url).hostname or "").lower().removeprefix("www.")
domain = f"https://{host}" if host else ""
```

Reject LinkedIn, Facebook, Instagram, X/Twitter, YouTube, Wikipedia,
YellowPages, Yelp, and generic directory/marketplace URLs as the primary
domain.

## 4. Domain enrichment pattern

Use the profile website first. For a missing domain, load `SERPER_API_KEY`
from the project-root `.env` and query:

```text
"COMPANY NAME" official website 2026 LOCATION
```

Accept a result only when:

- It is the company's own website.
- The company name and location/industry match sufficiently.
- It is not a social profile, directory, marketplace, or unrelated similarly
  named company.

Prefer `knowledgeGraph.website`, then a matching organic result. Leave the
field blank when the match is uncertain. Never expose the API key in source
copies, logs, CSV, or JSON.

## 5. Normalization and deduplication

Normalize before deduplication:

- Trim whitespace and collapse repeated spaces.
- Decode HTML entities.
- Remove visual-only labels such as `Featured Exhibitor`.
- Preserve legal suffixes when displayed by the official source.
- Normalize booth separators, but preserve all booth values.
- Compare names case-insensitively after removing punctuation for duplicate
  detection; retain the first official spelling.
- Deduplicate by profile URL first, then by normalized company name plus booth.

Do not merge two similarly named companies solely because their names look
similar. Keep separate records when their profile URLs, countries, or booths
are different.

## 6. Verification pass

Every scraper must run a final verification before writing the deliverables:

1. Confirm exactly the nine canonical headers and their order.
2. Confirm every `company_name` is non-empty.
3. Validate domain protocols and reject social/directory domains.
4. Validate email, phone, address, city, LinkedIn, and description formats.
5. Confirm booth coverage when the source displays booth data.
6. Confirm the requested event year is the source year.
7. Spot-check at least three records against the live profile pages.
8. Confirm the `.env` API key does not occur in any output.
9. Report field coverage and whether verification passed.

Recommended report:

```text
=== Verification Report: EVENT NAME ===
Total Exhibitors : N
company_name     : N/N (100.0%)
booth            : N/N (XX.X%)
description      : N/N (XX.X%)
email            : N/N (XX.X%)
mobile_primary   : N/N (XX.X%)
domain           : N/N (XX.X%)
full_address     : N/N (XX.X%)
city             : N/N (XX.X%)
linkedin_url     : N/N (XX.X%)
Sample Verified  : company A; company B; company C
Security Check   : No API key leakage
Status           : PASSED / FAILED
```

## 7. Failure handling and safety

Retry transient HTTP failures with bounded exponential backoff. Stop and
report when encountering:

- Login, CAPTCHA, passkey, consent requiring manual action, or access denial.
- A site that returns a different year than requested.
- A directory whose “load more” request repeatedly returns the same page.
- A profile link that redirects to an unrelated site.
- An ambiguous company/domain match.

Do not bypass authentication, CAPTCHA, rate limits, or access controls.
Preserve partial source data and the exact failure reason for resumability.

## 8. Recommended automation layout

For new events, use this structure:

```text
EVENT NAME/
  scraper.py
  EVENT_NAME_exhibitors.csv
  EVENT_NAME_exhibitors.json
  source/                 # optional, not part of final export
  verification_report.txt # optional audit output
```

Implement these reusable functions:

```python
discover_source(url)
fetch_listing_pages(source)
extract_listing_records(page)
fetch_profile(profile_url)
extract_profile_fields(profile)
enrich_missing_domains(records)
normalize_and_deduplicate(records)
verify(records)
write_csv_and_json(records)
```

Keep site-specific selectors, API queries, page ranges, and field mappings in
configuration or small adapters. The core pagination, retry, normalization,
validation, export, and verification code should be shared.

## 9. Git handoff

After verification:

1. Check `git status`.
2. Stage only the event folder and its intended files.
3. Commit with the exact event name.
4. Push and verify the remote result.
5. If push fails, report that the local commit succeeded and include the
   failure reason; do not claim the push completed.
