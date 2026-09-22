import argparse
import asyncio
import datetime
import json
import logging
import os
import sys
from urllib.parse import urlparse

from dotenv import load_dotenv

# Add directory to sys.path to ensure imports work
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from crawler.url_manager import UrlManager
from crawler.robots import RobotsParser
from crawler.crawler import WebCrawler
from extractors.page_extractor import PageExtractor
from extractors.contact_extractor import ContactExtractor
from extractors.structured_data import StructuredDataExtractor
from ai.llm_extractor import LlmExtractor
from enrichment.web_search import WebSearcher
from enrichment.company_enrichment import CompanyEnricher
from enrichment.source_validator import SourceValidator
from qualification.icp import IcpEvaluator
from exporters.json_exporter import JsonExporter
from exporters.docx_exporter import DocxExporter
from models.company import (
    CompanyIntelligenceReport,
    CrawlMetadata,
    PageData,
    ContactDetails,
    EnrichedField,
    ProductServiceItem,
    CustomerItem,
    PartnerItem,
    CompetitorItem,
    LeadershipItem,
    CertificationItem,
    AwardItem
)
from utils.logger import setup_logger
from utils.deduplication import deduplicate_strings, deduplicate_contacts

logger = logging.getLogger("company_intelligence.main")

def parse_args():
    parser = argparse.ArgumentParser(description="Company Intelligence Extractor")
    parser.add_argument("--url", required=True, help="Official website URL of the company to analyze")
    parser.add_argument("--max-pages", type=int, default=50, help="Maximum number of pages to crawl (default: 50)")
    parser.add_argument("--max-depth", type=int, default=3, help="Maximum crawl depth from starting page (default: 3)")
    parser.add_argument("--icp-config", help="Optional path to JSON file specifying ICP target criteria")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose debug logging")
    return parser.parse_args()

