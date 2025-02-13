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
    """Extract URLs from text using regex pattern."""
    url_pattern = re.compile(r'(https?://\S+)')
    urls = re.findall(url_pattern, text)
    return urls

def wrap_text_content(text):
    """Wraps plain text content in XML tags with type information."""
    return f'<text_content>\n{html.escape(text)}\n</text_content>'

async def fetch_urls_content(urls, api_key_manager, httpx_client, config=None):
    """Fetch and process content from a list of URLs with XML wrapping."""
    if config is None:
        config = {}

    async def fetch_and_convert(url):
        """Fetch and convert content from a single URL with appropriate XML tags."""
        if 'youtube.com' in url or 'youtu.be' in url:
            content = await fetch_youtube_content(url, api_key_manager, httpx_client)
            return f'<youtube_content>\n{content}\n</youtube_content>'
        elif 'reddit.com' in url or 'redd.it' in url:
            content = await fetch_reddit_content(url, api_key_manager, httpx_client)
            return f'<reddit_content>\n{content}\n</reddit_content>'
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
                        return f'<pdf_content>\n{text_content}\n</pdf_content>'
                    except Exception as e:
                        return f'<error>Error extracting text from PDF at {url}: {e}</error>'
                elif 'text/html' in content_type:
                    html_content = response.text
                    soup = BeautifulSoup(html_content, 'lxml')
                    
                    for tag in soup(['script', 'style', 'header', 'footer', 'nav', 'aside', 'form', 'svg', 'canvas']):
                        tag.decompose()
                    for c in soup.find_all(text=lambda text: isinstance(text, Comment)):
                        c.extract()
                    
                    title = soup.title.string if soup.title else 'No title found'
                    meta_desc = soup.find('meta', {'name': 'description'})
                    description = meta_desc['content'] if meta_desc else 'No description found'
                    
                    text_content = soup.get_text(separator=' ', strip=True)
                    
                    return (
                        f'<webpage_content>\n'
                        f'<metadata>\n'
                        f'<title>{title}</title>\n'
                        f'<description>{description}</description>\n'
                        f'</metadata>\n'
                        f'<main_content>{text_content}</main_content>\n'
                        f'</webpage_content>'
                    )
                else:
                    return f'<error>Unsupported content type: {content_type}</error>'

            except Exception as e:
                return f'<error>Error fetching content from {url}: {e}</error>'

    tasks = [fetch_and_convert(url) for url in urls]
    contents = await asyncio.gather(*tasks)
    return contents