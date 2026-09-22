import logging
import asyncio
from typing import List, Optional
from bs4 import BeautifulSoup
import httpx
from urllib.parse import urlparse

from .url_manager import UrlManager
from .robots import RobotsParser

logger = logging.getLogger("company_intelligence.crawler.crawler")

# Optional crawl4ai imports
CRAWL4AI_AVAILABLE = False
try:
    from crawl4ai import AsyncWebCrawler
    from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig
    CRAWL4AI_AVAILABLE = True
    logger.info("Crawl4AI library loaded successfully.")
except ImportError:
    logger.warning("Crawl4AI not installed or failed to import. Crawling will fallback to direct Playwright/HTTPX.")

# Playwright fallback imports
from playwright.async_api import async_playwright

class WebCrawler:
    def __init__(self, url_manager: UrlManager, robots_parser: RobotsParser, user_agent: str = "CompanyIntelligenceBot/1.0"):
        self.url_manager = url_manager
        self.robots_parser = robots_parser
        self.user_agent = user_agent
        
        # Playwright resources for fallback
        self.playwright = None
        self.browser = None
        
        # Crawl4AI resources
        self.crawl4ai_crawler = None

    async def initialize(self):
        """
        Initializes crawling engines.
        """
        # Start crawl4ai if available
        if CRAWL4AI_AVAILABLE:
            try:
                self.crawl4ai_crawler = AsyncWebCrawler()
                await self.crawl4ai_crawler.start()
                logger.info("Crawl4AI AsyncWebCrawler started.")
                return
            except Exception as e:
                logger.error(f"Failed to start Crawl4AI crawler: {e}. Falling back to Playwright.")
                self.crawl4ai_crawler = None

        # Playwright fallback initialization
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=True)
            logger.info("Playwright browser fallback initialized.")
        except Exception as e:
            logger.critical(f"Failed to initialize Playwright fallback: {e}")

    async def fetch_sitemap_urls(self) -> List[str]:
        """
        Tries to discover sitemap URLs from robots.txt or default locations,
        downloads and parses the sitemap.xml files.
        """
        domain = self.url_manager.base_domain
        start_url = self.url_manager.start_url
        parsed = urlparse(start_url)
        
        sitemap_urls = []
        # Check standard robots.txt parser for sitemaps if supported
        if self.robots_parser.has_robots:
            try:
                # urllib.robotparser does not expose sitemaps easily, so we check standard locations
                pass
            except Exception:
                pass
                
        # Candidate sitemap locations
        candidates = [
            f"{parsed.scheme}://{parsed.netloc}/sitemap.xml",
            f"{parsed.scheme}://{parsed.netloc}/sitemap_index.xml",
        ]
        
        discovered = []
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            for s_url in candidates:
                try:
                    logger.debug(f"Checking sitemap candidate: {s_url}")
                    response = await client.get(s_url, headers={"User-Agent": self.user_agent})
                    if response.status_code == 200:
                        logger.info(f"Discovered sitemap at: {s_url}")
                        soup = BeautifulSoup(response.content, "xml")
                        locs = soup.find_all("loc")
                        for loc in locs:
                            url = loc.text.strip()
                            if url:
                                discovered.append(url)
                except Exception as e:
                    logger.debug(f"Failed to check sitemap {s_url}: {e}")
                    
        return list(set(discovered))

    async def crawl_page(self, url: str) -> Optional[str]:
        """
        Crawls a page and returns its HTML.
        Attempts to use Crawl4AI first (if available), then falls back to direct Playwright,
        and finally falls back to simple httpx static fetches.
        """
        # Respect robots.txt
        if not self.robots_parser.can_fetch(url):
            logger.warning(f"URL disallowed by robots.txt: {url}")
            return None

        # Apply crawl delay
        delay = self.robots_parser.get_crawl_delay()
        if delay > 0:
            logger.debug(f"Sleeping for robots.txt crawl delay: {delay}s")
            await asyncio.sleep(delay)

        # 1. Try Crawl4AI
        if self.crawl4ai_crawler:
            try:
                logger.debug(f"Crawling using Crawl4AI: {url}")
                # Use Crawl4AI run config
                from crawl4ai.async_configs import CrawlerRunConfig
                config = CrawlerRunConfig(
                    cache_mode="BYPASS",
                    wait_until="networkidle",
                    page_timeout=30000
                )
                result = await self.crawl4ai_crawler.arun(url=url, config=config)
                if result.success and result.html:
                    return result.html
                else:
                    logger.warning(f"Crawl4AI failed for {url}: {result.error_message}. Trying fallback...")
            except Exception as e:
                logger.warning(f"Crawl4AI errored for {url}: {e}. Trying fallback...")

        # 2. Try Playwright Fallback
        if self.browser:
            try:
                logger.debug(f"Crawling using Playwright fallback: {url}")
                page = await self.browser.new_page()
                page.set_default_timeout(30000)
                
                # Navigate and wait
                response = await page.goto(url, wait_until="load")
                
                # Handle redirects (if location changed, we should know)
                # Wait for any js rendering
                await asyncio.sleep(1.0)
                
                html = await page.content()
                await page.close()
                return html
            except Exception as e:
                logger.warning(f"Playwright fallback failed for {url}: {e}. Trying static fetch...")

        # 3. Try HTTPX Fallback (Static page fetch)
        try:
            logger.debug(f"Crawling using HTTPX static fallback: {url}")
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                response = await client.get(url, headers={"User-Agent": self.user_agent})
                if response.status_code == 200:
                    return response.text
                else:
                    logger.warning(f"HTTPX fallback returned code {response.status_code} for {url}")
        except Exception as e:
            logger.error(f"All crawl methods failed for {url}: {e}")
            
        return None

    async def close(self):
        """
        Cleans up browser instances and connection clients.
        """
        if self.crawl4ai_crawler:
            try:
                await self.crawl4ai_crawler.close()
                logger.info("Crawl4AI crawler closed.")
            except Exception as e:
                logger.error(f"Error closing Crawl4AI: {e}")
                
        if self.browser:
            try:
                await self.browser.close()
                logger.info("Playwright browser closed.")
            except Exception as e:
                logger.error(f"Error closing Playwright browser: {e}")
                
        if self.playwright:
            try:
                await self.playwright.stop()
                logger.info("Playwright client stopped.")
            except Exception as e:
                logger.error(f"Error stopping Playwright: {e}")
