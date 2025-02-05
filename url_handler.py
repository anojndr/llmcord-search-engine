import asyncio
import re
import html
from bs4 import BeautifulSoup, Comment
import httpx
from youtube_handler import fetch_youtube_content
from reddit_handler import fetch_reddit_content
from PyPDF2 import PdfReader
from io import BytesIO
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

def smart_truncate_content(content, max_length=50000):
    """
    Smartly truncates content while preserving the most important information.
    
    Args:
        content (str): The content to truncate
        max_length (int): Maximum length of the truncated content
        
    Returns:
        str: Truncated content with preservation of key information
    """
    if len(content) <= max_length:
        return content
        
    def split_into_sections(text):
        sections = text.split('\n\n')
        return [s.strip() for s in sections if s.strip()]
    
    def score_section(section, position, total_sections):
        score = 0
        
        important_markers = [
            'summary', 'conclusion', 'overview', 'abstract',
            'key', 'main', 'important', 'critical', 'essential',
            'findings', 'results', 'analysis', 'introduction',
            'background', 'method', 'discussion'
        ]
        
        if position == 0:  
            score += 5
        elif position == total_sections - 1:  
            score += 3
        elif position < total_sections * 0.2:  
            score += 2
            
        length = len(section)
        if 100 <= length <= 1000:
            score += 2
        elif 50 <= length <= 2000:
            score += 1
        
        lower_section = section.lower()
        for marker in important_markers:
            if marker in lower_section:
                score += 2
                
        words = section.split()
        unique_words = len(set(words))
        if len(words) > 0:
            info_density = unique_words / len(words)
            score += info_density * 3
            
        if re.search(r'[•◦‣⁃▪▫-]', section):
            score += 1
        if re.search(r'\d+\.|[A-Za-z]\)', section):
            score += 1
            
        if len(words) < 10:
            score -= 2
            
        return score
    
    sections = split_into_sections(content)
    
    if not sections:
        return content[:max_length] + "... [Content truncated]"
    
    scored_sections = []
    for i, section in enumerate(sections):
        score = score_section(section, i, len(sections))
        scored_sections.append((section, score, i))
    
    scored_sections.sort(key=lambda x: (-x[1], x[2]))
    
    truncated_content = []
    current_length = 0
    
    first_section = sections[0]
    if first_section not in [s[0] for s in scored_sections[:3]]:
        truncated_content.append(first_section)
        current_length += len(first_section) + 2
    
    for section, score, original_pos in scored_sections:
        if current_length + len(section) + 100 > max_length:
            break
            
        if section not in truncated_content:
            truncated_content.append(section)
            current_length += len(section) + 2 
    
    final_sections = []
    for section in sections:
        if section in truncated_content:
            final_sections.append(section)
    
    if current_length < len(content):
        truncation_notice = "\n\n[Content truncated for length...]"
        if current_length + len(truncation_notice) <= max_length:
            final_sections.append(truncation_notice)
    
    return '\n\n'.join(final_sections)

def extract_urls_from_text(text):
    """Extract URLs from text using regex pattern."""
    url_pattern = re.compile(r'(https?://\S+)')
    urls = re.findall(url_pattern, text)
    return urls

def wrap_text_content(text):
    """Wraps plain text content in XML tags with type information."""
    return f'<text_content>\n{html.escape(text)}\n</text_content>'

