"""
SauceNAO Handler Module

Provides functionality to perform a SauceNAO image source lookup using its API.
It downloads the given image, sends it to the SauceNAO API, and formats the results in XML.
"""

import logging
import httpx
import html
from io import BytesIO
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

SAUCENAO_API_URL = "https://saucenao.com/search.php"

async def handle_saucenao_query(
    image_url: str,
    api_key: str,
    httpx_client: httpx.AsyncClient,
    min_similarity: float = 50.0
) -> str:
    """
    Look up an image source using the SauceNAO API.

    Args:
        image_url (str): URL of the image to search.
        api_key (str): SauceNAO API key.
        httpx_client (httpx.AsyncClient): HTTP client for requests.
        min_similarity (float): Minimum similarity threshold to consider (default: 50.0).

    Returns:
        str: XML-formatted results from SauceNAO.
    """
    try:
        # Download the image to send to SauceNAO.
        image_response = await httpx_client.get(image_url)
        image_response.raise_for_status()
        image_data = image_response.content
        
        # Prepare multipart file upload.
        files = {
            'file': ('image.png', image_data, 'image/png')
        }
        
        params = {
            'output_type': 2,  
            'api_key': api_key,
            'numres': 16,  
            'db': 999,  
            'dedupe': 2  
        }
        
        response = await httpx_client.post(
            SAUCENAO_API_URL,
            params=params,
            files=files,
            timeout=30.0
        )
        response.raise_for_status()
        data = response.json()
        
        xml_parts = ['<saucenao_results>']
        
        header = data.get('header', {})
        xml_parts.extend([
            '<header>',
            f'<user_id>{header.get("user_id", "")}</user_id>',
            f'<account_type>{header.get("account_type", "")}</account_type>',
            f'<short_limit>{header.get("short_limit", "")}</short_limit>',
            f'<long_limit>{header.get("long_limit", "")}</long_limit>',
            f'<long_remaining>{header.get("long_remaining", "")}</long_remaining>',
            f'<short_remaining>{header.get("short_remaining", "")}</short_remaining>',
            f'<minimum_similarity>{header.get("minimum_similarity", "")}</minimum_similarity>',
            f'<query_image>{html.escape(header.get("query_image", ""))}</query_image>',
            f'<results_returned>{header.get("results_returned", "")}</results_returned>',
            '</header>'
        ])
        
        results = data.get('results', [])
        for result in results:
            header = result.get('header', {})
            data_obj = result.get('data', {})
            
            similarity = float(header.get('similarity', 0))
            # Skip results with similarity below the threshold.
            if similarity < min_similarity:
                continue
                
            xml_parts.extend([
                '<result>',
                '<result_header>',
                f'<similarity>{header.get("similarity", "")}</similarity>',
                f'<thumbnail>{html.escape(header.get("thumbnail", ""))}</thumbnail>',
                f'<index_id>{header.get("index_id", "")}</index_id>',
                f'<index_name>{html.escape(header.get("index_name", ""))}</index_name>',
                '</result_header>',
                '<result_data>'
            ])
            
            # Convert result data into XML elements.
            for key, value in data_obj.items():
                if isinstance(value, list):
                    xml_parts.extend([
                        f'<{key}>',
                        '\n'.join(f'<item>{html.escape(str(item))}</item>' for item in value),
                        f'</{key}>'
                    ])
                else:
                    xml_parts.append(f'<{key}>{html.escape(str(value))}</{key}>')
            
            xml_parts.extend(['</result_data>', '</result>'])
        
        xml_parts.append('</saucenao_results>')
        return '\n'.join(xml_parts)
        
    except httpx.HTTPError as http_err:
        logger.error(f"HTTP error during SauceNAO request: {http_err}")
        return f'<saucenao_results><error>HTTP error during SauceNAO request: {str(http_err)}</error></saucenao_results>'
    except Exception as e:
        logger.error(f"Error processing SauceNAO request: {e}")
        return f'<saucenao_results><error>Error processing SauceNAO request: {str(e)}</error></saucenao_results>'