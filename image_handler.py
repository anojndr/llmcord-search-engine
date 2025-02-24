"""
Image Handler Module

Modified image handler that uses SearxNG with a fallback via Serper.
This module fetches images based on search queries, downloads them and
returns Discord File objects together with any URLs that failed to download.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple
import httpx
from discord import File
from io import BytesIO
from searxng_image_handler import download_image
from api_key_manager import APIKeyManager

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

async def fetch_images_from_serper(
    queries: List[str],
    num_images: int,
    api_key_manager: APIKeyManager,
    httpx_client: httpx.AsyncClient
) -> Tuple[List[File], List[str]]:
    """
    Fetches images using the Serper image search API. This is used as a fallback
    if the main image search via SearxNG fails.

    Args:
        queries: List of search queries.
        num_images: Number of images to attempt to fetch per query.
        api_key_manager: Instance managing API keys.
        httpx_client: HTTP client for making requests.

    Returns:
        - A list of Discord File objects for the successfully downloaded images.
        - A list of URLs for which image downloading failed.
    """
    image_files: List[File] = []
    image_urls: List[str] = []

    for query in queries:
        api_key: str = await api_key_manager.get_next_api_key('serper')
        if not api_key:
            logger.warning("No Serper API key available.")
            continue

        params: Dict[str, Any] = {
            'q': query,
            'num': num_images * 2,
            'type': 'images',
            'autocorrect': 'false',
            'apiKey': api_key
        }

        try:
            response: httpx.Response = await httpx_client.get(
                'https://google.serper.dev/images',
                params=params,
                timeout=30.0
            )
            response.raise_for_status()
            data: Dict[str, Any] = response.json()

            source_urls: Dict[str, str] = {}
            for image in data.get('images', []):
                source_urls[image.get('sourceUrl')] = image.get('imageUrl')

            image_tasks: List[asyncio.Task] = []
            urls_to_try: List[str] = []

            for image in data.get('images', [])[:num_images * 2]:
                image_url: str = image.get('imageUrl')
                source_url: str = image.get('sourceUrl')

                if image_url:
                    urls_to_try.append(image_url)
                    image_tasks.append(download_image(image_url, httpx_client, source_url))

            if not image_tasks:
                logger.warning(f"No valid image URLs found for query: {query}")
                continue

            downloaded_images: List[Optional[bytes]] = await asyncio.gather(*image_tasks)

            successful_downloads: int = 0
            for idx, image_data in enumerate(downloaded_images):
                if image_data is None:
                    logger.error(f"Failed to download image from URL: {urls_to_try[idx]}")
                    if successful_downloads < num_images:
                        image_urls.append(urls_to_try[idx])
                else:
                    if successful_downloads < num_images:
                        image_file: File = File(BytesIO(image_data), filename=f"image_{len(image_files) + 1}.png")
                        image_files.append(image_file)
                        successful_downloads += 1

                if successful_downloads >= num_images:
                    break

        except httpx.HTTPError as http_err:
            logger.error(f"HTTP error while fetching images for query {query}: {http_err}")
            continue
        except Exception as e:
            logger.error(f"Error fetching images for query {query}: {e}")
            continue

    return image_files, image_urls