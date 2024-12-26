import asyncio
import re
import html2text
import httpx

def extract_urls_from_text(text):
    url_pattern = re.compile(r'(https?://\S+)')
    urls = re.findall(url_pattern, text)
    return urls

async def fetch_urls_content(urls, max_content_length=10000):
    async def fetch_and_convert(url):
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                if 'text/html' in response.headers.get('Content-Type', ''):
                    html_content = response.text
                    text_content = html2text.html2text(html_content)
                else:
                    text_content = response.text
                text_content = text_content[:max_content_length]
                return text_content.strip()
        except Exception as e:
            return f"Error fetching content from {url}: {e}"

    tasks = [fetch_and_convert(url) for url in urls]
    contents = await asyncio.gather(*tasks)
    return contents