async def main_async():
    # Load environment configuration
    load_dotenv()
    
    args = parse_args()
    setup_logger("company_intelligence", verbose=args.verbose)
    
    start_time = datetime.datetime.now()
    
    # 1. Parse URL & Domain
    start_url = args.url
    parsed_url = urlparse(start_url)
    if not parsed_url.scheme:
        start_url = "https://" + start_url
        parsed_url = urlparse(start_url)
        
    domain = parsed_url.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
        
    domain_folder = domain.replace(".", "_").replace("-", "_")
    output_dir = os.path.join("output", domain_folder)
    
    logger.info(f"Target company URL: {start_url} (Domain: {domain})")
    
    # 2. Initialize Components
    url_manager = UrlManager(start_url, max_pages=args.max_pages, max_depth=args.max_depth)
    robots_parser = RobotsParser()
    crawler = WebCrawler(url_manager, robots_parser)
    page_extractor = PageExtractor(start_url)
    llm_extractor = LlmExtractor()
    web_searcher = WebSearcher()
    company_enricher = CompanyEnricher(web_searcher, llm_extractor)
    
    # 3. Setup Robots.txt and Sitemaps
    await robots_parser.fetch_robots(start_url)
    await crawler.initialize()
    
    # Seed queue with Sitemap URLs
    logger.info("Checking sitemaps...")
    sitemap_urls = await crawler.fetch_sitemap_urls()
    for s_url in sitemap_urls:
        url_manager.add_url(s_url, depth=1, from_sitemap=True)
        
    # 4. BFS Crawling Loop
    crawled_count = 0
    pages_data_list = []
    
    # Track metrics for crawl_report.json
    http_status_codes = {}
    redirects = []
    duplicate_urls = []
    
    logger.info("Starting web crawl...")
    while url_manager.has_next():
        next_item = url_manager.get_next()
        if not next_item:
            break
            
        current_url, depth = next_item
        crawled_count += 1
        
        # Display progress on terminal exactly as required
        print(f"[{crawled_count}/{args.max_pages}] Crawling {current_url}")
        sys.stdout.flush()
        
        try:
            html = await crawler.crawl_page(current_url)
            if not html:
                url_manager.mark_failed(current_url, "Fetched empty content or blocked.")
                http_status_codes[current_url] = 404
                continue
                
            # Track success
            url_manager.mark_crawled(current_url)
            http_status_codes[current_url] = 200
            
            # Extract page components
            raw_extracted = page_extractor.extract(html, current_url)
            
            # Extract contact patterns
            emails = ContactExtractor.extract_emails(raw_extracted["content"])
            phones = ContactExtractor.extract_phones(raw_extracted["content"])
            
            page_data = PageData(
                url=current_url,
                canonical_url=raw_extracted["canonical_url"],
                title=raw_extracted["title"],
                page_type=raw_extracted["page_type"],
                content=raw_extracted["content"],
                emails=emails,
                phones=phones,
                links=raw_extracted["internal_links"]
            )
            pages_data_list.append(page_data)
            
            # Add discovered internal URLs to manager queue
            for link in raw_extracted["internal_links"]:
                url_manager.add_url(link, depth=depth + 1)
                
        except Exception as e:
            logger.error(f"Error crawling {current_url}: {e}")
            url_manager.mark_failed(current_url, str(e))
            http_status_codes[current_url] = 500
            
    await crawler.close()
    
    # Print crawl statistics exactly as requested
    stats = url_manager.get_stats()
    print("\nPages discovered:", stats["pages_discovered"])
    print("Pages crawled:", stats["pages_crawled"])
    print("Pages failed:", stats["pages_failed"])
    sys.stdout.flush()
    
    # 5. Extract structured company data using LLM
    logger.info("Analyzing crawled pages for company data...")
    
    # Build text block from high-value pages
    high_value_types = ["homepage", "about", "products", "services", "solutions", "team", "leadership", "contact"]
    summary_pages = [p for p in pages_data_list if p.page_type in high_value_types]
    if not summary_pages:
        summary_pages = pages_data_list[:5] # Fallback to first few pages
        
    crawled_text_block = ""
    for p in summary_pages:
        crawled_text_block += f"=== PAGE URL: {p.url} (Type: {p.page_type}) ===\n"
        crawled_text_block += f"Title: {p.title}\n"
        crawled_text_block += f"Content:\n{p.content[:8000]}\n\n" # Truncate individual page content if too long
        
    # Create main report model
    end_time = datetime.datetime.now()
    crawl_duration = str(end_time - start_time)
    
    metadata = CrawlMetadata(
        input_url=start_url,
        domain=domain,
        crawl_started=start_time.isoformat(),
        crawl_completed=end_time.isoformat(),
        pages_discovered=stats["pages_discovered"],
        pages_crawled=stats["pages_crawled"],
        pages_failed=stats["pages_failed"]
    )
    
    report = CompanyIntelligenceReport(metadata=metadata, pages=pages_data_list)
    
    # Set default URL for source attribution
    home_url = start_url
    
    # Run LLM structured extraction if LLM is active
    if llm_extractor.is_active():
        try:
            llm_result = await llm_extractor.extract_company_data(crawled_text_block)
            if llm_result:
                # Map LLM results into report
                co = llm_result.company
                report.company.name = EnrichedField.create(co.name or domain, home_url)
                report.company.legal_name = EnrichedField.create(co.legal_name or "", home_url)
                report.company.description = EnrichedField.create(co.description or "", home_url)
                report.company.industry = EnrichedField.create(co.industry or "", home_url)
                report.company.sub_industry = EnrichedField.create(co.sub_industry or "", home_url)
                report.company.founded_year = EnrichedField.create(co.founded_year or None, home_url)
                report.company.company_type = EnrichedField.create(co.company_type or "", home_url)
                report.company.headquarters = EnrichedField.create(co.headquarters or "", home_url)
                report.company.locations = EnrichedField.create(co.locations or [], home_url)
                report.company.employee_count = EnrichedField.create(co.employee_count or None, home_url)
                report.company.company_size = EnrichedField.create(co.company_size or "", home_url)
                report.company.revenue = EnrichedField.create(co.revenue or "", home_url)
                report.company.parent_company = EnrichedField.create(co.parent_company or "", home_url)
                report.company.subsidiaries = EnrichedField.create(co.subsidiaries or [], home_url)
                
                # Add arrays
                for p in llm_result.products:
                    report.products.append(ProductServiceItem(name=p.name, description=p.description, source=home_url))
                for s in llm_result.services:
                    report.services.append(ProductServiceItem(name=s.name, description=s.description, source=home_url))
                for sol in llm_result.solutions:
                    report.solutions.append(ProductServiceItem(name=sol.name, description=sol.description, source=home_url))
                for t in llm_result.technologies:
                    report.technologies.append(t)
                for cust in llm_result.customers:
                    report.customers.append(CustomerItem(name=cust, source=home_url))
                for part in llm_result.partners:
                    report.partners.append(PartnerItem(name=part, source=home_url))
                for comp in llm_result.competitors:
                    report.competitors.append(CompetitorItem(name=comp.name, reason=comp.reason, source=home_url))
                for lead in llm_result.leadership:
                    report.leadership.append(LeadershipItem(name=lead.name, role=lead.role, source=home_url))
                for cert in llm_result.certifications:
                    report.certifications.append(CertificationItem(name=cert, source=home_url))
                for a in llm_result.awards:
                    report.awards.append(AwardItem(name=a, source=home_url))
                    
        except Exception as e:
            logger.error(f"Failed parsing company data with LLM: {e}")
            
    # Parse local contacts from crawled pages
    all_emails = []
    all_phones = []
    all_links = []
    for page in pages_data_list:
        all_emails.extend(page.emails)
        all_phones.extend(page.phones)
        all_links.extend(page.links)
        
    report.contact_information.emails = deduplicate_contacts(all_emails)
    report.contact_information.phones = deduplicate_contacts(all_phones)
    
    # Extract social URLs
    report.social_media = ContactExtractor.extract_socials(all_links)
    
    # If name still not set, fallback to title of homepage
    if not report.company.name.value:
        homepage = next((p for p in pages_data_list if p.page_type == "homepage"), None)
        h_title = homepage.title if homepage else domain
        report.company.name = EnrichedField.create(h_title, home_url)
        
    # 6. Web Enrichment
    logger.info("Executing external enrichment searches...")
    try:
        report = await company_enricher.enrich(report)
    except Exception as e:
        logger.error(f"Enrichment layer failed: {e}")
        
    # 7. Deduplicate Lists
    report.technologies = deduplicate_strings(report.technologies)
    report.industries_served = deduplicate_strings(report.industries_served)
    
    # 8. ICP Qualification
    if args.icp_config:
        try:
            logger.info(f"Loading ICP configuration from {args.icp_config} ...")
            with open(args.icp_config, "r", encoding="utf-8") as f:
                icp_criteria = json.load(f)
            evaluator = IcpEvaluator(icp_criteria)
            evaluator.evaluate(report)
        except Exception as e:
            logger.error(f"Failed to qualify company ICP: {e}")
            
    # 9. Calculate Overall Profile Data Quality & Confidence
    SourceValidator.calculate_confidence(report)
    
    # 10. Save Outputs
    print("Company extraction completed.\n")
    sys.stdout.flush()
    
    # JSON Data Exporter
    JsonExporter.export(report, output_dir)
    print(f"JSON saved:\n{os.path.join(output_dir, 'company_data.json')}")
    
    # Word Docx Exporter
    DocxExporter.export(report, output_dir)
    print(f"DOCX saved:\n{os.path.join(output_dir, 'company_report.docx')}")
    
    # Save crawl report
    crawl_stats = {
        "starting_url": start_url,
        "domain": domain,
        "pages_discovered": stats["pages_discovered"],
        "pages_crawled": stats["pages_crawled"],
        "pages_failed": stats["pages_failed"],
        "crawl_duration": crawl_duration,
        "failed_urls": stats["failed_urls"],
        "http_status_codes": http_status_codes,
        "redirects": redirects,
        "duplicate_urls": duplicate_urls,
        "external_urls_ignored_count": stats["ignored_urls_count"]
    }
    JsonExporter.export_crawl_report(crawl_stats, output_dir)
    
    sys.stdout.flush()

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
