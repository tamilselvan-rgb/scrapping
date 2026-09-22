import argparse
import asyncio
import csv
import datetime
import os
import sys
import logging
from dotenv import load_dotenv

# Add directory to sys.path to ensure absolute imports work
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from crawler.http_crawler import HttpCrawler
from crawler.playwright_crawler import PlaywrightCrawler
from crawler.pagination import PaginationDetector
from crawler.page_detector import PageDetector
from extractors.list_extractor import ListExtractor
from extractors.profile_extractor import ProfileExtractor
from enrichment.website_search import WebsiteSearch
from enrichment.website_verifier import WebsiteVerifier
from utils.url_utils import normalize_url, get_domain
from utils.text_utils import normalize_company_name
from utils.logger import setup_logger
from utils.checkpoint import CheckpointManager

# Output CSV Columns
CSV_COLUMNS = [
    "company_name",
    "website",
    "website_source",
    "website_confidence",
    "website_verification_reason",
    "exhibitor_profile_url",
    "category",
    "industry",
    "description",
    "country",
    "city",
    "address",
    "email",
    "phone",
    "booth_number",
    "hall_number",
    "contact_person",
    "linkedin",
    "facebook",
    "instagram",
    "products",
    "brands",
    "source_page",
    "scraped_at"
]

logger = logging.getLogger("scraper.main")

def parse_args():
    parser = argparse.ArgumentParser(description="Modular Event Exhibitor Web Scraper")
    parser.add_argument("url", help="Starting Exhibitor List URL")
    parser.add_argument("--output", "-o", help="Custom path for output CSV file")
    parser.add_argument("--concurrency", "-c", type=int, default=10, help="Max concurrent HTTP requests (default: 10)")
    parser.add_argument("--browser-concurrency", "-bc", type=int, default=3, help="Max concurrent Playwright pages (default: 3)")
    parser.add_argument("--search-missing-websites", "-s", action="store_true", help="Search missing websites using Serper API")
    parser.add_argument("--resume", "-r", action="store_true", help="Resume from checkpoint file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose debug logging")
    return parser.parse_args()

async def scrape_listings(
    start_url: str, 
    http_crawler: HttpCrawler, 
    playwright_crawler: PlaywrightCrawler
) -> List[str]:
    """
    Crawls pages of the directory list and extracts all unique profile URLs.
    Handles static pagination, load-more button clicking, or infinite scroll fallback.
    """
    profile_urls = set()
    current_url = start_url
    page_num = 1
    max_pages = 50 # Safeguard limit for pagination
    
    logger.info(f"Analyzing starting website: {start_url} ...")
    
    # 1. Fetch initial page to inspect structure
    initial_html = await http_crawler.fetch_html(start_url)
    
    # Fallback to playwright if static HTTP gets blocked or is empty
    if not initial_html:
        logger.warning("Initial HTTP crawl returned empty. Retrying with Playwright...")
        initial_html = await playwright_crawler.fetch_html_dynamic(start_url)
        if not initial_html:
            logger.error("Could not fetch the initial page using HTTP or Playwright. Exiting listing scraping.")
            return []

    # 2. Extract initial profiles and detect pagination layout
    extractor = ListExtractor(start_url)
    initial_exhibitors = extractor.extract(initial_html)
    for item in initial_exhibitors:
        profile_urls.add(item["exhibitor_profile_url"])
        
    pagination = PaginationDetector.detect_pagination(BeautifulSoup(initial_html, 'lxml'), start_url)
    pag_type = pagination["type"]
    logger.info(f"Detected loading structure: {pag_type}")

    # 3. Handle different pagination flows
    if pag_type in ("load_more", "infinite_scroll") or len(initial_exhibitors) == 0:
        # Require playwright dynamic load
        scroll = pag_type == "infinite_scroll" or len(initial_exhibitors) == 0
        click_selector = pagination.get("selector") if pag_type == "load_more" else None
        
        dynamic_html = await playwright_crawler.fetch_html_dynamic(
            start_url, 
            scroll=scroll, 
            click_selector=click_selector,
            max_clicks=20
        )
        if dynamic_html:
            dynamic_exhibitors = extractor.extract(dynamic_html)
            for item in dynamic_exhibitors:
                profile_urls.add(item["exhibitor_profile_url"])
                
    elif pag_type in ("query_param", "next_button", "path_variable"):
        # Iterate over pagination links
        while current_url and page_num < max_pages:
            logger.info(f"Processing listing page {page_num} ...")
            html = await http_crawler.fetch_html(current_url)
            if not html:
                logger.warning(f"Could not load listing page {page_num}. Stopping listing crawl.")
                break
                
            soup = BeautifulSoup(html, 'lxml')
            page_exhibitors = extractor.extract(html)
            
            # If no new exhibitors found, we have likely reached the end
            new_additions = 0
            for item in page_exhibitors:
                u = item["exhibitor_profile_url"]
                if u not in profile_urls:
                    profile_urls.add(u)
                    new_additions += 1
                    
            logger.info(f"Page {page_num}: Discovered {len(page_exhibitors)} profiles ({new_additions} new).")
            if new_additions == 0 and page_num > 1:
                logger.info("No new profiles discovered. Stopping listing crawl.")
                break
                
            # Determine next page URL
            next_url = None
            if pag_type == "query_param":
                next_url = PaginationDetector.generate_next_query_url(
                    current_url, 
                    pagination["param_name"], 
                    page_num
                )
            elif pag_type == "path_variable":
                next_url = PaginationDetector.generate_next_path_url(current_url, page_num)
            elif pag_type == "next_button":
                next_info = PaginationDetector.find_next_button_link(soup, current_url)
                if next_info:
                    next_url = next_info["url"]
                    
            if not next_url or next_url == current_url:
                logger.info("Next page URL not found or unchanged. Stopping listing crawl.")
                break
                
            current_url = next_url
            page_num += 1

    logger.info(f"Listing crawl finished. Total unique profiles discovered: {len(profile_urls)}")
    return list(profile_urls)

