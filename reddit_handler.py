import httpx
import logging
import random
import os

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

def _find_proxies_file(filename="proxies.txt"):
    """
    Attempts to find a file named 'proxies.txt' first in the current directory,
    then in /etc/secrets. Returns the file path if it exists, else None.
    """
    if os.path.exists(filename):
        return os.path.abspath(filename)
    alt_filename = os.path.join("/etc/secrets", filename)
    if os.path.exists(alt_filename):
        return alt_filename
    return None

def load_proxies(filename="proxies.txt"):
    """
    Loads proxies from the specified file.
    Returns a list of proxy URLs, or an empty list if the file is not found or empty.
    """
    filepath = _find_proxies_file(filename)
    proxies = []
    if filepath:
        logger.info("Loading proxies from %s", filepath)
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(':')
                if len(parts) == 4:
                    ip, port, user, password = parts
                    proxy_url = f"http://{user}:{password}@{ip}:{port}"
                    proxies.append(proxy_url)
    else:
        logger.warning("No proxies file found.")
    return proxies

def get_random_proxy(proxies_list):
    """
    Randomly select a proxy URL string from proxies_list.
    Returns None if proxies_list is empty.
    """
    if not proxies_list:
        return None
    return random.choice(proxies_list)

def _parse_comment_tree(children, comment_list):
    """
    Recursively traverse Reddit 't1' comments, appending each comment's body to comment_list.
    """
    for child in children:
        if child.get('kind') == 't1':
            data = child.get('data', {})
            body = data.get('body', '')
            if body:
                comment_list.append(body)
            replies = data.get('replies')
            if isinstance(replies, dict):
                new_children = replies.get('data', {}).get('children', [])
                _parse_comment_tree(new_children, comment_list)

async def fetch_reddit_content(url, api_key_manager, httpx_client=None, retries=3):
    """
    Fetches Reddit submission + comments by appending .json to the final redirect URL
    and parsing the returned JSON structure (which typically consists of two listings).
    Uses a random proxy from proxies.txt for each request.
    """
    proxies = load_proxies()
    proxy_url = get_random_proxy(proxies)

    if proxy_url:
        logger.info("Using proxy for Reddit: %s", proxy_url)
        proxies = {"http://": proxy_url, "https://": proxy_url}
    else:
        proxies = None

    if httpx_client is None:
        httpx_client = httpx.AsyncClient(proxies=proxies, timeout=10.0)

    try:
        response = await httpx_client.get(url, follow_redirects=True)
        response.raise_for_status()
        final_url = str(response.url)

        base, sep, query = final_url.partition('?')
        if sep:
            json_url = base.rstrip('/') + '.json?' + query
        else:
            json_url = base.rstrip('/') + '.json'

        json_response = await httpx_client.get(json_url, follow_redirects=True)
        json_response.raise_for_status()
        data = json_response.json()

        if not isinstance(data, list) or len(data) < 1:
            return "No valid data received from Reddit."

        first_listing = data[0]
        submission_children = first_listing.get('data', {}).get('children', [])
        if not submission_children:
            return "No submission data found."

        submission_data = submission_children[0].get('data', {})
        title = submission_data.get('title', '')
        selftext = submission_data.get('selftext', '')

        comments_list = []
        if len(data) > 1:
            second_listing = data[1]
            comments_children = second_listing.get('data', {}).get('children', [])
            _parse_comment_tree(comments_children, comments_list)

        content = f"Title: {title}\n\nSelftext:\n{selftext}\n\nComments:\n"
        for idx, comment in enumerate(comments_list, start=1):
            content += f"{idx}. {comment}\n"

        return content.strip() or "No content found."

    except (httpx.ProxyError, httpx.ConnectError, httpx.ReadError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
        logger.warning("Proxy or connection error: %s", e)
        if retries > 0:
            logger.info("Retrying with a different proxy (attempts left: %d)", retries)
            if httpx_client:
                await httpx_client.aclose()
            return await fetch_reddit_content(url, api_key_manager, None, retries - 1)
        else:
            return f"Error fetching Reddit content after multiple retries: {e}"

    except Exception as e:
        return f"Error fetching Reddit content: {e}"