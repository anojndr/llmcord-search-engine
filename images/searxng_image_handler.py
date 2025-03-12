"""
SearxNG Image Handler Module

This module implements image search using SearxNG with a fallback to Serper.
It defines helper functions to normalize, download and wrap image data as Discord Files.
"""

import logging
import asyncio
from typing import Any, Tuple, List, Dict, Optional

import httpx
from io import BytesIO
from discord import File
from urllib.parse import urljoin, quote

from config.api_key_manager import APIKeyManager
from config.searxng_config import get_searxng_config
from images.image_handler import fetch_images_from_serper
from images.utils import download_image

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


async def fetch_images_from_searxng(
    query: str,
    num_images: int,
    api_key_manager: APIKeyManager,
    httpx_client: httpx.AsyncClient
) -> Tuple[List[File], List[str]]:
    """
    Search for images using SearxNG under the 'images' category.

    Args:
        query: Search query.
        num_images: Number of desired images.
        api_key_manager: API key manager instance.
        httpx_client: HTTP client.

    Returns:
        Tuple:
          - List of Discord File objects (for successfully downloaded images).
          - List of URLs for images that failed to download.
    """
    image_files: List[File] = []
    image_urls: List[str] = []

    try:
        # Get SearxNG configuration
        searxng_config: Dict[str, Any] = get_searxng_config()
        language: str = searxng_config['language'].split('#')[0].strip()

        # Prepare request parameters
        params: Dict[str, Any] = {
            'q': query,
            'format': 'json',
            'language': language,
            'safesearch': searxng_config['safe_search'],
            'categories': 'images'
        }

        # Build URL with properly encoded parameters
        base_url: str = urljoin(searxng_config['base_url'], 'search')
        param_strings: List[str] = []
        for key, value in params.items():
            encoded_key: str = quote(str(key))
            encoded_value: str = quote(str(value))
            param_strings.append(f"{encoded_key}={encoded_value}")
        url: str = f"{base_url}?{'&'.join(param_strings)}"

        logger.info(f"Making SearxNG images request to: {url}")

        # Send request to SearxNG
        response: httpx.Response = await httpx_client.get(
            url,
            timeout=searxng_config['timeout']
        )
        response.raise_for_status()

        # Process response
        data: Dict[str, Any] = response.json()
        if not data.get('results'):
            logger.warning(f"No image results found from SearxNG for query: {query}")
            return [], []

        # Queue image download tasks
        image_tasks: List[asyncio.Task] = []
        urls_to_try: List[str] = []

        # Create mapping of source URLs to image URLs
        source_urls: Dict[str, str] = {
            result.get('source_url'): result.get('img_src') 
            for result in data['results']
        }

        # Create download tasks for each image
        for result in data['results'][:num_images * 2]:
            if 'img_src' in result:
                img_url: str = result['img_src']
                source_url: str = result.get('source_url')
                urls_to_try.append(img_url)
                image_tasks.append(download_image(img_url, httpx_client, source_url))

        if not image_tasks:
            logger.warning(
                f"No valid image URLs found in SearxNG results for query: {query}"
            )
            return [], []

        # Execute all download tasks concurrently
        downloaded_images: List[Optional[bytes]] = await asyncio.gather(*image_tasks)

        # Process downloaded images
        successful_downloads: int = 0
        for idx, image_data in enumerate(downloaded_images):
            if image_data is None:
                logger.error(f"Failed to download image from URL: {urls_to_try[idx]}")
                if successful_downloads < num_images:
                    image_urls.append(urls_to_try[idx])
            else:
                if successful_downloads < num_images:
                    image_file: File = File(
                        BytesIO(image_data), 
                        filename=f"image_{len(image_files) + 1}.png"
                    )
                    image_files.append(image_file)
                    successful_downloads += 1

            if successful_downloads >= num_images:
                break

        logger.info(
            f"SearxNG returned {successful_downloads} images and "
            f"{len(image_urls)} failed URLs for query: {query}"
        )
        return image_files, image_urls

    except Exception as e:
        logger.error(
            f"Error in SearxNG image search for query '{query}': {str(e)}", 
            exc_info=True
        )
        return [], []


async def fetch_images(
    queries: List[str],
    num_images: int,
    api_key_manager: APIKeyManager,
    httpx_client: httpx.AsyncClient
) -> Tuple[Dict[str, List[File]], Dict[str, List[str]]]:
    """
    For a given list of queries, fetch images using SearxNG, and if necessary,
    fall back to fetching from Serper.

    Args:
        queries: List of search queries.
        num_images: Desired number of images per query.
        api_key_manager: API key manager.
        httpx_client: HTTP client.

    Returns:
        Tuple:
          - Dict mapping each query to a list of Discord File objects.
          - Dict mapping each query to a list of URLs for which images could not be downloaded.
    """
    image_files_dict: Dict[str, List[File]] = {}
    image_urls_dict: Dict[str, List[str]] = {}

    for query in queries:
        # Try SearxNG first
        files: List[File]
        urls: List[str]
        files, urls = await fetch_images_from_searxng(
            query, num_images, api_key_manager, httpx_client
        )

        # If SearxNG found no images, fall back to Serper
        if not files and not urls:
            logger.info(
                f"SearxNG found no images for query '{query}'. "
                f"Falling back to Serper."
            )
            fallback_files, fallback_urls = await fetch_images_from_serper(
                [query], num_images, api_key_manager, httpx_client
            )
            
            # Validate fallback results
            if isinstance(fallback_files, list):
                files = fallback_files
            else:
                logger.warning(
                    f"Serper returned invalid files type for query '{query}': "
                    f"{type(fallback_files)}"
                )
                files = []
                
            if isinstance(fallback_urls, list):
                urls = fallback_urls
            else:
                logger.warning(
                    f"Serper returned invalid URLs type for query '{query}': "
                    f"{type(fallback_urls)}"
                )
                urls = []

        # Store results for this query
        image_files_dict[query] = files
        image_urls_dict[query] = urls

    return image_files_dict, image_urls_dict