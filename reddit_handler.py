import httpx

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

async def fetch_reddit_content(url, api_key_manager, httpx_client=None):
    """
    Fetches Reddit submission + comments by appending .json to the final redirect URL
    and parsing the returned JSON structure (which typically consists of two listings).
    """
    if httpx_client is None:
        httpx_client = httpx.AsyncClient()

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

    except Exception as e:
        return f"Error fetching Reddit content: {e}"