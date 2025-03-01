"""
SauceNAO Handler Module

Provides functionality to perform a SauceNAO image source lookup using its API.
It downloads the given image, sends it to the SauceNAO API, and formats the results in plain text.
"""

import logging
from typing import Dict, Any, List, Optional

import httpx

from config.api_key_manager import APIKeyManager

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

SAUCENAO_API_URL: str = "https://saucenao.com/search.php"


async def handle_saucenao_query(
    image_url: str,
    api_key_manager: APIKeyManager,
    httpx_client: httpx.AsyncClient,
    min_similarity: float = 50.0
) -> str:
    """
    Look up an image source using the SauceNAO API.

    Args:
        image_url: URL of the image to search.
        api_key_manager: Instance managing API keys.
        httpx_client: HTTP client for requests.
        min_similarity: Minimum similarity threshold to consider (default: 50.0).

    Returns:
        Plain text–formatted results from SauceNAO.

    Raises:
        Exception: If no SauceNAO API key is available.
    """
    logger.info(f"Starting SauceNAO image source lookup for image: {image_url}")
    
    # Get API key
    api_key = await api_key_manager.get_next_api_key('saucenao')
    if not api_key:
        error_msg = "No SauceNAO API key available"
        logger.error(error_msg)
        raise Exception(error_msg)

    try:
        # Download the image
        logger.debug(f"Downloading image from URL: {image_url}")
        image_response = await httpx_client.get(image_url)
        image_response.raise_for_status()
        image_data = image_response.content
        logger.debug(f"Successfully downloaded image ({len(image_data)} bytes)")

        # Prepare multipart form data
        files: Dict[str, tuple] = {
            'file': ('image.png', image_data, 'image/png')
        }

        # Set SauceNAO API parameters
        params: Dict[str, Any] = {
            'output_type': 2,  # JSON output
            'api_key': api_key,
            'numres': 16,      # Number of results
            'db': 999,         # All databases
            'dedupe': 2        # High deduplication
        }

        # Send request to SauceNAO API
        logger.info("Sending request to SauceNAO API")
        response = await httpx_client.post(
            SAUCENAO_API_URL,
            params=params,
            files=files,
            timeout=30.0
        )
        response.raise_for_status()
        data: Dict[str, Any] = response.json()

        # Format response as plain text
        return _format_saucenao_response(data, min_similarity)

    except httpx.HTTPError as http_err:
        logger.error(
            f"HTTP error during SauceNAO request: {http_err}", 
            exc_info=True
        )
        return f"HTTP error during SauceNAO request: {str(http_err)}"
    except Exception as e:
        logger.error(
            f"Error processing SauceNAO request: {e}", 
            exc_info=True
        )
        return f"Error processing SauceNAO request: {str(e)}"


def _format_saucenao_response(
    data: Dict[str, Any], 
    min_similarity: float
) -> str:
    """
    Format the SauceNAO API response as plain text.
    
    Args:
        data: SauceNAO API response data
        min_similarity: Minimum similarity threshold
    
    Returns:
        Formatted plain text response
    """
    lines: List[str] = []
    header: Dict[str, Any] = data.get('header', {})
    
    # Add header information
    lines.append("SauceNAO Results:")
    lines.append("Header:")
    lines.append(f"  User ID: {header.get('user_id', '')}")
    lines.append(f"  Account Type: {header.get('account_type', '')}")
    lines.append(f"  Short Limit: {header.get('short_limit', '')}")
    lines.append(f"  Long Limit: {header.get('long_limit', '')}")
    lines.append(f"  Long Remaining: {header.get('long_remaining', '')}")
    lines.append(f"  Short Remaining: {header.get('short_remaining', '')}")
    lines.append(f"  Minimum Similarity: {header.get('minimum_similarity', '')}")
    lines.append(f"  Query Image: {header.get('query_image', '')}")
    lines.append(f"  Results Returned: {header.get('results_returned', '')}")
    lines.append("")

    # Log quota information
    logger.info(
        f"SauceNAO API quota - Short remaining: "
        f"{header.get('short_remaining', 'N/A')}, "
        f"Long remaining: {header.get('long_remaining', 'N/A')}"
    )

    # Process and filter results
    results: List[Dict[str, Any]] = data.get('results', [])
    filtered_results = []
    for result in results:
        similarity: float = float(
            result.get('header', {}).get('similarity', 0)
        )
        if similarity < min_similarity:
            continue
        filtered_results.append(result)
    
    logger.info(
        f"SauceNAO found {len(filtered_results)} results with similarity >= "
        f"{min_similarity}%"
    )

    # Add results to output
    for result in filtered_results:
        rheader: Dict[str, str] = result.get('header', {})
        rdata: Dict[str, Any] = result.get('data', {})
        
        lines.append("Result:")
        lines.append(f"  Similarity: {rheader.get('similarity', '')}")
        lines.append(f"  Thumbnail: {rheader.get('thumbnail', '')}")
        lines.append(f"  Index ID: {rheader.get('index_id', '')}")
        lines.append(f"  Index Name: {rheader.get('index_name', '')}")
        
        for key, value in rdata.items():
            if isinstance(value, list):
                lines.append(f"  {key.capitalize()}:")
                for item in value:
                    lines.append(f"    - {item}")
            else:
                lines.append(f"  {key.capitalize()}: {value}")
        
        lines.append("")

    return "\n".join(lines)