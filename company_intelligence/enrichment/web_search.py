import os
import logging
import asyncio
from typing import List, Dict, Any
import httpx

logger = logging.getLogger("company_intelligence.enrichment.web_search")

class WebSearcher:
    def __init__(self):
        self.serper_api_key = os.getenv("SERPER_API_KEY", "")
        if not self.serper_api_key:
            logger.warning("SERPER_API_KEY is empty. Falling back to DuckDuckGo search for enrichment.")

    async def search_serper(self, query: str, num_results: int = 5) -> List[Dict[str, Any]]:
        """
        Queries Google search via Serper API.
        """
        url = "https://google.serper.dev/search"
        payload = {
            "q": query,
            "num": num_results
        }
        headers = {
            "X-API-KEY": self.serper_api_key,
            "Content-Type": "application/json"
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    organic_results = data.get("organic", [])
                    
                    normalized = []
                    for r in organic_results[:num_results]:
                        normalized.append({
                            "title": r.get("title", ""),
                            "url": r.get("link", ""),
                            "snippet": r.get("snippet", "")
                        })
                    return normalized
                else:
                    logger.error(f"Serper API returned status code {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"Serper search failed: {e}")
            
        return []

    async def search_ddg(self, query: str, num_results: int = 5) -> List[Dict[str, Any]]:
        """
        Queries DuckDuckGo search as a fallback.
        """
        try:
            from duckduckgo_search import DDGS
            
            def run_sync_ddg():
                with DDGS() as ddgs:
                    return list(ddgs.text(query, max_results=num_results))
                    
            # Run blocking DDG client in a separate thread
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, run_sync_ddg)
            
            normalized = []
            for r in results:
                normalized.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", "")
                })
            return normalized
        except Exception as e:
            logger.error(f"DuckDuckGo search failed: {e}")
            
        return []

    async def search(self, query: str, num_results: int = 5) -> List[Dict[str, Any]]:
        """
        Main entry point for web searches. Tries Serper first (if key is set),
        falls back to DuckDuckGo if Serper key is missing or fails.
        """
        logger.info(f"Searching web for query: '{query}'")
        
        if self.serper_api_key:
            results = await self.search_serper(query, num_results)
            if results:
                return results
                
        # Fallback to DDG
        return await self.search_ddg(query, num_results)
