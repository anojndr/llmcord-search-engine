import logging
from typing import Optional
import httpx
from urllib.parse import urljoin, urlparse
import base64

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
        normalized_url: Optional[str] = normalize_image_url(image_url, base_url)
        if not normalized_url:
            raise ValueError(f"Invalid image URL: {image_url}")

        if normalized_url.startswith('data:'):
            header, data = normalized_url.split(',', 1)
            if ';base64' in header:
                return base64.b64decode(data)
            return data.encode('utf-8')

        response: httpx.Response = await httpx_client.get(normalized_url, timeout=10.0)
        response.raise_for_status()

        content_type: str = response.headers.get('content-type', '').lower()
        if not any(img_type in content_type for img_type in ['image/', 'application/octet-stream']):
            raise ValueError(f"Invalid content type: {content_type}")

        return response.content

    except httpx.HTTPError as http_err:
        logger.error(f"HTTP error downloading image from {image_url}: {http_err}")
        return None
    except Exception as e:
        logger.error(f"Error downloading image from {image_url}: {e}")
        return None