async def fetch_urls_content(urls, api_key_manager, httpx_client, config=None):
    """
    Fetch and process content from a list of URLs with XML wrapping and smart truncation.
    Handles various content types including HTML, PDF, YouTube, and Reddit content.
    """
    if config is None:
        config = {}

    async def fetch_and_convert(url):
        """
        Fetch and convert content from a single URL with appropriate XML tags and smart truncation.
        Includes specialized handling for different content types and platforms.
        """
        try:
            if 'youtube.com' in url or 'youtu.be' in url:
                content = await fetch_youtube_content(url, api_key_manager, httpx_client)
                return f'<youtube_content>\n{content}\n</youtube_content>'
                
            elif 'reddit.com' in url or 'redd.it' in url:
                content = await fetch_reddit_content(url, api_key_manager, httpx_client)
                return f'<reddit_content>\n{content}\n</reddit_content>'
            
            response = await httpx_client.get(url, timeout=10.0, follow_redirects=True)
            response.raise_for_status()
            content_type = response.headers.get('Content-Type', '').lower()

            if 'application/pdf' in content_type:
                try:
                    pdf_bytes = response.content
                    reader = PdfReader(BytesIO(pdf_bytes))
                    text_content = []
                    
                    metadata = reader.metadata
                    if metadata:
                        meta_content = []
                        for key, value in metadata.items():
                            if value and str(value).strip():
                                meta_content.append(f'<meta name="{html.escape(key)}">{html.escape(str(value))}</meta>')
                        if meta_content:
                            text_content.append('<metadata>' + '\n'.join(meta_content) + '</metadata>')
                    
                    page_contents = []
                    for i, page in enumerate(reader.pages, 1):
                        text = page.extract_text()
                        if text and text.strip():
                            page_contents.append(f'<page number="{i}">\n{html.escape(text.strip())}\n</page>')
                    
                    if page_contents:
                        text_content.append('<content>' + '\n'.join(page_contents) + '</content>')
                    else:
                        text_content.append('<error>No extractable text found in PDF.</error>')
                    
                    full_content = '\n'.join(text_content)
                    truncated_content = smart_truncate_content(full_content)
                    
                    return f'<pdf_content>\n{truncated_content}\n</pdf_content>'
                except Exception as e:
                    logger.error(f"Error processing PDF from {url}: {e}")
                    return f'<error>Error extracting text from PDF: {str(e)}</error>'

            elif 'text/html' in content_type:
                try:
                    html_content = response.text
                    soup = BeautifulSoup(html_content, 'lxml')
                    
                    for tag in soup(['script', 'style', 'header', 'footer', 'nav', 'aside', 'form', 'svg', 'canvas', 'iframe']):
                        tag.decompose()
                    for comment in soup.find_all(text=lambda text: isinstance(text, Comment)):
                        comment.extract()
                    
                    metadata = []
                    if soup.title:
                        metadata.append(f'<title>{html.escape(soup.title.string)}</title>')
                    
                    meta_tags = {
                        'description': ('name', 'description'),
                        'keywords': ('name', 'keywords'),
                        'author': ('name', 'author'),
                        'og:title': ('property', 'og:title'),
                        'og:description': ('property', 'og:description')
                    }
                    
                    for meta_name, (attr_type, attr_value) in meta_tags.items():
                        meta_tag = soup.find('meta', {attr_type: attr_value})
                        if meta_tag and meta_tag.get('content'):
                            metadata.append(f'<meta name="{meta_name}">{html.escape(meta_tag["content"])}</meta>')
                    
                    main_content = soup.get_text(separator=' ', strip=True)
                    truncated_content = smart_truncate_content(main_content)
                    
                    content_parts = []
                    if metadata:
                        content_parts.append('<metadata>\n' + '\n'.join(metadata) + '\n</metadata>')
                    content_parts.append(f'<main_content>\n{html.escape(truncated_content)}\n</main_content>')
                    
                    return f'<webpage_content>\n' + '\n'.join(content_parts) + '\n</webpage_content>'
                
                except Exception as e:
                    logger.error(f"Error processing HTML from {url}: {e}")
                    return f'<error>Error processing HTML content: {str(e)}</error>'

            else:
                text_content = response.text
                truncated_content = smart_truncate_content(text_content)
                return f'<raw_content>\n{html.escape(truncated_content)}\n</raw_content>'

        except httpx.TimeoutException:
            logger.error(f"Timeout while fetching {url}")
            return f'<error>Request timed out while fetching {url}</error>'
        except httpx.HTTPError as e:
            logger.error(f"HTTP error while fetching {url}: {e}")
            return f'<error>HTTP error while fetching {url}: {str(e)}</error>'
        except Exception as e:
            logger.error(f"Unexpected error while processing {url}: {e}")
            return f'<error>Error processing {url}: {str(e)}</error>'

    tasks = [fetch_and_convert(url) for url in urls]
    try:
        contents = await asyncio.gather(*tasks)
        return contents
    except Exception as e:
        logger.error(f"Error fetching multiple URLs: {e}")
        return [f'<error>Error fetching multiple URLs: {str(e)}</error>']