import asyncio
import re
import html2text
import httpx
from youtube_handler import fetch_youtube_content
from reddit_handler import fetch_reddit_content

def extract_urls_from_text(text):
    url_pattern = re.compile(r'(https?://\S+)')
    urls = re.findall(url_pattern, text)
    return urls

async def fetch_urls_content(urls, config=None):
    if config is None:
        config = {}

    async def fetch_and_convert(url):
        if 'youtube.com' in url or 'youtu.be' in url:
            api_key = config.get('youtube_api_key', '')
            if not api_key:
                return "YouTube API key not set in config."
            content = await fetch_youtube_content(url, api_key)
            return content
        elif 'reddit.com' in url or 'redd.it' in url:
            client_id = config.get('reddit_client_id', '')
            client_secret = config.get('reddit_client_secret', '')
            user_agent = config.get('reddit_user_agent', 'llmcord_bot')
            if not client_id or not client_secret:
                return "Reddit API credentials not set in config."
            content = await fetch_reddit_content(url, client_id, client_secret, user_agent)
            return content
        else:
            try:
                async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    if 'text/html' in response.headers.get('Content-Type', ''):
                        html_content = response.text
                        text_content = html2text.html2text(html_content)
                    else:
                        text_content = response.text
                    return text_content.strip()
            except Exception as e:
                return f"Error fetching content from {url}: {e}"

    tasks = [fetch_and_convert(url) for url in urls]
    contents = await asyncio.gather(*tasks)
    return contents