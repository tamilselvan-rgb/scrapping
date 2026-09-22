import asyncio
import logging
from typing import Optional, List, Callable, Any
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger("scraper.playwright_crawler")

class PlaywrightCrawler:
    def __init__(self, headless: bool = True, timeout: float = 30000.0):
        self.headless = headless
        self.timeout = timeout
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None

    async def start(self):
        """
        Starts the Playwright browser session.
        """
        if not self.browser:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless,
                args=["--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage"]
            )
            # Create a reusable context
            self.context = await self.browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
                )
            )
            self.context.set_default_timeout(self.timeout)

    async def stop(self):
        """
        Stops the browser session.
        """
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
            
        self.browser = None
        self.context = None
        self.playwright = None

    async def get_page(self) -> Page:
        """
        Creates and returns a new page in the shared context.
        """
        if not self.context:
            await self.start()
        return await self.context.new_page()

    async def fetch_html_dynamic(
        self, 
        url: str, 
        wait_selector: Optional[str] = None, 
        scroll: bool = False,
        click_selector: Optional[str] = None,
        max_clicks: int = 10
    ) -> Optional[str]:
        """
        Loads the page dynamically, handles waiting, scrolling, or clicking.
        """
        page = None
        try:
            page = await self.get_page()
            logger.info(f"Navigating browser to: {url}")
            await page.goto(url, wait_until="domcontentloaded")
            
            # Wait for specific selector if requested
            if wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=10000)
                except Exception:
                    logger.warning(f"Timeout waiting for selector {wait_selector}")
                    
            # Perform scroll to bottom if infinite scroll
            if scroll:
                await self.scroll_to_bottom(page)
                
            # Perform click paging if requested
            if click_selector:
                await self.click_element_repeatedly(page, click_selector, max_clicks)
                
            html = await page.content()
            return html
        except Exception as e:
            logger.error(f"Error loading {url} dynamically: {e}")
            return None
        finally:
            if page:
                await page.close()

    async def scroll_to_bottom(self, page: Page, max_scrolls: int = 20, delay: float = 1.0):
        """
        Scrolls down the page repeatedly to trigger infinite scroll.
        """
        logger.info("Scrolling page to trigger infinite load...")
        last_height = await page.evaluate("document.body.scrollHeight")
        for i in range(max_scrolls):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
            await asyncio.sleep(delay)
            new_height = await page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                # Try scrolling slightly up and down to trigger lazy load events
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight - 500);")
                await asyncio.sleep(0.3)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                await asyncio.sleep(delay)
                new_height = await page.evaluate("document.body.scrollHeight")
                if new_height == last_height:
                    break
            last_height = new_height

    async def click_element_repeatedly(self, page: Page, selector: str, max_clicks: int = 15, delay: float = 1.5):
        """
        Repeatedly clicks a button (e.g. Load More) until it's no longer visible or clickable.
        """
        logger.info(f"Clicking 'Load More' element ({selector}) repeatedly...")
        for i in range(max_clicks):
            try:
                button = page.locator(selector).first
                if not button or not await button.is_visible() or not await button.is_enabled():
                    logger.info("Load more button is no longer active.")
                    break
                await button.scroll_into_view_if_needed()
                await button.click()
                await asyncio.sleep(delay)
            except Exception as e:
                logger.debug(f"Clicking locator failed or finished: {e}")
                break
