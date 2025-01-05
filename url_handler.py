import asyncio
import re
from bs4 import BeautifulSoup, Comment
import httpx
from youtube_handler import fetch_youtube_content
from reddit_handler import fetch_reddit_content
from PyPDF2 import PdfReader
from io import BytesIO

def extract_urls_from_text(text):
    url_pattern = re.compile(r'(https?://\S+)')
    urls = re.findall(url_pattern, text)
    return urls

async def fetch_urls_content(urls, api_key_manager, httpx_client, config=None):
    if config is None:
        config = {}

    async def fetch_and_convert(url):
        if 'youtube.com' in url or 'youtu.be' in url:
            content = await fetch_youtube_content(url, api_key_manager, httpx_client)
            return content
        elif 'reddit.com' in url or 'redd.it' in url:
            content = await fetch_reddit_content(url, api_key_manager, httpx_client)
            return content
        else:
            try:
                response = await httpx_client.get(url, timeout=10.0, follow_redirects=True)
                response.raise_for_status()
                content_type = response.headers.get('Content-Type', '')

                if 'application/pdf' in content_type:
                    pdf_bytes = response.content
                    try:
                        reader = PdfReader(BytesIO(pdf_bytes))
                        text_content = ''
                        for page in reader.pages:
                            text = page.extract_text()
                            if text:
                                text_content += text + '\n'
                        if not text_content:
                            text_content = f"No extractable text found in PDF at {url}."
                    except Exception as e:
                        text_content = f"Error extracting text from PDF at {url}: {e}"
                elif 'text/html' in content_type:
                    html_content = response.text
                    soup = BeautifulSoup(html_content, 'lxml')
                    for tag in soup(['script', 'style', 'header', 'footer', 'nav', 'aside', 'form', 'svg', 'canvas']):
                        tag.decompose()
                    for c in soup.find_all(text=lambda text: isinstance(text, Comment)):
                        c.extract()
                    text_content = soup.get_text(separator=' ', strip=True)
                else:
                    text_content = response.text

                return text_content.strip()

            except Exception as e:
                return f"Error fetching content from {url}: {e}"

    tasks = [fetch_and_convert(url) for url in urls]
    contents = await asyncio.gather(*tasks)
    return contents