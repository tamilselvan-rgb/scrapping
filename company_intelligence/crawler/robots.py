import logging
import urllib.robotparser
from urllib.parse import urlparse
import httpx

logger = logging.getLogger("company_intelligence.crawler.robots")

class RobotsParser:
    def __init__(self, user_agent: str = "*"):
        self.user_agent = user_agent
        self.parser = urllib.robotparser.RobotFileParser()
        self.robots_url = ""
        self.has_robots = False
        self.crawl_delay = None

    async def fetch_robots(self, base_url: str):
        """
        Asynchronously fetches the robots.txt file for a given site
        and parses it using RobotFileParser.
        """
        parsed_base = urlparse(base_url)
        self.robots_url = f"{parsed_base.scheme}://{parsed_base.netloc}/robots.txt"
        
        logger.debug(f"Attempting to fetch robots.txt from {self.robots_url}")
        
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                headers = {"User-Agent": "CompanyIntelligenceBot/1.0"}
                response = await client.get(self.robots_url, headers=headers)
                
                if response.status_code == 200:
                    lines = response.text.splitlines()
                    self.parser.parse(lines)
                    self.has_robots = True
                    logger.info(f"Loaded robots.txt successfully from {self.robots_url}")
                    
                    # Read crawl delay if specified
                    try:
                        delay = self.parser.crawl_delay(self.user_agent)
                        if delay:
                            self.crawl_delay = float(delay)
                            logger.info(f"Detected crawl delay from robots.txt: {self.crawl_delay}s")
                    except Exception:
                        pass
                else:
                    logger.debug(f"No robots.txt found (status {response.status_code})")
        except Exception as e:
            logger.debug(f"Error fetching robots.txt: {e}")
            
    def can_fetch(self, url: str) -> bool:
        """
        Returns True if the URL can be crawled according to robots.txt.
        If robots.txt could not be fetched or parsed, defaults to True.
        """
        if not self.has_robots:
            return True
        return self.parser.can_fetch(self.user_agent, url)

    def get_crawl_delay(self) -> float:
        """
        Returns the crawl delay in seconds, defaulting to 0.0 if not specified.
        """
        return self.crawl_delay if self.crawl_delay else 0.0
