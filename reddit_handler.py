import re

async def fetch_reddit_content(url, api_key_manager, httpx_client):
    """
    Fetches Reddit content by adding .json to the URL and parsing the returned JSON
    rather than using asyncpraw.
    """
    # Ensure the URL ends with ".json"
    if not url.endswith('.json'):
        if url.endswith('/'):
            url += '.json'
        else:
            url += '/.json'

    def traverse_comments(children, all_comments):
        """
        Recursively collect all comment bodies (including replies) into all_comments.
        """
        for child in children:
            kind = child.get('kind')
            if kind == 't1':
                # This is a standard comment
                comment_body = child['data'].get('body', '[deleted]')
                all_comments.append(comment_body)
                replies = child['data'].get('replies')
                if isinstance(replies, dict):
                    more_children = replies['data'].get('children', [])
                    traverse_comments(more_children, all_comments)
            elif kind == 'more':
                # If you want to handle 'more' items, do so here. We'll skip them.
                pass

    try:
        # Make a direct request to Reddit's .json endpoint
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = await httpx_client.get(url, headers=headers, timeout=10)
        resp.raise_for_status()

        data = resp.json()
        if not isinstance(data, list) or len(data) < 2:
            return "Unexpected Reddit JSON structure."

        # The first element in data is the submission (thread) listing
        post_data = data[0]['data']['children'][0]['data']
        title = post_data.get('title', '[no title]')
        selftext = post_data.get('selftext', '[no selftext]')

        # The second element in data is the top-level comments listing
        comments_list = data[1]['data']['children']
        all_comments = []
        traverse_comments(comments_list, all_comments)

        # Construct output with post info plus enumerated comments
        output = f"Title: {title}\n\nSelftext:\n{selftext}\n\nComments:\n"
        for i, comment in enumerate(all_comments, start=1):
            output += f"{i}. {comment}\n"

        return output

    except Exception as e:
        return f"Error fetching Reddit content: {e}"