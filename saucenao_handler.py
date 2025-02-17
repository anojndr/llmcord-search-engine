"""
SauceNAO Handler Module

Provides functionality to perform a SauceNAO image source lookup using its API.
It downloads the given image, sends it to the SauceNAO API, and formats the results in plain text.
"""

import logging
import httpx
import html
from io import BytesIO
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

SAUCENAO_API_URL = "https://saucenao.com/search.php"


async def handle_saucenao_query(
    image_url: str,
    api_key: str,
    httpx_client: httpx.AsyncClient,
    min_similarity: float = 50.0
) -> str:
    """
    Look up an image source using the SauceNAO API.

    Args:
        image_url (str): URL of the image to search.
        api_key (str): SauceNAO API key.
        httpx_client (httpx.AsyncClient): HTTP client for requests.
        min_similarity (float): Minimum similarity threshold to consider (default: 50.0).

    Returns:
        str: Plain text–formatted results from SauceNAO.
    """
    try:
        # Download the image to send to SauceNAO.
        image_response = await httpx_client.get(image_url)
        image_response.raise_for_status()
        image_data = image_response.content
        
        # Prepare multipart upload.
        files = {
            'file': ('image.png', image_data, 'image/png')
        }
        
        params = {
            'output_type': 2,
            'api_key': api_key,
            'numres': 16,
            'db': 999,
            'dedupe': 2
        }
        
        response = await httpx_client.post(
            SAUCENAO_API_URL,
            params=params,
            files=files,
            timeout=30.0
        )
        response.raise_for_status()
        data = response.json()
        
        lines = []
        header = data.get('header', {})
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
        
        results = data.get('results', [])
        for result in results:
            similarity = float(result.get('header', {}).get('similarity', 0))
            if similarity < min_similarity:
                continue
            rheader = result.get('header', {})
            rdata = result.get('data', {})
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
        
    except httpx.HTTPError as http_err:
        logger.error(f"HTTP error during SauceNAO request: {http_err}")
        return f"HTTP error during SauceNAO request: {str(http_err)}"
    except Exception as e:
        logger.error(f"Error processing SauceNAO request: {e}")
        return f"Error processing SauceNAO request: {str(e)}"