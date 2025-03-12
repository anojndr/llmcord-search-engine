"""
Image Utilities Module

Provides helper functions for image URL normalization and downloading.
"""

import logging
import base64
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from fake_useragent import UserAgent

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def normalize_image_url(image_url: str, base_url: Optional[str] = None) -> Optional[str]:
    """
    Normalize image URLs ensuring they are absolute and valid.

    Args:
        image_url: The raw image URL.
        base_url: Base URL to resolve relative URLs.

    Returns:
        A normalized image URL or None if unable to resolve.
    """
    try:
        if not image_url:
            logger.warning("Empty image URL provided")
            return None
            
        if image_url.startswith('data:'):
            logger.debug("Data URL detected, returning as-is")
            return image_url

        image_url = image_url.strip()
        logger.debug(f"Normalizing image URL: {image_url}")

        parsed = urlparse(image_url)

        # Handle protocol-relative URLs (starting with //)
        if not parsed.scheme:
            if image_url.startswith('//'):
                normalized_url = f'https:{image_url}'
                logger.debug(f"Protocol-relative URL normalized: {normalized_url}")
                return normalized_url

            # Handle absolute paths (starting with /)
            if image_url.startswith('/'):
                if base_url:
                    normalized_url = urljoin(base_url, image_url)
                    logger.debug(
                        f"Absolute path URL normalized with base {base_url}: "
                        f"{normalized_url}"
                    )
                    return normalized_url
                logger.warning(f"Absolute path URL without base URL: {image_url}")
                return None

            # Handle relative URLs
            if base_url:
                normalized_url = urljoin(base_url, image_url)
                logger.debug(
                    f"Relative URL normalized with base {base_url}: {normalized_url}"
                )
                return normalized_url
                
            logger.warning(f"Relative URL without base URL: {image_url}")
            return None

        # Check for supported schemes
        if parsed.scheme not in ('http', 'https'):
            logger.warning(f"Unsupported URL scheme: {parsed.scheme}")
            return None

        logger.debug(f"URL already normalized: {image_url}")
        return image_url

    except Exception as e:
        logger.error(f"Error normalizing URL {image_url}: {e}", exc_info=True)
        return None


async def download_image(
    image_url: str,
    httpx_client: httpx.AsyncClient,
    base_url: Optional[str] = None
) -> Optional[bytes]:
    """
    Download an image given its URL, handling data URLs and HTTP requests.

    Args:
        image_url: The URL to download.
        httpx_client: HTTP client to make requests.
        base_url: Base URL for resolving relative image URLs.

    Returns:
        Downloaded image data, or None if download fails.
    """
    try:
        # Check for empty URL
        if not image_url or image_url.strip() == "":
            logger.warning("Empty image URL provided")
            return None

        # Normalize the URL
        normalized_url: Optional[str] = normalize_image_url(image_url, base_url)
        if not normalized_url:
            logger.warning(f"Unable to normalize image URL: {image_url}")
            return None

        # Handle data URLs
        if normalized_url.startswith('data:'):
            logger.debug("Processing data URL")
            header, data = normalized_url.split(',', 1)
            if ';base64' in header:
                logger.debug("Decoding base64 data URL")
                return base64.b64decode(data)
            logger.debug("Processing non-base64 data URL")
            return data.encode('utf-8')

        # Use fake-useragent to generate a random user agent
        ua = UserAgent()
        random_user_agent = ua.random
        
        # Set common headers for image requests with random user agent
        headers = {
            'User-Agent': random_user_agent,
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
        }
        
        logger.debug(f"Using random user agent: {random_user_agent}")
        
        # Handle HTTP URLs with explicit redirect handling
        logger.debug(f"Downloading image from URL: {normalized_url}")
        response: httpx.Response = await httpx_client.get(
            normalized_url, 
            timeout=10.0,
            follow_redirects=True,  # Enable following redirects
            headers=headers
        )
        response.raise_for_status()

        # Get content type, defaulting to empty string if not present
        content_type: str = response.headers.get('content-type', '').lower()
        
        # List of acceptable image content types
        valid_image_types = [
            'image/', 
            'application/octet-stream',
            'binary/',
            'multipart/form-data'
        ]
        
        # Check if content type is valid for images
        is_valid_type = any(type_str in content_type for type_str in valid_image_types)
        
        # Special case handling for known problematic domains
        special_case_domains = ['facebook', 'fbcdn', 'fbsbx', 'pinterest', 'pinimg']
        is_special_domain = any(domain in normalized_url for domain in special_case_domains)
        
        # Process content if valid type or special case with reasonable size (> 1KB)
        if is_valid_type or (is_special_domain and len(response.content) > 1000):
            logger.debug(f"Successfully downloaded image ({len(response.content)} bytes)")
            return response.content
        
        # If we get here, content doesn't meet image criteria
        logger.warning(f"Invalid content type: {content_type} for URL: {normalized_url}")
        return None

    except httpx.HTTPError as http_err:
        # Handle redirect errors specifically
        if '301' in str(http_err) or '302' in str(http_err) or 'redirect' in str(http_err).lower():
            logger.warning(f"Redirect error for URL {image_url}")
            
            # Try to extract the redirect location
            redirect_location = None
            if hasattr(http_err, 'response') and 'location' in http_err.response.headers:
                redirect_location = http_err.response.headers['location']
                logger.info(f"Redirect location: {redirect_location}")
                
                # Try to follow the redirect manually as last resort
                try:
                    logger.debug(f"Attempting to follow redirect manually to: {redirect_location}")
                    return await download_image(redirect_location, httpx_client, base_url)
                except Exception as redirect_err:
                    logger.error(f"Error following redirect manually: {redirect_err}")
                    
        logger.error(f"HTTP error downloading image from {image_url}: {http_err}")
        return None
    except ValueError as ve:
        logger.warning(f"Value error downloading image: {ve}")
        return None
    except Exception as e:
        logger.error(f"Error downloading image from {image_url}: {e}", exc_info=True)
        return None