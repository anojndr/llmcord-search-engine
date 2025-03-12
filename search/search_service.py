"""
Search Service Module

Implements web search functionality using SearxNG as the main provider, with fallbacks to Serper API and Bing API.
Defines a SearchResult data class to represent individual search hits.
"""

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, quote

import httpx

from config.api_key_manager import APIKeyManager
from config.searxng_config import get_searxng_config

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


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
    
    def __init__(
        self, 
        api_key_manager: APIKeyManager, 
        httpx_client: httpx.AsyncClient
    ) -> None:
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
            # Parse configuration
            language = self.searxng_config['language'].split('#')[0].strip()
            categories = self.searxng_config['categories'].split('#')[0].strip()

            # Prepare parameters
            params: Dict[str, Any] = {
                'q': query,
                'format': 'json',
                'pageno': 1,
                'language': language,
                'safesearch': self.searxng_config['safe_search'],
                'categories': categories
            }

            # Build URL with properly encoded parameters
            base_url = urljoin(self.searxng_config['base_url'], 'search')
            param_strings = []
            for key, value in params.items():
                encoded_key = quote(str(key))
                encoded_value = quote(str(value))
                param_strings.append(f"{encoded_key}={encoded_value}")
            url = f"{base_url}?{'&'.join(param_strings)}"

            logger.info(f"Making SearxNG request to: {url}")

            # Send request
            response = await self.httpx_client.get(
                url,
                timeout=self.searxng_config['timeout']
            )
            response.raise_for_status()

            # Process response
            data = response.json()
            if not data.get('results'):
                logger.warning(f"No results found from SearxNG for query: {query}")
                return None, "No results found from SearxNG"

            # Convert results to SearchResult objects
            results = []
            for result in data['results'][:max_urls]:
                results.append(SearchResult(
                    url=result['url'],
                    title=result.get('title', 'No title'),
                    snippet=result.get('content', 'No snippet')
                ))

            logger.info(
                f"SearxNG search returned {len(results)} results for query: {query}"
            )
            return results, None

        except Exception as e:
            logger.error(
                f"SearxNG search error for query '{query}': {str(e)}", 
                exc_info=True
            )
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
            # Get API key
            api_key = await self.api_key_manager.get_next_api_key('serper')
            if not api_key:
                logger.warning(f"No Serper API key available for query: {query}")
                return None, "No Serper API key available"

            # Prepare request
            params: Dict[str, Any] = {
                'q': query,
                'num': max_urls,
                'autocorrect': 'false',
                'apiKey': api_key
            }

            # Send request
            logger.info(f"Making Serper API request for query: {query}")
            response = await self.httpx_client.get(
                'https://google.serper.dev/search',
                params=params
            )
            response.raise_for_status()

            # Process response
            data = response.json()
            results = []

            for result in data.get('organic', [])[:max_urls]:
                if 'link' in result:
                    results.append(SearchResult(
                        url=result['link'],
                        title=result.get('title', 'No title'),
                        snippet=result.get('snippet', 'No snippet')
                    ))

            logger.info(
                f"Serper API search returned {len(results)} results for query: {query}"
            )
            return results, None

        except Exception as e:
            logger.error(
                f"Serper API error for query '{query}': {str(e)}", 
                exc_info=True
            )
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
            # Get API credentials
            subscription_key = os.getenv('BING_SEARCH_V7_SUBSCRIPTION_KEY')
            endpoint = os.getenv('BING_SEARCH_V7_ENDPOINT')

            if not subscription_key or not endpoint:
                logger.warning(
                    f"Bing API credentials missing from environment variables "
                    f"for query: {query}"
                )
                return None, "Bing API credentials missing from environment variables"

            # Prepare request
            headers = {'Ocp-Apim-Subscription-Key': subscription_key}
            params = {
                'q': query,
                'mkt': 'en-US',
                'count': max_urls,
                'responseFilter': 'Webpages'
            }

            # Send request
            logger.info(f"Making Bing API request for query: {query}")
            response = await self.httpx_client.get(
                f"{endpoint.rstrip('/')}/v7.0/search",
                headers=headers,
                params=params
            )
            response.raise_for_status()

            # Process response
            data = response.json()
            results = []

            for page in data.get('webPages', {}).get('value', [])[:max_urls]:
                if 'url' in page:
                    results.append(SearchResult(
                        url=page['url'],
                        title=page.get('name', 'No title'),
                        snippet=page.get('snippet', 'No snippet')
                    ))

            logger.info(
                f"Bing API search returned {len(results)} results for query: {query}"
            )
            return results, None

        except Exception as e:
            logger.error(
                f"Bing API error for query '{query}': {str(e)}", 
                exc_info=True
            )
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

        logger.warning(f"All search providers failed for query: {query}")
        return [], errors