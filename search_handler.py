"""
Search Handler Module

Delegates search queries to the SearchService and then wraps the results
(and any errors) in a structured plain text format.
"""

import logging
from typing import Dict, Any, Optional, List
import httpx

from search_service import SearchService
from url_handler import fetch_urls_content

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


async def handle_search_query(query: str, api_key_manager, httpx_client: httpx.AsyncClient, config: Optional[Dict[str, Any]] = None) -> str:
    """
    Perform a search using multiple providers with fallback logic, and combine the results
    into plain text.

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


async def handle_search_queries(
    queries: List[str],
    api_key_manager,
    httpx_client: httpx.AsyncClient,
    config: dict = None
) -> str:
    """
    Perform a search on multiple queries, gather all results,
    deduplicate them by URL, fetch the page content for each unique URL,
    and return a formatted plain text summary.

    Args:
        queries (List[str]): List of search queries.
        api_key_manager: API key manager instance.
        httpx_client (httpx.AsyncClient): HTTP client for web requests.
        config (dict, optional): Additional configuration options.

    Returns:
        str: A plain text string containing aggregated search results.
    """
    config = config or {}
    max_urls = config.get("max_urls", 5)
    search_service = SearchService(api_key_manager, httpx_client)
    aggregated_results = {}
    errors = []

    # For each query, fetch its results.
    for query in queries:
        results, error = await search_service.search(query, max_urls)
        if error:
            errors.append(f"Query '{query}': {error}")
        # Add all returned results and deduplicate by URL.
        for res in results:
            if res.url not in aggregated_results:
                aggregated_results[res.url] = res

    dedup_results = list(aggregated_results.values())

    if not dedup_results:
        return "No search results found from any provider."

    # Gather all the unique URLs to fetch their content.
    url_list = [res.url for res in dedup_results]
    contents = await fetch_urls_content(url_list, api_key_manager, httpx_client, config=config)

    # Format the aggregated results.
    lines = []
    if errors:
        lines.append("Error Messages:")
        for err in errors:
            lines.append(f" - {err}")
        lines.append("")
    lines.append("Aggregated Search Results:")

    for idx, (res, content) in enumerate(zip(dedup_results, contents), start=1):
        lines.append(f"Result {idx}:")
        lines.append(f"  URL: {res.url}")
        lines.append(f"  Title: {res.title}")
        lines.append(f"  Snippet: {res.snippet}")
        lines.append("  Fetched Content:")
        lines.append(content)
        lines.append("")
    return "\n".join(lines)