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

from config.api_key_manager import APIKeyManager
from images.utils import download_image

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
        logger.info(f"Fetching images from Serper for query: '{query}'")
        
        # Get API key
        api_key: Optional[str] = await api_key_manager.get_next_api_key('serper')
        if not api_key:
            logger.warning(
                f"No Serper API key available for image query: '{query}'"
            )
            continue

        # Prepare request
        params: Dict[str, Any] = {
            'q': query,
            'num': num_images * 2,  # Request more to account for failures
            'type': 'images',
            'autocorrect': 'false',
            'apiKey': api_key
        }

        try:
            # Make API request
            logger.debug(f"Making Serper images API request for query: '{query}'")
            response: httpx.Response = await httpx_client.get(
                'https://google.serper.dev/images',
                params=params,
                timeout=30.0
            )
            response.raise_for_status()
            data: Dict[str, Any] = response.json()

            # Create a lookup dictionary of source URLs to image URLs
            source_urls: Dict[str, str] = {}
            for image in data.get('images', []):
                source_urls[image.get('sourceUrl')] = image.get('imageUrl')

            # Queue image download tasks
            image_tasks: List[asyncio.Task] = []
            urls_to_try: List[str] = []

            for image in data.get('images', [])[:num_images * 2]:
                image_url: Optional[str] = image.get('imageUrl')
                source_url: Optional[str] = image.get('sourceUrl')

                if image_url:
                    urls_to_try.append(image_url)
                    image_tasks.append(
                        download_image(image_url, httpx_client, source_url)
                    )

            if not image_tasks:
                logger.warning(
                    f"No valid image URLs found in Serper results for query: "
                    f"'{query}'"
                )
                continue

            # Download images
            logger.info(f"Downloading {len(image_tasks)} images for query: '{query}'")
            downloaded_images: List[Optional[bytes]] = await asyncio.gather(*image_tasks)

            # Process downloaded images
            successful_downloads: int = 0
            for idx, image_data in enumerate(downloaded_images):
                if image_data is None:
                    logger.error(
                        f"Failed to download image from URL: {urls_to_try[idx]}"
                    )
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
                f"Successfully downloaded {successful_downloads} images for "
                f"query: '{query}'"
            )

        except httpx.HTTPError as http_err:
            logger.error(
                f"HTTP error while fetching images for query '{query}': "
                f"{http_err}", 
                exc_info=True
            )
            continue
        except Exception as e:
            logger.error(
                f"Error fetching images for query '{query}': {e}", 
                exc_info=True
            )
            continue

    logger.info(
        f"Completed Serper image fetching: {len(image_files)} files, "
        f"{len(image_urls)} failed URLs"
    )
    return image_files, image_urls