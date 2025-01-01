import asyncio
import httpx
from bs4 import BeautifulSoup

from youtube_handler import fetch_youtube_content
from reddit_handler import fetch_reddit_content

def is_youtube_url(url):
    return 'youtube.com' in url or 'youtu.be' in url

def is_reddit_url(url):
    return 'reddit.com' in url or 'redd.it' in url

async def get_google_lens_results(image_url, api_key_manager, hl='en', country='us'):
    """
    Calls the SerpApi Google Lens API with the provided image URL.
    """
    api_key = await api_key_manager.get_next_api_key('serpapi')
    if not api_key:
        raise Exception("No SerpApi API key available.")

    params = {
        'engine': 'google_lens',
        'url': image_url,
        'hl': hl,
        'country': country,
        'api_key': api_key
    }

    async with httpx.AsyncClient() as client:
        response = await client.get('https://serpapi.com/search', params=params)
        response.raise_for_status()
        data = response.json()
        return data

async def process_google_lens_results(results, config, api_key_manager):
    """
    Processes the visual matches from the Google Lens API response.
    Fetches content for each URL and formats the results.
    """
    visual_matches = results.get('visual_matches', [])
    formatted_results = ''

    tasks = []
    for idx, match in enumerate(visual_matches[:10], start=1):
        url = match.get('link', '')
        title = match.get('title', '')
        tasks.append(process_visual_match(idx, url, title, config, api_key_manager))

    processed_matches = await asyncio.gather(*tasks)

    for match_result in processed_matches:
        formatted_results += match_result

    return formatted_results

async def process_visual_match(idx, url, title, config, api_key_manager):
    """
    Processes a single visual match by fetching its content and formatting the result.
    """
    content = ''

    if is_youtube_url(url):
        content = await fetch_youtube_content(url, api_key_manager)
    elif is_reddit_url(url):
        content = await fetch_reddit_content(url, api_key_manager)
    else:
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                if 'text/html' in response.headers.get('Content-Type', ''):
                    html_content = response.text
                    soup = BeautifulSoup(html_content, 'lxml')
                    # Remove script and style elements
                    for script_or_style in soup(['script', 'style']):
                        script_or_style.decompose()
                    # Get text
                    text_content = soup.get_text(separator=' ', strip=True)
                else:
                    text_content = response.text
                content = text_content.strip()
        except Exception as e:
            content = f"Error fetching content from {url}: {e}"

    formatted_result = f"Visual match {idx}:\n"
    formatted_result += f"Url of visual match {idx}: {url}\n"
    formatted_result += f"Url of visual match {idx} content:\n{content}\n\n"

    return formatted_result