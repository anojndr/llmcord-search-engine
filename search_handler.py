import asyncio
import os
import httpx
from url_handler import fetch_urls_content

async def handle_search_query(query, api_key_manager, httpx_client, config=None):
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

        serper_response = await httpx_client.get(
            'https://google.serper.dev/search', 
            params=serper_params
        )
        serper_response.raise_for_status()
        data = serper_response.json()

    except Exception as serper_error:
        error_messages.append(f"Serper error: {str(serper_error)}")
        
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

            bing_response = await httpx_client.get(
                f"{bing_endpoint}/bing/v7.0/search",
                headers=headers,
                params=bing_params
            )
            bing_response.raise_for_status()
            data = bing_response.json()

        except Exception as bing_error:
            error_messages.append(f"Bing fallback error: {str(bing_error)}")
            return "\n".join(error_messages)

    urls = []
    if not data:
        return "No search results available from either provider"

    if 'organic' in data:
        for result in data.get('organic', []):
            if 'link' in result:
                urls.append(result['link'])
                if len(urls) >= max_urls:
                    break

    elif 'webPages' in data:
        for page in data.get('webPages', {}).get('value', []):
            if 'url' in page:
                urls.append(page['url'])
                if len(urls) >= max_urls:
                    break

    if not urls:
        return "No valid URLs found in search results"

    contents = await fetch_urls_content(urls, api_key_manager, httpx_client, config=config)

    results = []
    for idx, (url, content) in enumerate(zip(urls, contents), start=1):
        results.append(f'url {idx}: "{url}"')
        results.append(f'url {idx} content: "{content}"\n')

    return "\n".join(results)