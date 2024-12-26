import re
import asyncpraw


def extract_submission_id(url):
    patterns = [
        r'reddit\.com/r/[^/]+/comments/([^/]+)/',
        r'redd\.it/([^/?#&]+)'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


async def fetch_reddit_content(url, client_id, client_secret, user_agent):
    reddit = asyncpraw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent
    )

    submission_id = extract_submission_id(url)
    if not submission_id:
        return "Could not extract submission ID from URL."

    try:
        submission = await reddit.submission(id=submission_id)
        await submission.load()
        await submission.comments.replace_more(limit=None)
        comments = []
        for comment in submission.comments.list():
            comments.append(comment.body)

        content = f"Title: {submission.title}\n\nSelftext:\n{submission.selftext}\n\nComments:\n"
        for idx, comment in enumerate(comments, start=1):
            content += f"{idx}. {comment}\n"
        return content

    except Exception as e:
        return f"Error fetching Reddit content: {e}"