#!/usr/bin/env python3
"""
Fast and reliable Python scraper for WHX Bangkok 2026 Exhibitor List.
This script fetches the target page, extracts embedded exhibitor records,
performs cleaning and deduplication, and saves the result to a CSV file.
"""

import os
import re
import csv
import html
import json
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from bs4 import BeautifulSoup

def fetch_page(url):
    """
    Fetches the HTML content of the target URL using a requests Session.
    Includes custom headers, retries with exponential backoff, and timeouts.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache"
    }
    
    session = requests.Session()
    
    # Configure retry strategy with exponential backoff (1s, 2s, 4s, 8s, 16s)
    retries = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        raise_on_status=False
    )
    session.mount("http://", HTTPAdapter(max_retries=retries))
    session.mount("https://", HTTPAdapter(max_retries=retries))
    
    try:
        response = session.get(url, headers=headers, timeout=15)
        return response
    except requests.exceptions.RequestException as e:
        print(f"HTTP request failed: {e}")
        return None

def detect_data_source(html_content):
    """
    Detects the source structure of the data inside the HTML.
    """
    if "const DATA =" in html_content:
        return "Embedded Javascript DATA Variable"
    
    soup = BeautifulSoup(html_content, "lxml")
    if soup.find("table"):
        return "HTML Table"
    
    return "Unknown/None"

def parse_exhibitors(html_content):
    """
    Extracts the embedded JSON array from the script tags or raw HTML.
    """
    # 1. Try to extract script content using BeautifulSoup for clean parsing
    soup = BeautifulSoup(html_content, "lxml")
    script_text = None
    for script in soup.find_all("script"):
        if script.string and "const DATA =" in script.string:
            script_text = script.string
            break
            
    # 2. Extract JSON string using regular expression
    pattern = r"const\s+DATA\s*=\s*(\[.*?\])\s*;"
    
    if script_text:
        match = re.search(pattern, script_text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError as e:
                print(f"Failed to parse JSON from script tag: {e}")
                
    # Fallback to searching the entire HTML text
    match = re.search(pattern, html_content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError as e:
            print(f"Failed to parse JSON from raw HTML: {e}")
            
    return []

def clean_text(text):
    """
    Cleans a text field according to requirements:
    - strips leading/trailing spaces
    - converts repeated whitespace to a single space
    - removes unnecessary \n, \r, and \t
    - converts HTML entities
    - preserves Unicode characters
    """
    if not text:
        return ""
    
    # Convert HTML entities
    text = html.unescape(str(text))
    # Replace newlines, carriage returns, and tabs with spaces
    text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    # Replace repeated whitespaces with a single space
    text = re.sub(r"\s+", " ", text)
    # Strip leading/trailing spaces
    return text.strip()

def normalize_company_name(name):
    """
    Normalizes a company name for accurate deduplication.
    - lowercase
    - trim whitespace
    - remove repeated spaces
    """
    return clean_text(name).lower()

def deduplicate_records(records):
    """
    Deduplicates records based on company name and booth number.
    If booth number is unavailable, deduplicates using normalized company name.
    """
    unique_records = []
    seen_keys = set()
    duplicates_removed = 0
    
    for record in records:
        # Extract fields
        raw_company = record.get("company", "")
        raw_booth = record.get("booth", "")
        raw_country = record.get("country", "")
        
        # Clean fields
        company_name = clean_text(raw_company)
        booth_number = clean_text(raw_booth)
        country = clean_text(raw_country)
        
        # Generate deduplication key
        norm_company = normalize_company_name(company_name)
        norm_booth = booth_number.lower()
        
        if norm_booth:
            key = (norm_company, norm_booth)
        else:
            key = (norm_company, "")
            
        if key in seen_keys:
            duplicates_removed += 1
        else:
            seen_keys.add(key)
            unique_records.append({
                "company_name": company_name,
                "booth_number": booth_number,
                "country": country,
                "official_website": ""
            })
            
    return unique_records, duplicates_removed

def save_csv(records, filename):
    """
    Saves the cleaned records to a CSV file using utf-8-sig encoding.
    """
    headers = ["company_name", "booth_number", "country", "official_website"]
    try:
        with open(filename, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for record in records:
                writer.writerow(record)
        return True
    except Exception as e:
        print(f"Error saving CSV to {filename}: {e}")
        fallback = "whx_bangkok_2026_exhibitors_new.csv"
        try:
            with open(fallback, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                for record in records:
                    writer.writerow(record)
            print(f"CSV successfully saved to fallback: {fallback}")
            return True
        except Exception as fe:
            print(f"Error saving CSV to fallback {fallback}: {fe}")
            return False

def handle_debug(response, url):
    """
    Saves diagnostic data to debug_page.html and prints detailed logs
    when extraction fails or no records are found.
    """
    debug_filename = "debug_page.html"
    if response is None:
        print("No response from server. Debug page cannot be saved.")
        return

    try:
        with open(debug_filename, "w", encoding="utf-8") as f:
            f.write(response.text)
        print(f"HTML saved to: {debug_filename}")
    except Exception as e:
        print(f"Failed to save debug page: {e}")
        
    print("\n--- DEBUGGING DIAGNOSTICS ---")
    print(f"HTTP status code: {response.status_code}")
    print(f"Final URL: {response.url}")
    print(f"Response length: {len(response.text)} characters")
    
    soup = BeautifulSoup(response.text, "lxml")
    
    title = soup.title.string.strip() if soup.title else "No Title Found"
    print(f"Page title: {title}")
    
    tables = soup.find_all("table")
    print(f"Detected tables count: {len(tables)}")
    for idx, table in enumerate(tables, 1):
        print(f"  - Table {idx}: class={table.get('class')}, id={table.get('id')}")
        
    scripts = soup.find_all("script")
    print(f"Number of script tags: {len(scripts)}")
    
    # Check for possible embedded JSON patterns
    possible_json_blocks = 0
    for idx, script in enumerate(scripts, 1):
        if script.string:
            content = script.string
            if "DATA" in content or "data" in content:
                print(f"  - Script {idx}: Contains 'DATA' or 'data' keyword")
                possible_json_blocks += 1
            elif re.search(r"\[\s*\{", content):
                print(f"  - Script {idx}: Contains JSON array format ([{{...}}])")
                possible_json_blocks += 1
                
    print(f"Possible embedded JSON blocks: {possible_json_blocks}")
    print("\n--- INVESTIGATION REPORT ---")
    if "Cloudflare" in response.text or "security" in title.lower() or response.status_code == 403:
        print("-> Access appears to be protected or challenged by a Web Application Firewall (e.g. Cloudflare).")
    elif possible_json_blocks == 0 and len(tables) == 0:
        print("-> The page has no tables or raw data variables. The page may require JavaScript execution (dynamic client-side rendering).")
    else:
        print("-> Data structure exists in HTML, but the regex patterns failed to parse it. Inspect debug_page.html to review the DOM structure.")

def main():
    target_url = "https://www.worldhealthexpo.com/media/bf47158a/whx-bangkok-2026-exhibitor-list-updateasof29May-1f1b993c7fd45ac14ccdc1d771cb06e5.html"
    csv_filename = "whx_bangkok_2026_exhibitors.csv"
    
    print(f"Fetching exhibitor list from: {target_url}")
    response = fetch_page(target_url)
    
    if not response or response.status_code != 200:
        print("Failed to fetch the target page.")
        handle_debug(response, target_url)
        return
        
    html_content = response.text
    
    # Detect the data source
    source = detect_data_source(html_content)
    print(f"Detected data source: {source}")
    
    # Parse the exhibitors list
    raw_records = parse_exhibitors(html_content)
    if not raw_records:
        print("No exhibitor records found in the HTML content.")
        handle_debug(response, target_url)
        return
        
    total_raw = len(raw_records)
    
    # Clean and deduplicate records
    unique_records, duplicates_removed = deduplicate_records(raw_records)
    
    records_with_booth = sum(1 for r in unique_records if r["booth_number"])
    records_with_country = sum(1 for r in unique_records if r["country"])
    
    # Save output to CSV
    success = save_csv(unique_records, csv_filename)
    if not success:
        return
        
    # Print Summary statistics
    print("\nScraping completed.\n")
    print(f"Total raw records: {total_raw}")
    print(f"Unique exhibitors: {len(unique_records)}")
    print(f"Duplicates removed: {duplicates_removed}")
    print(f"Records with booth number: {records_with_booth}")
    print(f"Records with country: {records_with_country}")
    print()
    print(f"CSV saved to:\n{csv_filename}\n")
    
    # Print the first 10 records for visual verification
    print("First 10 records:")
    preview_count = min(10, len(unique_records))
    for idx in range(preview_count):
        rec = unique_records[idx]
        print(f"Company: {rec['company_name']} | Booth: {rec['booth_number']} | Country: {rec['country']} | Website: {rec['official_website']}")

if __name__ == "__main__":
    main()
