import asyncio
from url_handler import fetch_urls_content
import httpx

async def handle_search_query(query, api_key, max_urls=2, config=None):
    if config is None:
        config = {}
    headers = {
        'Content-Type': 'application/json',
        'X-API-KEY': api_key
    }
    data = {
        'q': query,
        'num': max_urls
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post('https://google.serper.dev/search', json=data, headers=headers)
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        return f"Error fetching search results: {e}"

    urls = []
    for result in data.get('organic', []):
        if 'link' in result:
            urls.append(result['link'])
            if len(urls) >= max_urls:
                break

    contents = await fetch_urls_content(urls, config=config)

    results = []
    for idx, (url, content) in enumerate(zip(urls, contents), start=1):
        results.append(f'url {idx}: "{url}"')
        results.append(f'url {idx} content: "{content}"\n')

    return "\n".join(results)