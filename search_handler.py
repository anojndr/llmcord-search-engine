"""
Search Handler Module

Delegates search queries to the SearchService and then wraps the results (and any errors)
in a structured XML format. Also supports fetching URL content from the search results.
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
    Perform a search using multiple providers with fallback logic, and combine the results into XML.

    Args:
        query (str): The search query.
        api_key_manager: API key manager instance.
        httpx_client (httpx.AsyncClient): HTTP client for web requests.
        config (dict, optional): Additional configuration options.

    Returns:
        str: An XML string containing search results.
    """
    if config is None:
        config = {}

    max_urls = config.get('max_urls', 5)
    search_service = SearchService(api_key_manager, httpx_client)
    
    results, errors = await search_service.search(query, max_urls)
    
    xml_parts = ['<search_results>']
    
    if errors:
        xml_parts.append('<error_messages>')
        for error in errors:
            xml_parts.append(f'<search_error>{error}</search_error>')
        xml_parts.append('</error_messages>')
    
    if not results:
        xml_parts.append('<search_error>No results found from any provider</search_error>')
        xml_parts.append('</search_results>')
        return '\n'.join(xml_parts)
    
    # Extract the URLs from the search results and fetch their page content.
    url_list = [result.url for result in results]
    contents = await fetch_urls_content(url_list, api_key_manager, httpx_client, config=config)
    
    for idx, (result, content) in enumerate(zip(results, contents), start=1):
        xml_parts.extend([
            f'<search_result id="{idx}">',
            '<metadata>',
            f'<url>{result.url}</url>',
            f'<title>{result.title}</title>',
            f'<snippet>{result.snippet}</snippet>',
            '</metadata>',
            f'<content>{content}</content>',
            '</search_result>'
        ])
    
    xml_parts.append('</search_results>')
    return '\n'.join(xml_parts)