import httpx
import logging
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any
from utils.retry import retry_async

logger = logging.getLogger("scraper.http_crawler")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive"
}

class HttpCrawler:
    def __init__(self, concurrency: int = 10, timeout: float = 30.0, headers: Optional[Dict[str, str]] = None):
        self.concurrency_limit = asyncio_semaphore = None  # Handled externally or inside client call
        self.timeout = timeout
        self.headers = headers or DEFAULT_HEADERS
        self.client: Optional[httpx.AsyncClient] = None
        self.semaphore = None # Will initialize dynamically

    async def get_client(self) -> httpx.AsyncClient:
        if self.client is None or self.client.is_closed:
            self.client = httpx.AsyncClient(
                headers=self.headers,
                timeout=self.timeout,
                follow_redirects=True,
                verify=False # Ignore cert errors to be robust
            )
        return self.client

    async def fetch_html(self, url: str) -> Optional[str]:
        """
        Fetches the HTML content of a URL.
        Includes retry logic for transient HTTP issues (429, 500, 502, 503, 504, timeout).
        """
        async def _fetch():
            client = await self.get_client()
            response = await client.get(url)
            response.raise_for_status()
            return response.text

        try:
            # Wrap the _fetch method in our exponential backoff retry helper
            html = await retry_async(
                _fetch,
                retries=3,
                initial_delay=2.0,
                backoff_factor=2.0,
                exceptions=(httpx.HTTPError, httpx.TimeoutException)
            )
            return html
        except Exception as e:
            logger.error(f"Failed to fetch URL {url} via HTTP: {e}")
            return None

    async def fetch_soup(self, url: str) -> Optional[BeautifulSoup]:
        """
        Fetches the URL and returns a BeautifulSoup object.
        """
        html = await self.fetch_html(url)
        if html:
            return BeautifulSoup(html, 'lxml')
        return None

    async def close(self):
        if self.client and not self.client.is_closed:
            await self.client.aclose()