async def scrape_single_profile(
    url: str,
    http_crawler: HttpCrawler,
    playwright_crawler: PlaywrightCrawler,
    http_sem: asyncio.Semaphore,
    browser_sem: asyncio.Semaphore,
    website_searcher: WebsiteSearch,
    args: argparse.Namespace
) -> Optional[Dict[str, Any]]:
    """
    Scrapes an individual exhibitor profile page. 
    First tries static HTTP, falls back to Playwright if needed, 
    and enriches missing company websites if requested.
    """
    async with http_sem:
        logger.debug(f"Starting scrape for: {url}")
        
        # 1. Fetch page content (prefer static HTTP)
        html = await http_crawler.fetch_html(url)
        
        # 2. Fallback to browser session if HTTP failed
        if not html:
            logger.warning(f"HTTP request failed for profile {url}. Falling back to browser session...")
            async with browser_sem:
                html = await playwright_crawler.fetch_html_dynamic(url)
                
        if not html:
            logger.error(f"Failed to fetch content for profile URL: {url}")
            return None

        # 3. Extract profile information
        extractor = ProfileExtractor(url)
        data = extractor.extract(html)
        
        # 4. Search and verify missing company website if requested
        if args.search_missing_websites and not data["website"]:
            company_name = data["company_name"]
            if company_name and company_name != "Unknown Exhibitor":
                logger.info(f"Website missing for '{company_name}'. Searching via Serper API...")
                candidates = await website_searcher.search_company_website(
                    company_name, 
                    country=data.get("country"), 
                    industry=data.get("industry")
                )
                if candidates:
                    web_url, src, conf, reason = WebsiteVerifier.verify_candidate(
                        company_name, 
                        candidates, 
                        data
                    )
                    data["website"] = web_url
                    data["website_source"] = src
                    data["website_confidence"] = conf
                    data["website_verification_reason"] = reason

        data["scraped_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return data

async def main():
    load_dotenv()
    args = parse_args()
    setup_logger("scraper", verbose=args.verbose)
    
    # Generate default output name if not provided
    domain = get_domain(args.url).replace('.', '_')
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = args.output or f"output/exhibitors_{domain}_{timestamp}.csv"
    
    # Initialize checkpoint manager
    checkpoint_manager = CheckpointManager()
    checkpoint_state = checkpoint_manager.load()
    
    # Check if we can resume
    profile_urls = []
    if args.resume and checkpoint_state.get("start_url") == args.url:
        profile_urls = checkpoint_state.get("discovered_urls", [])
        logger.info(f"Resuming scrape. Found {len(profile_urls)} discovered profiles in checkpoint.")
    else:
        # Starting new scrape: clear previous state
        checkpoint_state["start_url"] = args.url
        checkpoint_state["discovered_urls"] = []
        checkpoint_state["completed_urls"] = {}
        checkpoint_manager.save(checkpoint_state)

    # Initialize crawlers
    http_crawler = HttpCrawler()
    playwright_crawler = PlaywrightCrawler(headless=True)
    website_searcher = WebsiteSearch()

    try:
        # Fetch profile list if we don't have it in checkpoint
        if not profile_urls:
            await playwright_crawler.start()
            profile_urls = await scrape_listings(args.url, http_crawler, playwright_crawler)
            checkpoint_state["discovered_urls"] = profile_urls
            checkpoint_manager.save(checkpoint_state)
            
        if not profile_urls:
            logger.error("No profile URLs were found. Exiting.")
            return

        # Setup output file and write header if new
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        file_exists = os.path.exists(output_file)
        
        # We open the file in append mode to dynamically save progress
        with open(output_file, "a", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=CSV_COLUMNS)
            if not file_exists or os.path.getsize(output_file) == 0:
                writer.writeheader()
                csvfile.flush()

            # Filter out already completed URLs
            urls_to_scrape = [u for u in profile_urls if u not in checkpoint_state["completed_urls"]]
            total_urls = len(profile_urls)
            completed_count = len(checkpoint_state["completed_urls"])
            
            logger.info(f"Queueing {len(urls_to_scrape)} profile pages for details extraction...")
            
            # Setup Semaphores for concurrency control
            http_sem = asyncio.Semaphore(args.concurrency)
            browser_sem = asyncio.Semaphore(args.browser_concurrency)
            
            # Helper function to scrape and write immediately
            async def worker(url: str):
                try:
                    result = await scrape_single_profile(
                        url, 
                        http_crawler, 
                        playwright_crawler, 
                        http_sem, 
                        browser_sem, 
                        website_searcher, 
                        args
                    )
                    if result:
                        # Prevent duplicate company writes if we have records
                        writer.writerow(result)
                        csvfile.flush()
                        
                        checkpoint_state["completed_urls"][url] = {
                            "status": "success",
                            "timestamp": datetime.datetime.now().isoformat(),
                            "company_name": result["company_name"]
                        }
                    else:
                        checkpoint_state["completed_urls"][url] = {
                            "status": "failed",
                            "timestamp": datetime.datetime.now().isoformat()
                        }
                    # Save checkpoint state after each profile completion
                    checkpoint_manager.save(checkpoint_state)
                    
                    nonlocal completed_count
                    completed_count += 1
                    
                    # Print terminal progress reporting
                    src_web = sum(1 for v in checkpoint_state["completed_urls"].values() 
                                  if isinstance(v, dict) and v.get("status") == "success") # approx metrics
                    logger.info(f"Progress: Profiles scraped {completed_count}/{total_urls}")
                    
                except Exception as e:
                    logger.error(f"Unhandled worker error for URL {url}: {e}")

            # Run concurrency queue
            tasks = [worker(url) for url in urls_to_scrape]
            if tasks:
                await asyncio.gather(*tasks)

        logger.info(f"Scrape completed successfully! Saved results to: {output_file}")
        
        # Print summary report
        completed_records = checkpoint_state["completed_urls"]
        success_count = sum(1 for v in completed_records.values() if v.get("status") == "success")
        logger.info(f"--- Crawl Summary ---")
        logger.info(f"Total Discovered Profiles: {total_urls}")
        logger.info(f"Successfully Scraped: {success_count}/{total_urls}")
        
        # Clear checkpoint upon full success
        checkpoint_manager.clear()

    except Exception as e:
        logger.critical(f"Critical error during scraper execution: {e}", exc_info=True)
    finally:
        # Close crawler resources
        await http_crawler.close()
        await playwright_crawler.stop()

if __name__ == "__main__":
    # Ensure asyncio event loop runs correctly on Windows
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
