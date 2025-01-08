import asyncio
import logging
import httpx
from bs4 import BeautifulSoup, Comment

from youtube_handler import fetch_youtube_content
from reddit_handler import fetch_reddit_content

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

def is_youtube_url(url):
    return 'youtube.com' in url or 'youtu.be' in url

def is_reddit_url(url):
    return 'reddit.com' in url or 'redd.it' in url

async def get_google_lens_results(image_url, api_key_manager, httpx_client, hl='en', country='us'):
    """
    Calls the SerpApi Google Lens API with the provided image URL.
    Uses logging statements to help with debugging any issues.
    """
    logger.debug("Starting get_google_lens_results with image_url=%s", image_url)

    api_key = await api_key_manager.get_next_api_key('serpapi')
    if not api_key:
        error_msg = "No SerpApi API key available."
        logger.error(error_msg)
        raise Exception(error_msg)

    params = {
        'engine': 'google_lens',
        'url': image_url,
        'hl': hl,
        'country': country,
        'api_key': api_key
    }
    logger.debug("get_google_lens_results params: %s", params)

    try:
        response = await httpx_client.get(
            'https://serpapi.com/search',
            params=params,
            timeout=300
        )
        response.raise_for_status()
        data = response.json()
        logger.debug("Google Lens response received successfully.")
        return data
    except httpx.HTTPError as http_err:
        logger.exception("HTTP error during Google Lens request: %s", http_err)
        raise
    except Exception as e:
        logger.exception("Unexpected error while calling Google Lens API: %s", e)
        raise

async def process_google_lens_results(results, config, api_key_manager, httpx_client):
    """
    Processes the visual matches from the Google Lens API response.
    Fetches content for each URL and formats the results with detailed logging.
    """
    visual_matches = results.get('visual_matches', [])
    logger.debug("Processing %d visual matches.", len(visual_matches))

    formatted_results = ''
    tasks = []

    for idx, match in enumerate(visual_matches[:10], start=1):
        url = match.get('link', '')
        title = match.get('title', '')
        logger.debug("Queueing visual match #%d: url=%s, title=%s", idx, url, title)
        tasks.append(process_visual_match(idx, url, title, config, api_key_manager, httpx_client))

    try:
        processed_matches = await asyncio.gather(*tasks)
    except Exception:
        logger.exception("Error while processing one or more visual matches.")
        raise

    for match_result in processed_matches:
        formatted_results += match_result

    logger.debug("All visual matches processed.")
    return formatted_results

async def process_visual_match(idx, url, title, config, api_key_manager, httpx_client):
    """
    Processes a single visual match by fetching its content and formatting the result.
    Adds logging to help debug errors or unexpected behavior.
    """
    logger.debug("Starting process_visual_match #%d: %s", idx, url)
    content = ''

    if is_youtube_url(url):
        logger.debug("Detected YouTube URL for match #%d: %s", idx, url)
        content = await fetch_youtube_content(url, api_key_manager, httpx_client)
    elif is_reddit_url(url):
        logger.debug("Detected Reddit URL for match #%d: %s", idx, url)
        content = await fetch_reddit_content(url, api_key_manager, httpx_client)
    else:
        try:
            response = await httpx_client.get(url, timeout=10.0, follow_redirects=True)
            response.raise_for_status()
            content_type = response.headers.get('Content-Type', '')

            if 'text/html' in content_type:
                html_content = response.text
                soup = BeautifulSoup(html_content, 'lxml')
                for tag in soup(['script', 'style', 'header', 'footer', 'nav', 'aside', 'form', 'svg', 'canvas']):
                    tag.decompose()
                for c in soup.find_all(text=lambda text: isinstance(text, Comment)):
                    c.extract()
                text_content = soup.get_text(separator=' ', strip=True)
            else:
                text_content = response.text

            content = text_content.strip()
            logger.debug("Successfully fetched content for URL: %s", url)

        except httpx.HTTPError as http_err:
            error_msg = f"Error fetching content from {url}: {http_err}"
            logger.exception(error_msg)
            content = error_msg
        except Exception as e:
            error_msg = f"Error fetching content from {url}: {e}"
            logger.exception(error_msg)
            content = error_msg

    formatted_result = (
        f"Visual match {idx}:\n"
        f"Url of visual match {idx}: {url}\n"
        f"Url of visual match {idx} content:\n{content}\n\n"
    )

    logger.debug("Finished processing visual match #%d.", idx)
    return formatted_result