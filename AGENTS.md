# Agent Scraping Rules & Guidelines

Every scraper and agent running in this workspace must adhere strictly to these rules:

## 1. Mandatory Output Fields
Every dataset produced by a scraper must include these core fields:
1. **`exhibitor_name`**: Full name of the company or exhibiting brand.
2. **`domain`**: Official website root domain (e.g. `example.com`, lowercase, no `https://`, no `www.`, no trailing slash).
3. **`contact_number`**: Telephone / mobile / phone number (standard format with country/area code).
4. **`mail`**: Contact email address.
5. **`location`**: Full physical address (street, city, state/province).
6. **`country`**: **Full English country name — NEVER shortcode** (e.g., `Italy` not `IT`, `Germany` not `DE`, `Netherlands` not `NL`, `United States` not `US`, `France` not `FR`, `Spain` not `ES`, `Belgium` not `BE`, `Austria` not `AT`).

## 2. Scraping Execution
- Every exhibitor hyperlink on directory/listing pages must be visited to scrape the full profile and contact information.

## 3. Fallback: Serper Google Search
- If an exhibitor lacks a domain or website on the portal:
  - Load `SERPER_API_KEY` from `d:\habsy\scrapping\.env`.
  - Search Serper (`https://google.serper.dev/search`) using query: `"{exhibitor_name}" official website {location}`.
  - Filter out social media (LinkedIn, Facebook, Instagram, Twitter/X) and directories (Wikipedia, YouTube, YellowPages, Yelp).
  - Extract the verified domain from `knowledgeGraph.website` or top organic match.
  - Also retrieve `knowledgeGraph.address` and `knowledgeGraph.phone` if location or phone is missing.

## 4. Output Format
- CSV file exported with `utf-8-sig` encoding (to properly display accented characters in Excel).
- Standard Column Order: `exhibitor_name`, `domain`, `contact_number`, `mail`, `location`, `country`, ...
