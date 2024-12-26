# search_handler.py

import asyncio
import html2text
import httpx


async def handle_search_query(query, api_key, max_urls=2):
    headers = {
        'Content-Type': 'application/json'
    }
    params = {
        'q': query,
        'apiKey': api_key
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get('https://google.serper.dev/search', params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        return f"Error fetching search results: {e}"

    # Get the top N URLs from the search results
    urls = []
    for result in data.get('organic', []):
        if 'link' in result:
            urls.append(result['link'])
            if len(urls) >= max_urls:
                break

    contents = await fetch_urls_content(urls)

    # Format the results
    results = []
    for idx, (url, content) in enumerate(zip(urls, contents), start=1):
        results.append(f'url {idx}: "{url}"')
        results.append(f'url {idx} content: "{content}"\n')

    return "\n".join(results)


async def fetch_urls_content(urls):
    async def fetch_and_convert(url):
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                html_content = response.text
                text_content = html2text.html2text(html_content)
                return text_content.strip()
        except Exception as e:
            return f"Error fetching content from {url}: {e}"

    tasks = [fetch_and_convert(url) for url in urls]
    contents = await asyncio.gather(*tasks)
    return contents