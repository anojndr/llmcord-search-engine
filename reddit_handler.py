import httpx
import logging
import random
import os
import html

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
    Loads proxies from the specified file. Each line can be a simple URL or include user:pass.
    Returns a list of proxy URLs, or an empty list if the file is not found or empty.
    """
    filepath = _find_proxies_file(filename)
    proxies = []
    if filepath:
        logger.info("Loading proxies from %s", filepath)
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    if '@' not in line and ':' in line:
                        parts = line.split(':')
                        if len(parts) == 2:
                            ip, port = parts
                            proxy_url = f"http://{ip}:{port}"
                        elif len(parts) == 4:
                            ip, port, user, password = parts
                            proxy_url = f"http://{user}:{password}@{ip}:{port}"
                        else:
                            continue
                        proxies.append(proxy_url)
                    else:
                        proxies.append(line)
    else:
        logger.warning("No proxies file found.")
    return proxies

def get_random_proxy(proxies_list=None):
    """
    Randomly select a proxy URL string from proxies_list.
    Returns None if proxies_list is empty.
    """
    if proxies_list is None:
        proxies_list = load_proxies()
    if not proxies_list:
        return None
    return random.choice(proxies_list)

def _parse_comment_tree(children, comment_list):
    """
    Recursively traverse Reddit 't1' comments, appending each comment's body to comment_list.
    Returns XML-structured comment data.
    """
    for child in children:
        if child.get('kind') == 't1':
            data = child.get('data', {})
            comment_data = {
                'body': html.escape(data.get('body', '')),
                'author': html.escape(data.get('author', '[deleted]')),
                'score': data.get('score', 0),
                'created_utc': data.get('created_utc', 0)
            }
            if comment_data['body']:
                comment_list.append(comment_data)
            replies = data.get('replies')
            if isinstance(replies, dict):
                new_children = replies.get('data', {}).get('children', [])
                _parse_comment_tree(new_children, comment_list)

async def fetch_reddit_content(url, api_key_manager, httpx_client=None, retries=3):
    """
    Fetches Reddit submission + comments by appending .json to the final redirect URL
    and parsing the returned JSON structure. Returns content in XML format.
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
        httpx_client = httpx.AsyncClient(proxies=proxies, timeout=10.0, http2=True)

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
            return "<reddit_response><error>No valid data received from Reddit.</error></reddit_response>"

        first_listing = data[0]
        submission_children = first_listing.get('data', {}).get('children', [])
        if not submission_children:
            return "<reddit_response><error>No submission data found.</error></reddit_response>"

        submission_data = submission_children[0].get('data', {})
        title = html.escape(submission_data.get('title', ''))
        selftext = html.escape(submission_data.get('selftext', ''))
        author = html.escape(submission_data.get('author', '[deleted]'))
        score = submission_data.get('score', 0)
        upvote_ratio = submission_data.get('upvote_ratio', 0)
        created_utc = submission_data.get('created_utc', 0)
        num_comments = submission_data.get('num_comments', 0)
        subreddit = html.escape(submission_data.get('subreddit', ''))

        comments_list = []
        if len(data) > 1:
            second_listing = data[1]
            comments_children = second_listing.get('data', {}).get('children', [])
            _parse_comment_tree(comments_children, comments_list)

        content = [
            '<reddit_response>',
            '<post>',
            f'<metadata>',
            f'<subreddit>{subreddit}</subreddit>',
            f'<author>{author}</author>',
            f'<created_utc>{created_utc}</created_utc>',
            f'<score>{score}</score>',
            f'<upvote_ratio>{upvote_ratio}</upvote_ratio>',
            f'<num_comments>{num_comments}</num_comments>',
            '</metadata>',
            f'<title>{title}</title>',
            f'<selftext>{selftext}</selftext>',
            '</post>',
            '<comments>'
        ]
        
        for comment in comments_list:
            content.extend([
                '<comment>',
                f'<author>{comment["author"]}</author>',
                f'<score>{comment["score"]}</score>',
                f'<created_utc>{comment["created_utc"]}</created_utc>',
                f'<body>{comment["body"]}</body>',
                '</comment>'
            ])
        
        content.extend(['</comments>', '</reddit_response>'])

        return '\n'.join(content)

    except (httpx.ProxyError, httpx.ConnectError, httpx.ReadError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
        logger.warning("Proxy or connection error: %s", e)
        if retries > 0:
            logger.info("Retrying with a different proxy (attempts left: %d)", retries)
            if httpx_client:
                await httpx_client.aclose()
            return await fetch_reddit_content(url, api_key_manager, None, retries - 1)
        else:
            return f'<reddit_response><error>Error fetching Reddit content after multiple retries: {str(e)}</error></reddit_response>'

    except Exception as e:
        logger.error("Error fetching Reddit content: %s", str(e))
        return f'<reddit_response><error>Error fetching Reddit content: {str(e)}</error></reddit_response>'