"""
Search Handler Module

Delegates search queries to the SearchService and then wraps the results
(and any errors) in a structured plain text format.
"""

import logging
from typing import Dict, Any, List, Optional

import httpx

from config.api_key_manager import APIKeyManager
from search.search_service import SearchService, SearchResult
from search.url_handler import fetch_urls_content

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
    max_urls = config.get("max_urls", 5)
    
    logger.info(f"Handling search for {len(queries)} queries with max_urls={max_urls}")
    
    # Initialize search service
    search_service = SearchService(api_key_manager, httpx_client)
    aggregated_results: Dict[str, SearchResult] = {}
    errors: List[str] = []

    # Perform search for each query
    for i, query in enumerate(queries, 1):
        logger.info(f"Searching for query {i}/{len(queries)}: '{query}'")
        
        # Get search results
        results, error = await search_service.search(query, max_urls)
        
        if error:
            logger.warning(f"Error during search for query '{query}': {error}")
            errors.append(f"Query '{query}': {error}")
        
        # Log results
        if results:
            logger.info(f"Search returned {len(results)} results for query: '{query}'")
            for j, res in enumerate(results, 1):
                logger.debug(
                    f"  Result {j}: URL={res.url}, "
                    f"Title={res.title[:50]}..."
                )
        else:
            logger.warning(f"No results found for query: '{query}'")
        
        # Deduplicate by URL
        for res in results:
            if res.url not in aggregated_results:
                aggregated_results[res.url] = res

    # Process results
    dedup_results = list(aggregated_results.values())
    
    if not dedup_results:
        logger.warning("No search results found from any provider for any query")
        return "No search results found from any provider."

    # Fetch content for each URL
    logger.info(f"Fetching content for {len(dedup_results)} unique URLs")
    url_list = [res.url for res in dedup_results]
    contents = await fetch_urls_content(
        url_list, api_key_manager, httpx_client, config=config
    )

    # Format results as plain text
    formatted_results = _format_search_results(
        dedup_results, contents, errors
    )
    
    logger.info(f"Successfully formatted {len(dedup_results)} search results")
    return formatted_results


def _format_search_results(
    results: List[SearchResult],
    contents: List[str],
    errors: List[str]
) -> str:
    """
    Format search results as plain text.
    
    Args:
        results: List of search results
        contents: List of URL contents
        errors: List of error messages
        
    Returns:
        Formatted text content
    """
    lines = []
    
    # Add error messages if any
    if errors:
        logger.warning(f"Found {len(errors)} errors during search")
        lines.append("Error Messages:")
        for err in errors:
            lines.append(f" - {err}")
        lines.append("")
        
    lines.append("Aggregated Search Results:")

    # Add each result with its content
    for idx, (res, content) in enumerate(zip(results, contents), start=1):
        logger.debug(f"Formatting result {idx}/{len(results)}: {res.url}")
        lines.append(f"Result {idx}:")
        
        # Check if Jina was used successfully
        if content.startswith("__JINA_SUCCESS__"):
            # Only show snippet for Jina results
            lines.append(f"Snippet: {res.snippet}\n")
            # Remove the Jina marker before adding content
            content = content.replace("__JINA_SUCCESS__\n", "", 1)
        else:
            # Show URL, Title, and Snippet for non-Jina results
            lines.append(f"URL: {res.url}\n")
            lines.append(f"Title: {res.title}\n")
            lines.append(f"Snippet: {res.snippet}\n")
            lines.append("Fetched Content:\n")
        
        lines.append(content)
        lines.append("")
        
    return "\n".join(lines)