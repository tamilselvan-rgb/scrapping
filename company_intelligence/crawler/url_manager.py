import logging
from collections import deque
from typing import Set, Dict, Tuple, Optional
from utils.url_utils import normalize_url, is_internal_url, should_ignore_url, get_domain

logger = logging.getLogger("company_intelligence.crawler.url_manager")

class UrlManager:
    def __init__(self, start_url: str, max_pages: int = 100, max_depth: int = 5):
        self.start_url = normalize_url(start_url)
        self.base_domain = get_domain(self.start_url)
        self.max_pages = max_pages
        self.max_depth = max_depth
        
        # State tracking
        self.discovered_urls: Set[str] = set()
        self.crawled_urls: Set[str] = set()
        self.failed_urls: Dict[str, str] = {} # url -> error message
        self.ignored_urls: Set[str] = set()
        
        # BFS Queue: stores tuple of (normalized_url, depth)
        self.queue = deque()
        
        # Add the start URL
        if self.start_url:
            self.add_url(self.start_url, depth=0)
        else:
            logger.error(f"Invalid start URL: {start_url}")

    def add_url(self, url: str, depth: int, from_sitemap: bool = False) -> bool:
        """
        Normalizes a URL and adds it to the queue if it's internal, not ignored,
        and doesn't exceed maximum depth or page limit.
        """
        normalized = normalize_url(url, self.start_url)
        if not normalized:
            return False
            
        # Ignore external domains
        if not is_internal_url(normalized, self.start_url):
            self.ignored_urls.add(normalized)
            return False
            
        # Ignore file assets (images, css, pdfs, etc.)
        if should_ignore_url(normalized):
            self.ignored_urls.add(normalized)
            return False
            
        # Check limits
        if normalized in self.discovered_urls:
            return False
            
        if len(self.crawled_urls) + len(self.queue) >= self.max_pages:
            logger.debug(f"Skipping {normalized}: Max pages limit reached ({self.max_pages})")
            return False
            
        if depth > self.max_depth:
            logger.debug(f"Skipping {normalized}: Max depth limit reached ({depth} > {self.max_depth})")
            return False
            
        self.discovered_urls.add(normalized)
        
        # If it's from sitemap, we append it with depth 1 since it's directly discovered
        actual_depth = 1 if from_sitemap else depth
        self.queue.append((normalized, actual_depth))
        logger.debug(f"Added to queue (depth {actual_depth}): {normalized}")
        return True

    def get_next(self) -> Optional[Tuple[str, int]]:
        """
        Pops the next URL and depth from the BFS queue.
        """
        if self.queue:
            return self.queue.popleft()
        return None

    def has_next(self) -> bool:
        """
        Returns True if the queue is not empty.
        """
        return len(self.queue) > 0

    def mark_crawled(self, url: str):
        """
        Marks a URL as successfully crawled.
        """
        self.crawled_urls.add(url)

    def mark_failed(self, url: str, error_message: str):
        """
        Marks a URL as failed with the error message.
        """
        self.failed_urls[url] = error_message

    def get_stats(self) -> dict:
        """
        Returns stats for logs and reports.
        """
        return {
            "start_url": self.start_url,
            "domain": self.base_domain,
            "pages_discovered": len(self.discovered_urls),
            "pages_crawled": len(self.crawled_urls),
            "pages_failed": len(self.failed_urls),
            "failed_urls": self.failed_urls,
            "ignored_urls_count": len(self.ignored_urls)
        }
