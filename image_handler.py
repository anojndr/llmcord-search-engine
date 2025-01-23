import asyncio
import logging
import httpx
from api_key_manager import APIKeyManager
from discord import File
from io import BytesIO

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

async def fetch_images_from_serper(queries, num_images, api_key_manager, httpx_client):
    """
    Fetches images from Serper API using GET requests with query parameters
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
            response = await httpx_client.get('https://google.serper.dev/images', params=params)
            response.raise_for_status()
            data = response.json()

            image_tasks = []
            for image in data.get('images', [])[:num_images * 2]:
                image_url = image['imageUrl']
                image_tasks.append(download_image(image_url, httpx_client))

            downloaded_images = await asyncio.gather(*image_tasks, return_exceptions=True)

            successful_downloads = 0
            for idx, image_data in enumerate(downloaded_images):
                if isinstance(image_data, Exception):
                    logger.error(f"Error downloading image: {image_data}")
                    if successful_downloads < num_images:
                        image_urls.append(data['images'][idx]['imageUrl'])
                elif image_data:
                    if successful_downloads < num_images:
                        image_file = File(BytesIO(image_data), filename=f"image_{len(image_files) + 1}.png")
                        image_files.append(image_file)
                        successful_downloads += 1
                
                if successful_downloads >= num_images:
                    break

        except Exception as e:
            logger.error(f"Error fetching images for query {query}: {e}")

    return image_files, image_urls

async def download_image(image_url, httpx_client):
    """
    Downloads an image from the given URL and returns its binary data.

    Args:
        image_url (str): URL of the image to download.
        httpx_client: Async HTTP client for making requests.

    Returns:
        bytes: Binary data of the downloaded image, or None if the download fails.
    """
    try:
        response = await httpx_client.get(image_url)
        response.raise_for_status()
        return response.content
    except Exception as e:
        logger.error(f"Error downloading image from {image_url}: {e}")
        raise e