"""
URL Handler Module

This module is responsible for:

- Extracting URLs from text using regex.
- Fetching content from URLs (e.g., web pages, PDFs, YouTube, Reddit)
    and converting them into plain text formatted strings.
Synchronous parsing operations are offloaded to threads for concurrency.
"""

import asyncio
import logging
import re
from typing import Dict, Any, List, Optional

import httpx
from bs4 import BeautifulSoup, Comment
from io import BytesIO
from PyPDF2 import PdfReader

from config.api_key_manager import APIKeyManager
from providers.youtube_handler import fetch_youtube_content
from providers.reddit_handler import fetch_reddit_content

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def extract_urls_from_text(text: str) -> List[str]:
    """
    Extract URLs from the provided text using a regex pattern.

    Args:
        text: Input text.

    Returns:
        A list of URLs found.
    """
    url_pattern = re.compile(r'(https?://\S+)')
    urls = re.findall(url_pattern, text)
    return urls


def parse_html_content(html_content: str) -> str:
    """
    Parse HTML content synchronously using BeautifulSoup and extract text.
    This function is run in a thread to avoid blocking the async event loop.

    Args:
        html_content: Raw HTML string.

    Returns:
        Extracted text content.
    """
    try:
        # Create BeautifulSoup object
        soup = BeautifulSoup(html_content, 'lxml')
        
        # Remove script, style, and other non-content elements
        for tag in soup(['script', 'style', 'header', 'footer', 'nav', 'aside', 'form', 'svg', 'canvas']):
            tag.decompose()
            
        # Remove comments
        for comment in soup.find_all(text=lambda text: isinstance(text, Comment)):
            comment.extract()
            
        # Extract text
        text_content = soup.get_text(separator=' ', strip=True)[:20000]
        return text_content
    except Exception as e:
        logger.error(f"Error parsing HTML content: {e}", exc_info=True)
        return f"Error extracting text from HTML: {e}"


def parse_pdf_content(pdf_bytes: bytes) -> str:
    """
    Extract text from PDF bytes synchronously using PyPDF2.
    This function is run in a thread to avoid blocking the async event loop.

    Args:
        pdf_bytes: Raw PDF bytes.

    Returns:
        Extracted text content or error message.
    """
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        text_content = ''
        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_content += text + '\n'
        if not text_content:
            text_content = "No extractable text found in PDF."
        return text_content[:20000]
    except Exception as e:
        logger.error(f"Error extracting text from PDF: {e}", exc_info=True)
        return f"Error extracting text from PDF: {e}"


async def fetch_single_url_content(
    url: str, 
    api_key_manager: APIKeyManager, 
    httpx_client: httpx.AsyncClient
) -> str:
    """
    Fetch and convert the content of a single URL to plain text.
    Synchronous parsing (HTML, PDF) is offloaded to threads.

    Args:
        url: The URL to fetch content from.
        api_key_manager: API key manager instance.
        httpx_client: HTTP client instance.

    Returns:
        Plain text content string, truncated to 20,000 characters.
    """
    # Handle special URL types
    if 'youtube.com' in url or 'youtu.be' in url:
        content = await fetch_youtube_content(url, api_key_manager, httpx_client)
        # Return content without the prefix for YouTube URLs
        return content[:20000]  # Modified to remove "YouTube Content:" prefix
    elif 'reddit.com' in url or 'redd.it' in url:
        content = await fetch_reddit_content(url, api_key_manager, httpx_client)
        # Return content without the prefix for Reddit URLs
        return content[:20000]  # Modified to remove "Reddit Content:" prefix
    
    # Try Jina first
    try:
        jina_url = "https://r.jina.ai/" + url
        logger.debug(f"Trying Jina URL: {jina_url}")
        
        response = await httpx_client.get(jina_url, timeout=10.0)
        response.raise_for_status()
        text_content = response.text.strip()[:20000]
        return f"__JINA_SUCCESS__\n{text_content}"
    except httpx.HTTPError:
        logger.debug(f"Jina failed for URL: {url}, falling back to direct fetch")
    except Exception as e:
        logger.error(f"Error fetching content with jina_ai from {url}: {e}", exc_info=True)
    
    # Fallback to direct fetch
    try:
        logger.debug(f"Fetching URL directly: {url}")
        response = await httpx_client.get(url, timeout=10.0, follow_redirects=True)
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', '')

        # Handle different content types
        if 'application/pdf' in content_type:
            logger.debug(f"Processing PDF content from {url}")
            pdf_bytes = response.content
            text_content = await asyncio.to_thread(parse_pdf_content, pdf_bytes)
            return f"PDF Content (fallback):\n{text_content}"
        elif 'text/html' in content_type:
            logger.debug(f"Processing HTML content from {url}")
            html_content = response.text
            text_content = await asyncio.to_thread(parse_html_content, html_content)
            return f"Extracted Content (BeautifulSoup fallback):\n{text_content}"
        else:
            logger.debug(f"Processing plain text content from {url}")
            text_content = response.text[:20000]
            return text_content
    except Exception as e:
        logger.error(f"Error fetching content from {url}: {e}", exc_info=True)
        return f"Error fetching content from {url}: {e}"


async def fetch_urls_content(
    urls: List[str],
    api_key_manager: APIKeyManager,
    httpx_client: httpx.AsyncClient,
    config: Optional[Dict[str, Any]] = None
) -> List[str]:
    """
    For each URL in the list, fetch its content and convert it to plain text.
    Handles special URLs like YouTube and Reddit differently.

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

    # Create a task for each URL
    logger.info(f"Fetching content for {len(urls)} URLs")
    tasks = [
        fetch_single_url_content(url, api_key_manager, httpx_client) 
        for url in urls
    ]
    
    # Execute all tasks concurrently
    contents = await asyncio.gather(*tasks)
    logger.info(f"Completed content fetch for {len(urls)} URLs")
    
    return contents