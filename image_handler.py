"""
Modified image handler that uses SearxNG with Serper fallback.
"""

import asyncio
import logging
from typing import Tuple, List
import httpx
from discord import File
from io import BytesIO

from searxng_image_handler import download_image

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

async def fetch_images_from_serper(
    queries: List[str], 
    num_images: int, 
    api_key_manager, 
    httpx_client: httpx.AsyncClient
) -> Tuple[List[File], List[str]]:
    """
    Fetches images from Serper API using GET requests with query parameters.
    Used as fallback when SearxNG fails.
    
    Args:
        queries (List[str]): List of search queries
        num_images (int): Number of images to fetch per query
        api_key_manager: API key manager instance
        httpx_client (httpx.AsyncClient): HTTP client
        
    Returns:
        Tuple[List[File], List[str]]: List of image files and list of failed image URLs
    """
    image_files = []
    image_urls = []
    
    for query in queries:
        api_key = await api_key_manager.get_next_api_key('serper')
        if not api_key:
            logger.warning("No Serper API key available.")
            continue

        params = {
            'q': query,
            'num': num_images * 2,
            'type': 'images',
            'autocorrect': 'false',
            'apiKey': api_key
        }

        try:
            response = await httpx_client.get(
                'https://google.serper.dev/images', 
                params=params,
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()

            source_urls = {}
            for image in data.get('images', []):
                source_urls[image.get('sourceUrl')] = image.get('imageUrl')

            image_tasks = []
            urls_to_try = []

            for image in data.get('images', [])[:num_images * 2]:
                image_url = image.get('imageUrl')
                source_url = image.get('sourceUrl')
                
                if image_url:
                    urls_to_try.append(image_url)
                    image_tasks.append(download_image(image_url, httpx_client, source_url))

            if not image_tasks:
                logger.warning(f"No valid image URLs found for query: {query}")
                continue

            downloaded_images = await asyncio.gather(*image_tasks)

            successful_downloads = 0
            for idx, image_data in enumerate(downloaded_images):
                if image_data is None:
                    logger.error(f"Failed to download image from URL: {urls_to_try[idx]}")
                    if successful_downloads < num_images:
                        image_urls.append(urls_to_try[idx])
                else:
                    if successful_downloads < num_images:
                        image_file = File(BytesIO(image_data), filename=f"image_{len(image_files) + 1}.png")
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