"""
URL Handler Module

This module is responsible for:

- Extracting URLs from text using regex.
- Wrapping plain text content.
- Fetching content from URLs (e.g., web pages, PDFs, YouTube, Reddit)
    and converting them into plain text formatted strings.
"""

import asyncio
import re
import html
from bs4 import BeautifulSoup, Comment
import httpx
from youtube_handler import fetch_youtube_content
from reddit_handler import fetch_reddit_content
from PyPDF2 import PdfReader
from io import BytesIO


def extract_urls_from_text(text):
    """
    Extract URLs from the provided text using a regex pattern.
    
    Args:
        text (str): Input text.
    
    Returns:
        list: A list of URLs found.
    """
    url_pattern = re.compile(r'(https?://\S+)')
    urls = re.findall(url_pattern, text)
    return urls


def wrap_text_content(text):
    """
    Wrap plain text in a simple block.
    
    Args:
        text (str): Text to wrap.
    
    Returns:
        str: The plain text.
    """
    return text


async def fetch_urls_content(urls, api_key_manager, httpx_client, config=None):
    """
    For each URL in the list, fetch its content and convert it to plain text.
    Handles special URLs like YouTube and Reddit differently.
    
    For non-YouTube/Reddit links, the code first attempts to extract content by
    prepending "https://r.jina.ai/" to the URL. Because this service is rate limited,
    if the call fails an HTTP error is raised and the code falls back to the original
    extraction method (using httpx and BeautifulSoup).
    
    Args:
        urls (list): List of URLs.
        api_key_manager: API key manager.
        httpx_client (httpx.AsyncClient): HTTP client.
        config (dict, optional): Configuration dictionary.
    
    Returns:
        list: List of plain text content strings.
    """
    if config is None:
        config = {}

    async def fetch_and_convert(url):
        if 'youtube.com' in url or 'youtu.be' in url:
            content = await fetch_youtube_content(url, api_key_manager, httpx_client)
            return f"YouTube Content:\n{content}"
        elif 'reddit.com' in url or 'redd.it' in url:
            content = await fetch_reddit_content(url, api_key_manager, httpx_client)
            return f"Reddit Content:\n{content}"
        else:
            # First attempt: use the Jina-AI extraction endpoint.
            jina_url = "https://r.jina.ai/" + url
            try:
                response = await httpx_client.get(jina_url, timeout=10.0)
                response.raise_for_status()
                text_content = response.text.strip()
                return f"Extracted Content (jina_ai):\n{text_content}"
            except httpx.HTTPError as http_err:
                # If an HTTPError (e.g. rate limit exceeded) occurs, fall back to direct extraction.
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
                            return f"PDF Content (fallback):\n{text_content}"
                        except Exception as e:
                            return f"Error extracting text from PDF at {url}: {e}"
                    elif 'text/html' in content_type:
                        html_content = response.text
                        soup = BeautifulSoup(html_content, 'lxml')
                        # Remove non-content elements
                        for tag in soup(['script', 'style', 'header', 'footer', 'nav', 'aside', 'form', 'svg', 'canvas']):
                            tag.decompose()
                        # Remove HTML comments
                        for c in soup.find_all(text=lambda text: isinstance(text, Comment)):
                            c.extract()
                        text_content = soup.get_text(separator=' ', strip=True)
                        return f"Extracted Content (BeautifulSoup fallback):\n{text_content}"
                    else:
                        text_content = response.text
                        return text_content
                except Exception as e:
                    return f"Error fetching content from {url}: {e}"
            except Exception as e:
                return f"Error fetching content with jina_ai from {url}: {e}"

    tasks = [fetch_and_convert(url) for url in urls]
    contents = await asyncio.gather(*tasks)
    return contents