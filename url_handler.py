"""
URL Handler Module

This module is responsible for:

- Extracting URLs from text using regex.
- Fetching content from URLs (e.g., web pages, PDFs, YouTube, Reddit)
    and converting them into plain text formatted strings.
"""

import asyncio
import re
from typing import List, Optional, Dict, Any
from bs4 import BeautifulSoup, Comment
import httpx
from api_key_manager import APIKeyManager
from youtube_handler import fetch_youtube_content
from reddit_handler import fetch_reddit_content
from PyPDF2 import PdfReader
from io import BytesIO

def extract_urls_from_text(text: str) -> List[str]:
    """
    Extract URLs from the provided text using a regex pattern.

    Args:
        text: Input text.

    Returns:
        A list of URLs found.
    """
    url_pattern = re.compile(r'(https?://\S+)')
    urls: List[str] = re.findall(url_pattern, text)
    return urls

async def fetch_urls_content(
    urls: List[str],
    api_key_manager: APIKeyManager,
    httpx_client: httpx.AsyncClient,
    config: Optional[Dict[str, Any]] = None
) -> List[str]:
    """
    For each URL in the list, fetch its content and convert it to plain text.
    Handles special URLs like YouTube and Reddit differently.

    For non-YouTube/Reddit links, the code first attempts to extract content by
    prepending "https://r.jina.ai/" to the URL. Because this service is rate limited,
    if the call fails an HTTP error is raised and the code falls back to the original
    extraction method (using httpx and BeautifulSoup).

    Args:
        urls: List of URLs.
        api_key_manager: API key manager.
        httpx_client: HTTP client.
        config: Configuration dictionary.

    Returns:
        List of plain text content strings, each truncated to 20,000 characters.
    """
    if config is None:
        config = {}

    async def fetch_and_convert(url: str) -> str:
        if 'youtube.com' in url or 'youtu.be' in url:
            content: str = await fetch_youtube_content(url, api_key_manager, httpx_client)
            return f"YouTube Content:\n{content[:20000]}"
        elif 'reddit.com' in url or 'redd.it' in url:
            content: str = await fetch_reddit_content(url, api_key_manager, httpx_client)
            return f"Reddit Content:\n{content[:20000]}"
        else:
            jina_url: str = "https://r.jina.ai/" + url
            try:
                response: httpx.Response = await httpx_client.get(jina_url, timeout=10.0)
                response.raise_for_status()
                text_content: str = response.text.strip()[:20000]
                return f"Extracted Content (jina_ai):\n{text_content}"
            except httpx.HTTPError as http_err:
                try:
                    response: httpx.Response = await httpx_client.get(url, timeout=10.0, follow_redirects=True)
                    response.raise_for_status()
                    content_type: str = response.headers.get('Content-Type', '')

                    if 'application/pdf' in content_type:
                        pdf_bytes: bytes = response.content
                        try:
                            reader: PdfReader = PdfReader(BytesIO(pdf_bytes))
                            text_content: str = ''
                            for page in reader.pages:
                                text: Optional[str] = page.extract_text()
                                if text:
                                    text_content += text + '\n'
                            if not text_content:
                                text_content = f"No extractable text found in PDF at {url}."
                            return f"PDF Content (fallback):\n{text_content[:20000]}"
                        except Exception as e:
                            return f"Error extracting text from PDF at {url}: {e}"
                    elif 'text/html' in content_type:
                        html_content: str = response.text
                        soup: BeautifulSoup = BeautifulSoup(html_content, 'lxml')
                        for tag in soup(['script', 'style', 'header', 'footer', 'nav', 'aside', 'form', 'svg', 'canvas']):
                            tag.decompose()
                        for c in soup.find_all(text=lambda text: isinstance(text, Comment)):
                            c.extract()
                        text_content: str = soup.get_text(separator=' ', strip=True)[:20000]
                        return f"Extracted Content (BeautifulSoup fallback):\n{text_content}"
                    else:
                        text_content: str = response.text[:20000]
                        return text_content
                except Exception as e:
                    return f"Error fetching content from {url}: {e}"
            except Exception as e:
                return f"Error fetching content with jina_ai from {url}: {e}"

    tasks: List[asyncio.Task] = [fetch_and_convert(url) for url in urls]
    contents: List[str] = await asyncio.gather(*tasks)
    return contents