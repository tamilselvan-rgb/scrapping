# Company Intelligence Extractor

A production-ready Python application that crawls a company's domain recursively, extracts structured data from pages, performs public web search enrichment, validates and deduplicates findings, qualifies them against target ICP criteria, and exports the intelligence into both structured JSON files and professionally formatted Microsoft Word (.docx) documents.

## Project Architecture

The application is structured modularly:
* **`main.py`**: CLI entry point and orchestration layer.
* **`crawler/`**: BFS Crawling management, robots.txt compliance, sitemap.xml ingestion, and dual-crawler support (Crawl4AI as primary, Playwright as a robust fallback).
* **`extractors/`**: Low-overhead heuristics parsing titles, metadata, headers, structured schema blocks (JSON-LD, OpenGraph), contact information (emails, phones), and performing page classifications.
* **`ai/`**: Schema definition, custom prompts, and structured LLM extraction wrappers supporting both Google Gemini API and OpenAI.
* **`enrichment/`**: Querying public web records via Google Serper or DuckDuckGo search to verify/enrich company stats. Implements confidence scoring and conflict trackers.
* **`qualification/`**: Rating company profiles against ideal customer characteristics.
* **`exporters/`**: Generation of `company_data.json`, `crawl_report.json`, and styled Word summaries (`company_report.docx`).
* **`tests/`**: Suite of verification unit tests.

---

## Installation & Setup

### Prerequisites
* Python 3.11 or later
* Git (optional)

### Steps

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Install Browser Engines**:
   Ensure Playwright browsers are installed:
   ```bash
   playwright install
   ```

3. **Configure Environment**:
   Copy `.env.example` to `.env` and fill in your keys:
   ```bash
   copy .env.example .env
   ```
   Edit `.env`:
   ```env
   LLM_PROVIDER=gemini           # 'gemini' or 'openai'
   LLM_MODEL=gemini-1.5-flash    # 'gemini-1.5-flash' or 'gpt-4o-mini'
   LLM_API_KEY=your_gemini_key_here
   SERPER_API_KEY=your_serper_key_here # Optional (falls back to DuckDuckGo search if missing)
   ```

---

## Usage

### Simple Crawl
Crawl and extract intelligence from a company's website:
```bash
python main.py --url https://example.com
```

### Crawl with Limits
Control page and depth settings:
```bash
python main.py --url https://example.com --max-pages 20 --max-depth 2
```

### Crawl with ICP Qualification
You can pass a JSON criteria file to evaluate the target company:
```bash
python main.py --url https://example.com --icp-config icp_criteria.json
```

Where `icp_criteria.json` looks like:
```json
{
    "industries": ["Software", "SaaS", "Technology"],
    "locations": ["California", "India", "San Francisco"],
    "min_employees": 50,
    "max_employees": 500,
    "technologies": ["react", "aws"]
}
```

---

## Outputs

All output files are saved under `output/{company_domain_folder}/`:
1. **`company_data.json`**: Standard JSON file following Pydantic schemas. Includes detailed metadata and source mappings for all attributes.
2. **`company_report.docx`**: Styled Microsoft Word report with clean margins, headings, formatted tables, bullet points, and source footnotes.
3. **`crawl_report.json`**: Details statistics of the crawl (pages crawled, failed URLs, HTTP status codes, redirects, duplicate counts, etc.).

---

## Running Unit Tests

Run the test suite using Python's standard `unittest` framework:
```bash
python -m unittest discover tests
```
This tests:
* URL normalization and ignore filter lists
* Fuzzy deduplication algorithm
* Page classification heuristic mappings
* Pydantic schemas validation and conflict flags
