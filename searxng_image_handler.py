"""
SearxNG Image Handler Module

This module implements image search using SearxNG with a fallback to Serper.
It defines helper functions to normalize, download and wrap image data as Discord Files.
"""

import logging
import asyncio
from typing import Tuple, List, Dict, Optional
import httpx
from io import BytesIO
from discord import File
from urllib.parse import urljoin, quote, urlparse

from searxng_config import get_searxng_config

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

def normalize_image_url(image_url: str, base_url: str = None) -> Optional[str]:
    """
    Normalize image URLs ensuring they are absolute and valid.

    Args:
        image_url (str): The raw image URL.
        base_url (str, optional): Base URL to resolve relative URLs.

    Returns:
        str or None: A normalized image URL or None if unable to resolve.
    """
    try:
        if image_url.startswith('data:'):
            return image_url
            
        image_url = image_url.strip()
        
        parsed = urlparse(image_url)
        
        if not parsed.scheme:
            if image_url.startswith('//'):
                return f'https:{image_url}'
                
            if image_url.startswith('/'):
                if base_url:
                    return urljoin(base_url, image_url)
                return None
                
            if base_url:
                return urljoin(base_url, image_url)
            return None
            
        if parsed.scheme not in ('http', 'https'):
            return None
            
        return image_url
        
    except Exception as e:
        logger.error(f"Error normalizing URL {image_url}: {e}")
        return None

async def download_image(image_url: str, httpx_client: httpx.AsyncClient, base_url: str = None) -> Optional[bytes]:
    """
    Download an image given its URL, handling data URLs and HTTP requests.

    Args:
        image_url (str): The URL to download.
        httpx_client (httpx.AsyncClient): HTTP client to make requests.
        base_url (str, optional): Base URL for resolving relative image URLs.
    
    Returns:
        bytes or None: Downloaded image data, or None if download fails.
    """
    try:
        normalized_url = normalize_image_url(image_url, base_url)
        if not normalized_url:
            raise ValueError(f"Invalid image URL: {image_url}")
            
        if normalized_url.startswith('data:'):
            import base64
            header, data = normalized_url.split(',', 1)
            if ';base64' in header:
                return base64.b64decode(data)
            return data.encode('utf-8')
            
        response = await httpx_client.get(normalized_url, timeout=10.0)
        response.raise_for_status()
        
        content_type = response.headers.get('content-type', '').lower()
        if not any(img_type in content_type for img_type in ['image/', 'application/octet-stream']):
            raise ValueError(f"Invalid content type: {content_type}")
            
        return response.content
        
    except httpx.HTTPError as http_err:
        logger.error(f"HTTP error downloading image from {image_url}: {http_err}")
        return None
    except Exception as e:
        logger.error(f"Error downloading image from {image_url}: {e}")
        return None

async def fetch_images_from_searxng(query: str, num_images: int, api_key_manager, httpx_client: httpx.AsyncClient) -> Tuple[List[File], List[str]]:
    """
    Search for images using SearxNG under the 'images' category.
    
    Args:
        query (str): Search query.
        num_images (int): Number of desired images.
        api_key_manager: API key manager instance.
        httpx_client (httpx.AsyncClient): HTTP client.
    
    Returns:
        Tuple:
          - Dictionary of Discord File objects (for successfully downloaded images).
          - List of URLs for images that failed to download.
    """
    image_files = []
    image_urls = []
    
    try:
        searxng_config = get_searxng_config()
        
        language = searxng_config['language'].split('#')[0].strip()
        
        params = {
            'q': query,
            'format': 'json',
            'language': language,
            'safesearch': searxng_config['safe_search'],
            'categories': 'images'
        }
        
        base_url = urljoin(searxng_config['base_url'], 'search')
        param_strings = []
        for key, value in params.items():
            encoded_key = quote(str(key))
            encoded_value = quote(str(value))
            param_strings.append(f"{encoded_key}={encoded_value}")
        url = f"{base_url}?{'&'.join(param_strings)}"
        
        logger.info(f"Making SearxNG images request to: {url}")
        
        response = await httpx_client.get(
            url,
            timeout=searxng_config['timeout']
        )
        response.raise_for_status()
        
        data = response.json()
        if not data.get('results'):
            logger.warning("No image results found from SearxNG")
            return [], []
        
        image_tasks = []
        urls_to_try = []
        
        # Optionally map source URLs (if needed later)
        source_urls = {result.get('source_url'): result.get('img_src') for result in data['results']}
        
        for result in data['results'][:num_images * 2]: 
            if 'img_src' in result:
                img_url = result['img_src']
                source_url = result.get('source_url')
                urls_to_try.append(img_url)
                image_tasks.append(download_image(img_url, httpx_client, source_url))
                
        if not image_tasks:
            logger.warning("No valid image URLs found in SearxNG results")
            return [], []
            
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
                
        return image_files, image_urls
        
    except Exception as e:
        logger.error(f"Error in SearxNG image search: {str(e)}")
        return [], []

async def fetch_images(queries: List[str], num_images: int, api_key_manager, httpx_client: httpx.AsyncClient) -> Tuple[Dict[str, List[File]], Dict[str, List[str]]]:
    """
    For a given list of queries, fetch images using SearxNG, and if necessary,
    fall back to fetching from Serper.
    
    Args:
        queries (List[str]): List of search queries.
        num_images (int): Desired number of images per query.
        api_key_manager: API key manager.
        httpx_client (httpx.AsyncClient): HTTP client.
    
    Returns:
        Tuple:
          - Dict mapping each query to a list of Discord File objects.
          - Dict mapping each query to a list of URLs for which images could not be downloaded.
    """
    image_files_dict = {}
    image_urls_dict = {}
    
    for query in queries:
        files, urls = await fetch_images_from_searxng(query, num_images, api_key_manager, httpx_client)
        
        if not files and not urls:
            from image_handler import fetch_images_from_serper
            files, urls = await fetch_images_from_serper([query], num_images, api_key_manager, httpx_client)
            if isinstance(files, list):
                files = files
            else:
                files = []
            if isinstance(urls, list):
                urls = urls 
            else:
                urls = []
        
        image_files_dict[query] = files
        image_urls_dict[query] = urls
        
    return image_files_dict, image_urls_dict