import asyncio
import os
import httpx
from url_handler import fetch_urls_content
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

async def handle_search_query(query, api_key_manager, httpx_client, config=None):
    """
    Handle search queries using Serper API with fallback to Bing API.
    Returns results in structured XML format.
    """
    if config is None:
        config = {}

    max_urls = config.get('max_urls', 5)
    data = None
    error_messages = []

    try:
        serper_api_key = await api_key_manager.get_next_api_key('serper')
        if not serper_api_key:
            raise Exception("No Serper API key available.")

        serper_params = {
            'q': query,
            'num': max_urls,
            'autocorrect': 'false',
            'apiKey': serper_api_key
        }

        logger.info(f"Querying Serper API with params: {serper_params}")
        serper_response = await httpx_client.get(
            'https://google.serper.dev/search', 
            params=serper_params
        )
        
        if serper_response.status_code >= 400:
            raise httpx.HTTPStatusError(
                message=f"Bad status code: {serper_response.status_code}",
                request=serper_response.request,
                response=serper_response
            )

        data = serper_response.json()
        logger.info("Successfully received Serper API response")

    except Exception as serper_error:
        logger.warning(f"Serper API error: {serper_error}")
        error_messages.append(f'<search_error type="serper">{str(serper_error)}</search_error>')
        
        try:
            bing_subscription_key = os.getenv('BING_SEARCH_V7_SUBSCRIPTION_KEY')
            bing_endpoint = os.getenv('BING_SEARCH_V7_ENDPOINT')
            
            if not bing_subscription_key or not bing_endpoint:
                raise Exception("Bing API credentials missing from environment variables")

            headers = {'Ocp-Apim-Subscription-Key': bing_subscription_key}
            bing_params = {
                'q': query,
                'mkt': 'en-US',
                'count': max_urls,
                'responseFilter': 'Webpages'
            }

            logger.info("Attempting Bing API fallback")
            bing_response = await httpx_client.get(
                f"{bing_endpoint.rstrip('/')}/v7.0/search",
                headers=headers,
                params=bing_params
            )
            
            if bing_response.status_code >= 400:
                raise httpx.HTTPStatusError(
                    message=f"Bing error: {bing_response.status_code}",
                    request=bing_response.request,
                    response=bing_response
                )

            data = bing_response.json()
            logger.info("Successfully received Bing API response")

        except Exception as bing_error:
            logger.error(f"Bing API error: {bing_error}")
            error_messages.append(f'<search_error type="bing">{str(bing_error)}</search_error>')
            return "<search_results>\n" + "\n".join(error_messages) + "\n</search_results>"

    urls = []
    if not data:
        return '<search_results><search_error>No search results available from either provider</search_error></search_results>'

    if 'organic' in data:
        for result in data.get('organic', []):
            if 'link' in result:
                urls.append({
                    'url': result['link'],
                    'title': result.get('title', 'No title'),
                    'snippet': result.get('snippet', 'No snippet')
                })
                if len(urls) >= max_urls:
                    break

    elif 'webPages' in data:
        for page in data.get('webPages', {}).get('value', []):
            if 'url' in page:
                urls.append({
                    'url': page['url'],
                    'title': page.get('name', 'No title'),
                    'snippet': page.get('snippet', 'No snippet')
                })
                if len(urls) >= max_urls:
                    break

    if not urls:
        return '<search_results><search_error>No valid URLs found in search results</search_error></search_results>'

    url_list = [url_data['url'] for url_data in urls]
    contents = await fetch_urls_content(url_list, api_key_manager, httpx_client, config=config)

    results = ['<search_results>']
    results.extend(error_messages)
    
    for idx, ((url_data, content)) in enumerate(zip(urls, contents), start=1):
        results.append(
            f'<search_result id="{idx}">\n'
            f'<metadata>\n'
            f'<url>{url_data["url"]}</url>\n'
            f'<title>{url_data["title"]}</title>\n'
            f'<snippet>{url_data["snippet"]}</snippet>\n'
            f'</metadata>\n'
            f'<content>{content}</content>\n'
            f'</search_result>'
        )

    results.append('</search_results>')
    return "\n".join(results)