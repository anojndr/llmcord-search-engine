"""
Google Lens Handler Module

This module provides functionalities to search for visual matches in images via
the Google Lens API (using SerpApi) and to process the results.

It uses url_handler.py to fetch content from URLs.
"""

import asyncio
import logging
import httpx
from url_handler import fetch_urls_content

# Set up logging for debugging purposes.
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

async def get_google_lens_results(image_url, api_key_manager, httpx_client, hl='en', country='us'):
    """
    Call the SerpApi Google Lens API with the provided image URL.

    Args:
        image_url (str): The URL of the image to analyze.
        api_key_manager (APIKeyManager): API key manager instance.
        httpx_client (httpx.AsyncClient): HTTP client for API calls.
        hl (str): The language code (default 'en').
        country (str): Country code for the query (default 'us').

    Returns:
        dict: JSON response from the API containing the results.

    Raises:
        Exception: If an API key is not available or the HTTP request fails.
    """
    logger.debug("Starting get_google_lens_results with image_url=%s", image_url)

    api_key = await api_key_manager.get_next_api_key('serpapi')
    if not api_key:
        error_msg = "No SerpApi API key available."
        logger.error(error_msg)
        raise Exception(error_msg)

    # Construct API request parameters
    params = {
        'engine': 'google_lens',
        'url': image_url,
        'hl': hl,
        'country': country,
        'api_key': api_key
    }
    logger.debug("get_google_lens_results params: %s", params)

    try:
        # Perform asynchronous HTTP GET request to SerpApi
        response = await httpx_client.get(
            'https://serpapi.com/search',
            params=params,
            timeout=300
        )
        response.raise_for_status()
        data = response.json()
        logger.debug("Google Lens response received successfully.")
        return data
    except httpx.HTTPError as http_err:
        logger.exception("HTTP error during Google Lens request: %s", http_err)
        raise
    except Exception as e:
        logger.exception("Unexpected error while calling Google Lens API: %s", e)
        raise

async def process_google_lens_results(results, config, api_key_manager, httpx_client):
    """
    Process the visual matches from the Google Lens API response.

    This function extracts up to 10 visual matches, queues up fetch tasks,
    and formats the returned content with additional metadata.

    Args:
        results (dict): JSON result from the Google Lens API.
        config (dict): Configuration options.
        api_key_manager (APIKeyManager): API key manager.
        httpx_client (httpx.AsyncClient): HTTP client.

    Returns:
        str: A formatted string containing processed results.
    """
    visual_matches = results.get('visual_matches', [])
    logger.debug("Processing %d visual matches.", len(visual_matches))

    formatted_results = ''
    tasks = []

    # Process up to 10 visual matches
    for idx, match in enumerate(visual_matches[:10], start=1):
        url = match.get('link', '')
        title = match.get('title', '')
        logger.debug("Queueing visual match #%d: url=%s, title=%s", idx, url, title)
        tasks.append(process_visual_match(idx, url, title, config, api_key_manager, httpx_client))

    try:
        processed_matches = await asyncio.gather(*tasks)
    except Exception:
        logger.exception("Error while processing one or more visual matches.")
        raise

    for match_result in processed_matches:
        formatted_results += match_result

    logger.debug("All visual matches processed.")
    return formatted_results

async def process_visual_match(idx, url, title, config, api_key_manager, httpx_client):
    """
    Process a single visual match URL by fetching its content using url_handler.

    Args:
        idx (int): The visual match number.
        url (str): URL of the visual match.
        title (str): Title of the visual match (unused in output formatting).
        config (dict): Configuration settings.
        api_key_manager (APIKeyManager): API key manager instance.
        httpx_client (httpx.AsyncClient): HTTP client for content fetching.

    Returns:
        str: A string of formatted results for the visual match.
    """
    logger.debug("Starting process_visual_match #%d: %s", idx, url)
    content = ''

    # Fetch content using fetch_urls_content from url_handler.py
    contents = await fetch_urls_content([url], api_key_manager, httpx_client, config=config)
    content = contents[0] if contents else f"Error fetching content from {url}"

    formatted_result = (
        f"Visual match {idx}:\n"
        f"Url of visual match {idx}: {url}\n"
        f"Url of visual match {idx} content:\n{content}\n\n"
    )

    logger.debug("Finished processing visual match #%d.", idx)
    return formatted_result