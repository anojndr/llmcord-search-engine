"""
Search service module implementing SearxNG, Serper, and Bing search functionality.
"""

import os
import logging
from typing import Dict, Any, Optional, List, Tuple
import httpx
from dataclasses import dataclass
from urllib.parse import urljoin

from searxng_config import get_searxng_config

logger = logging.getLogger(__name__)

@dataclass
class SearchResult:
    """Data class for storing individual search results."""
    url: str
    title: str
    snippet: str

class SearchService:
    """Service class handling search operations across multiple providers."""
    
    def __init__(self, api_key_manager, httpx_client: httpx.AsyncClient):
        """
        Initialize the search service.
        
        Args:
            api_key_manager: API key manager instance
            httpx_client (httpx.AsyncClient): HTTP client for making requests
        """
        self.api_key_manager = api_key_manager
        self.httpx_client = httpx_client
        self.searxng_config = get_searxng_config()
    
    async def search_with_searxng(
        self, 
        query: str, 
        max_urls: int = 5
    ) -> Tuple[Optional[List[SearchResult]], Optional[str]]:
        """
        Perform a search using SearxNG.
        
        Args:
            query (str): Search query
            max_urls (int): Maximum number of results
            
        Returns:
            Tuple[Optional[List[SearchResult]], Optional[str]]: Search results and error message
        """
        try:
            params = {
                'q': query,
                'format': 'json',
                'pageno': 1,
                'language': self.searxng_config['language'],
                'safesearch': self.searxng_config['safe_search'],
                'categories': self.searxng_config['categories']
            }
            
            response = await self.httpx_client.get(
                urljoin(self.searxng_config['base_url'], 'search'),
                params=params,
                timeout=self.searxng_config['timeout']
            )
            response.raise_for_status()
            
            data = response.json()
            if not data.get('results'):
                return None, "No results found from SearxNG"
                
            results = []
            for result in data['results'][:max_urls]:
                results.append(SearchResult(
                    url=result['url'],
                    title=result.get('title', 'No title'),
                    snippet=result.get('content', 'No snippet')
                ))
                
            return results, None
            
        except Exception as e:
            logger.error(f"SearxNG search error: {str(e)}")
            return None, f"SearxNG error: {str(e)}"
    
    async def search_with_serper(
        self, 
        query: str, 
        max_urls: int = 5
    ) -> Tuple[Optional[List[SearchResult]], Optional[str]]:
        """
        Perform a search using Serper API as fallback.
        
        Args:
            query (str): Search query
            max_urls (int): Maximum number of results
            
        Returns:
            Tuple[Optional[List[SearchResult]], Optional[str]]: Search results and error message
        """
        try:
            api_key = await self.api_key_manager.get_next_api_key('serper')
            if not api_key:
                return None, "No Serper API key available"
                
            params = {
                'q': query,
                'num': max_urls,
                'autocorrect': 'false',
                'apiKey': api_key
            }
            
            response = await self.httpx_client.get(
                'https://google.serper.dev/search',
                params=params
            )
            response.raise_for_status()
            
            data = response.json()
            results = []
            
            for result in data.get('organic', [])[:max_urls]:
                if 'link' in result:
                    results.append(SearchResult(
                        url=result['link'],
                        title=result.get('title', 'No title'),
                        snippet=result.get('snippet', 'No snippet')
                    ))
                    
            return results, None
            
        except Exception as e:
            logger.error(f"Serper API error: {str(e)}")
            return None, f"Serper API error: {str(e)}"
    
    async def search_with_bing(
        self, 
        query: str, 
        max_urls: int = 5
    ) -> Tuple[Optional[List[SearchResult]], Optional[str]]:
        """
        Perform a search using Bing API as final fallback.
        
        Args:
            query (str): Search query
            max_urls (int): Maximum number of results
            
        Returns:
            Tuple[Optional[List[SearchResult]], Optional[str]]: Search results and error message
        """
        try:
            subscription_key = os.getenv('BING_SEARCH_V7_SUBSCRIPTION_KEY')
            endpoint = os.getenv('BING_SEARCH_V7_ENDPOINT')
            
            if not subscription_key or not endpoint:
                return None, "Bing API credentials missing from environment variables"
                
            headers = {'Ocp-Apim-Subscription-Key': subscription_key}
            params = {
                'q': query,
                'mkt': 'en-US',
                'count': max_urls,
                'responseFilter': 'Webpages'
            }
            
            response = await self.httpx_client.get(
                f"{endpoint.rstrip('/')}/v7.0/search",
                headers=headers,
                params=params
            )
            response.raise_for_status()
            
            data = response.json()
            results = []
            
            for page in data.get('webPages', {}).get('value', [])[:max_urls]:
                if 'url' in page:
                    results.append(SearchResult(
                        url=page['url'],
                        title=page.get('name', 'No title'),
                        snippet=page.get('snippet', 'No snippet')
                    ))
                    
            return results, None
            
        except Exception as e:
            logger.error(f"Bing API error: {str(e)}")
            return None, f"Bing API error: {str(e)}"
    
    async def search(
        self, 
        query: str, 
        max_urls: int = 5
    ) -> Tuple[List[SearchResult], List[str]]:
        """
        Perform search across all providers with fallback logic.
        
        Args:
            query (str): Search query
            max_urls (int): Maximum number of results
            
        Returns:
            Tuple[List[SearchResult], List[str]]: Search results and error messages
        """
        errors = []
        
        # Try SearxNG first
        results, error = await self.search_with_searxng(query, max_urls)
        if results:
            return results, errors
        if error:
            errors.append(error)
            
        # Try Serper as first fallback
        results, error = await self.search_with_serper(query, max_urls)
        if results:
            return results, errors
        if error:
            errors.append(error)
            
        # Try Bing as final fallback
        results, error = await self.search_with_bing(query, max_urls)
        if results:
            return results, errors
        if error:
            errors.append(error)
            
        # If all providers failed, return empty results
        return [], errors