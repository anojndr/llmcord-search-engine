"""
Search Service Module

Implements web search functionality using SearxNG as the main provider, with fallbacks to Serper API and Bing API.
Defines a SearchResult data class to represent individual search hits.
"""

import os
import logging
from typing import Any, Dict, Optional, List, Tuple
import httpx
from dataclasses import dataclass
from urllib.parse import urljoin, quote
from api_key_manager import APIKeyManager
from searxng_config import get_searxng_config

logger = logging.getLogger(__name__)

@dataclass
class SearchResult:
    """
    Data class representing a single search result.

    Attributes:
        url: URL of the search result.
        title: Title of the result.
        snippet: A brief snippet or summary.
    """
    url: str
    title: str
    snippet: str

class SearchService:
    """
    Service class for handling search queries.

    This service attempts to perform a search with SearxNG first, then falls back
    to Serper API and finally Bing API if needed.
    """
    api_key_manager: APIKeyManager
    httpx_client: httpx.AsyncClient
    searxng_config: Dict[str, Any]

    def __init__(self, api_key_manager: APIKeyManager, httpx_client: httpx.AsyncClient) -> None:
        """
        Initialize SearchService with an API key manager and HTTP client.

        Args:
            api_key_manager: API key manager instance.
            httpx_client: HTTP client.
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
        Search using SearxNG.

        Constructs the SearxNG URL from configuration, makes the HTTP request, and parses the JSON response.

        Args:
            query: Search query.
            max_urls: Maximum results to retrieve.

        Returns:
            Tuple containing either:
              - A list of SearchResult objects.
              - Or an error message if something went wrong.
        """
        try:
            language: str = self.searxng_config['language'].split('#')[0].strip()
            categories: str = self.searxng_config['categories'].split('#')[0].strip()

            params: Dict[str, Any] = {
                'q': query,
                'format': 'json',
                'pageno': 1,
                'language': language,
                'safesearch': self.searxng_config['safe_search'],
                'categories': categories
            }

            base_url: str = urljoin(self.searxng_config['base_url'], 'search')
            param_strings: List[str] = []
            for key, value in params.items():
                encoded_key: str = quote(str(key))
                encoded_value: str = quote(str(value))
                param_strings.append(f"{encoded_key}={encoded_value}")
            url: str = f"{base_url}?{'&'.join(param_strings)}"

            logger.info(f"Making SearxNG request to: {url}")

            response: httpx.Response = await self.httpx_client.get(
                url,
                timeout=self.searxng_config['timeout']
            )
            response.raise_for_status()

            data: Dict[str, Any] = response.json()
            if not data.get('results'):
                return None, "No results found from SearxNG"

            results: List[SearchResult] = []
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
        Perform a search using the Serper API as a fallback.

        Args:
            query: Search query.
            max_urls: Maximum number of results.

        Returns:
            Tuple containing the list of SearchResult or an error message.
        """
        try:
            api_key: Optional[str] = await self.api_key_manager.get_next_api_key('serper')
            if not api_key:
                return None, "No Serper API key available"

            params: Dict[str, Any] = {
                'q': query,
                'num': max_urls,
                'autocorrect': 'false',
                'apiKey': api_key
            }

            response: httpx.Response = await self.httpx_client.get(
                'https://google.serper.dev/search',
                params=params
            )
            response.raise_for_status()

            data: Dict[str, Any] = response.json()
            results: List[SearchResult] = []

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
        Perform a search using the Bing API as the final fallback.

        Args:
            query: The search query.
            max_urls: Maximum results to return.

        Returns:
            Tuple containing a list of SearchResult objects or an error message.
        """
        try:
            subscription_key: Optional[str] = os.getenv('BING_SEARCH_V7_SUBSCRIPTION_KEY')
            endpoint: Optional[str] = os.getenv('BING_SEARCH_V7_ENDPOINT')

            if not subscription_key or not endpoint:
                return None, "Bing API credentials missing from environment variables"

            headers: Dict[str, str] = {'Ocp-Apim-Subscription-Key': subscription_key}
            params: Dict[str, Any] = {
                'q': query,
                'mkt': 'en-US',
                'count': max_urls,
                'responseFilter': 'Webpages'
            }

            response: httpx.Response = await self.httpx_client.get(
                f"{endpoint.rstrip('/')}/v7.0/search",
                headers=headers,
                params=params
            )
            response.raise_for_status()

            data: Dict[str, Any] = response.json()
            results: List[SearchResult] = []

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
        Perform a search across all providers with fallback logic.

        The order of attempts is:
            1. SearxNG
            2. Serper API
            3. Bing API

        Args:
            query: The search query.
            max_urls: Maximum results for each attempt.

        Returns:
            Tuple[List[SearchResult], List[str]]:
              - A list of search results.
              - A list of error messages encountered during the search attempts.
        """
        errors: List[str] = []

        results: Optional[List[SearchResult]]
        error: Optional[str]
        results, error = await self.search_with_searxng(query, max_urls)
        if results:
            return results, errors
        if error:
            errors.append(error)

        results, error = await self.search_with_serper(query, max_urls)
        if results:
            return results, errors
        if error:
            errors.append(error)

        results, error = await self.search_with_bing(query, max_urls)
        if results:
            return results, errors
        if error:
            errors.append(error)

        return [], errors