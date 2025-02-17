"""
Reddit Handler Module

This module uses asyncpraw to fetch Reddit submissions and their comments.
The content is then formatted into plain text for further processing.
"""

import asyncpraw
import logging
import html
import os

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def get_reddit_instance():
    """
    Create an asyncpraw Reddit instance using environment credentials.
    
    Returns:
        asyncpraw.Reddit: Configured Reddit API client.
    
    Note:
        If environment variables are not set, empty strings are used,
        which may lead to authentication errors.
    """
    client_id = os.getenv("REDDIT_CLIENT_ID", "")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET", "")
    user_agent = os.getenv(
        "REDDIT_USER_AGENT",
        "llmcord_reddit_extractor (by /u/yourusername)"
    )
    return asyncpraw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent
    )


def _parse_comments(comments, comment_list):
    """
    Recursively traverse asyncpraw comment forests and extract comment data.
    
    Args:
        comments: Iterable of comment objects.
        comment_list: List to populate with parsed comment data.
    """
    for comment in comments:
        # Process only genuine Comment objects (skip MoreComments)
        if isinstance(comment, asyncpraw.models.Comment):
            if comment.body:
                comment_data = {
                    'body': html.escape(comment.body),
                    'author': html.escape(comment.author.name) if comment.author else "[deleted]",
                    'score': comment.score or 0,
                    'created_utc': comment.created_utc or 0
                }
                comment_list.append(comment_data)
            # Recursively process any replies
            if hasattr(comment, "replies"):
                _parse_comments(comment.replies, comment_list)


async def fetch_reddit_content(url, api_key_manager, httpx_client=None, retries=3):
    """
    Fetch a Reddit submission and its comments, then output a plain text block.
    
    Args:
        url (str): URL of the Reddit post.
        api_key_manager: Unused parameter kept for interface compatibility.
        httpx_client: Unused, kept for compatibility.
        retries (int): Number of retries (unused in the current implementation).
    
    Returns:
        str: A plain text string containing the submission details and comments.
    """
    try:
        reddit = get_reddit_instance()
        submission = await reddit.submission(url=url)
        await submission.load()  # Ensure full metadata is loaded

        title = submission.title or ""
        selftext = submission.selftext or ""
        author = submission.author.name if submission.author else "[deleted]"
        score = submission.score or 0
        created_utc = submission.created_utc or 0
        num_comments = submission.num_comments or 0
        subreddit = submission.subreddit.display_name if submission.subreddit else ""

        # Load all comments
        await submission.comments.replace_more(limit=0)
        comment_list = []
        _parse_comments(submission.comments, comment_list)

        lines = []
        lines.append(f"Post Title: {title}")
        lines.append(f"Author: {author}  |  Subreddit: {subreddit}")
        lines.append(f"Posted (UTC): {created_utc}  |  Score: {score}  |  Comments: {num_comments}")
        lines.append("")
        lines.append("Body:")
        lines.append(selftext)
        lines.append("")
        lines.append("Comments:")
        for comment in comment_list:
            lines.append("-----------------")
            lines.append(f"Author: {comment['author']} | Score: {comment['score']} | Posted (UTC): {comment['created_utc']}")
            lines.append(comment['body'])
            lines.append("")
        return "\n".join(lines)

    except Exception as e:
        logger.exception("Error fetching Reddit content: %s", e)
        return f"Error fetching Reddit content: {e}"