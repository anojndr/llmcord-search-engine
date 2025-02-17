"""
Search Handler Module

Delegates search queries to the SearchService and then wraps the results
(and any errors) in a structured plain text format.
"""

import logging
from typing import Dict, Any, Optional
import httpx

from search_service import SearchService
from url_handler import fetch_urls_content

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


async def handle_search_query(query: str, api_key_manager, httpx_client: httpx.AsyncClient, config: Optional[Dict[str, Any]] = None) -> str:
    """
    Perform a search using multiple providers with fallback logic, and combine the results into plain text.

    Args:
        query (str): The search query.
        api_key_manager: API key manager instance.
        httpx_client (httpx.AsyncClient): HTTP client for web requests.
        config (dict, optional): Additional configuration options.

    Returns:
        str: A plain text string containing search results.
    """
    if config is None:
        config = {}

    max_urls = config.get('max_urls', 5)
    search_service = SearchService(api_key_manager, httpx_client)
    
    results, errors = await search_service.search(query, max_urls)
    
    lines = []
    if errors:
        lines.append("Error Messages:")
        for error in errors:
            lines.append(f" - {error}")
        lines.append("")
    if not results:
        lines.append("No search results found from any provider.")
        return "\n".join(lines)
    
    # Extract the URLs from the search results and fetch their page content.
    url_list = [result.url for result in results]
    contents = await fetch_urls_content(url_list, api_key_manager, httpx_client, config=config)
    
    lines.append("Search Results:")
    for idx, (result, content) in enumerate(zip(results, contents), start=1):
        lines.append(f"Result {idx}:")
        lines.append(f"  URL: {result.url}")
        lines.append(f"  Title: {result.title}")
        lines.append(f"  Snippet: {result.snippet}")
        lines.append("  Fetched Content:")
        lines.append(content)
        lines.append("")
    return "\n".join(lines)