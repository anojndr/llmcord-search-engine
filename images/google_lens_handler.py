"""
Google Lens Handler Module

This module provides functionalities to search for visual matches in images via
the Google Lens API (using SerpApi) and to process the results.

It uses url_handler.py to fetch content from URLs.
"""

import asyncio
import logging
from typing import Dict, Any, List
import httpx

from config.api_key_manager import APIKeyManager
from search.url_handler import fetch_urls_content

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


async def get_google_lens_results(
    image_url: str,
    api_key_manager: APIKeyManager,
    httpx_client: httpx.AsyncClient,
    hl: str = 'en',
    country: str = 'us'
) -> Dict[str, Any]:
    """
    Call the SerpApi Google Lens API with the provided image URL.

    Args:
        image_url: The URL of the image to analyze.
        api_key_manager: API key manager instance.
        httpx_client: HTTP client for API calls.
        hl: The language code (default 'en').
        country: Country code for the query (default 'us').

    Returns:
        JSON response from the API containing the results.

    Raises:
        Exception: If an API key is not available or the HTTP request fails.
    """
    logger.info(f"Starting Google Lens search with image URL: {image_url}")

    # Get API key
    api_key: str = await api_key_manager.get_next_api_key('serpapi')
    if not api_key:
        error_msg: str = "No SerpApi API key available for Google Lens search"
        logger.error(error_msg)
        raise Exception(error_msg)

    # Prepare request parameters
    params: Dict[str, str] = {
        'engine': 'google_lens',
        'url': image_url,
        'hl': hl,
        'country': country,
        'api_key': api_key
    }
    
    # Log request (hiding API key)
    logger_params = params.copy()
    logger_params['api_key'] = '***REDACTED***'
    logger.debug(f"Google Lens API parameters: {logger_params}")

    try:
        logger.info("Sending request to SerpApi Google Lens endpoint")
        response: httpx.Response = await httpx_client.get(
            'https://serpapi.com/search',
            params=params,
            timeout=300
        )
        response.raise_for_status()
        data: Dict[str, Any] = response.json()
        
        # Log basic stats about the response
        visual_matches = data.get('visual_matches', [])
        logger.info(
            f"Google Lens search successful. Found {len(visual_matches)} "
            f"visual matches."
        )
        return data
    except httpx.HTTPError as http_err:
        logger.error(
            f"HTTP error during Google Lens request: {http_err}", 
            exc_info=True
        )
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error while calling Google Lens API: {e}", 
            exc_info=True
        )
        raise


async def process_google_lens_results(
    results: Dict[str, Any],
    config: Dict[str, Any],
    api_key_manager: APIKeyManager,
    httpx_client: httpx.AsyncClient
) -> str:
    """
    Process the visual matches from the Google Lens API response.

    This function extracts up to 10 visual matches, queues up fetch tasks,
    and formats the returned content with additional metadata.

    Args:
        results: JSON result from the Google Lens API.
        config: Configuration options.
        api_key_manager: API key manager.
        httpx_client: HTTP client.

    Returns:
        A formatted string containing processed results.
    """
    visual_matches: List[Dict[str, Any]] = results.get('visual_matches', [])
    logger.info(
        f"Processing {len(visual_matches)} visual matches from Google Lens "
        f"results"
    )

    formatted_results: str = ''
    
    # Limit to first 10 matches
    matches_to_process = visual_matches[:10]
    
    # Queue up all fetch tasks
    tasks: List[asyncio.Task] = []
    for idx, match in enumerate(matches_to_process, start=1):
        url: str = match.get('link', '')
        title: str = match.get('title', '')
        logger.debug(f"Queueing visual match #{idx}: url={url}, title={title}")
        tasks.append(
            process_visual_match(
                idx, url, title, config, api_key_manager, httpx_client
            )
        )

    try:
        logger.info(
            f"Processing {len(tasks)} visual match tasks concurrently"
        )
        processed_matches: List[str] = await asyncio.gather(*tasks)
        
        for match_result in processed_matches:
            formatted_results += match_result

        logger.info("All visual matches processed successfully")
        return formatted_results
    except Exception as e:
        logger.error(
            f"Error while processing visual matches: {e}", 
            exc_info=True
        )
        raise


async def process_visual_match(
    idx: int,
    url: str,
    title: str,
    config: Dict[str, Any],
    api_key_manager: APIKeyManager,
    httpx_client: httpx.AsyncClient
) -> str:
    """
    Process a single visual match URL by fetching its content.

    Args:
        idx: The visual match number.
        url: URL of the visual match.
        title: Title of the visual match (unused in output formatting).
        config: Configuration settings.
        api_key_manager: API key manager instance.
        httpx_client: HTTP client for content fetching.

    Returns:
        A string of formatted results for the visual match.
    """
    logger.debug(f"Processing visual match #{idx}: {url}")
    
    try:
        contents: List[str] = await fetch_urls_content(
            [url], api_key_manager, httpx_client, config=config
        )
        content = contents[0] if contents else f"Error fetching content from {url}"
        
        formatted_result: str = (
            f"Visual match {idx}:\n"
            f"Url of visual match {idx}: {url}\n"
            f"Url of visual match {idx} content:\n{content}\n\n"
        )

        logger.debug(f"Finished processing visual match #{idx}")
        return formatted_result
    except Exception as e:
        logger.error(
            f"Error processing visual match #{idx} ({url}): {e}", 
            exc_info=True
        )
        return (
            f"Visual match {idx}:\nUrl of visual match {idx}: {url}\n"
            f"Error: {str(e)}\n\n"
        )