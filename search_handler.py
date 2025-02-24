"""
Search Handler Module

Delegates search queries to the SearchService and then wraps the results
(and any errors) in a structured plain text format.
"""

import logging
from typing import Dict, Any, Optional, List
import httpx
from api_key_manager import APIKeyManager
from search_service import SearchService, SearchResult
from url_handler import fetch_urls_content

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

async def handle_search_queries(
    queries: List[str],
    api_key_manager: APIKeyManager,
    httpx_client: httpx.AsyncClient,
    config: Optional[Dict[str, Any]] = None
) -> str:
    """
    Perform a search on multiple queries, gather all results,
    deduplicate them by URL, fetch the page content for each unique URL,
    and return a formatted plain text summary.

    Args:
        queries: List of search queries.
        api_key_manager: API key manager instance.
        httpx_client: HTTP client for web requests.
        config: Additional configuration options.

    Returns:
        A plain text string containing aggregated search results.
    """
    config = config or {}
    max_urls: int = config.get("max_urls", 5)
    search_service: SearchService = SearchService(api_key_manager, httpx_client)
    aggregated_results: Dict[str, SearchResult] = {}
    errors: List[str] = []

    for query in queries:
        results: List[SearchResult]
        error: Optional[str]
        results, error = await search_service.search(query, max_urls)
        if error:
            errors.append(f"Query '{query}': {error}")
        for res in results:
            if res.url not in aggregated_results:
                aggregated_results[res.url] = res

    dedup_results: List[SearchResult] = list(aggregated_results.values())

    if not dedup_results:
        return "No search results found from any provider."

    url_list: List[str] = [res.url for res in dedup_results]
    contents: List[str] = await fetch_urls_content(url_list, api_key_manager, httpx_client, config=config)

    lines: List[str] = []
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