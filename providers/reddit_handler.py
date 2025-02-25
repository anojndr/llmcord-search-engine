"""
Reddit Handler Module

This module uses asyncpraw to fetch Reddit submissions and their comments.
The content is then formatted into plain text for further processing.
Comment parsing is offloaded to a thread to ensure concurrency.
"""

import asyncpraw
import logging
import html
import os
from typing import Optional, List, Dict, Any
import httpx
import asyncio

from config.api_key_manager import APIKeyManager

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

def get_reddit_instance() -> asyncpraw.Reddit:
    """
    Create an asyncpraw Reddit instance using environment credentials.

    Returns:
        Configured Reddit API client.

    Note:
        If environment variables are not set, empty strings are used,
        which may lead to authentication errors.
    """
    client_id: str = os.getenv("REDDIT_CLIENT_ID", "")
    client_secret: str = os.getenv("REDDIT_CLIENT_SECRET", "")
    user_agent: str = os.getenv(
        "REDDIT_USER_AGENT",
        "llmcord_reddit_extractor (by /u/yourusername)"
    )
    return asyncpraw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent
    )

def parse_comments(comments: Any) -> List[Dict[str, Any]]:
    """
    Recursively traverse asyncpraw comment forests and extract comment data synchronously.
    This function is run in a thread to avoid blocking the async event loop.

    Args:
        comments: Iterable of comment objects.

    Returns:
        List of parsed comment data.
    """
    comment_list: List[Dict[str, Any]] = []
    for comment in comments:
        if isinstance(comment, asyncpraw.models.Comment):
            if comment.body:
                comment_data: Dict[str, Any] = {
                    'body': html.escape(comment.body),
                    'author': html.escape(comment.author.name) if comment.author else "[deleted]",
                    'score': comment.score or 0,
                    'created_utc': comment.created_utc or 0
                }
                comment_list.append(comment_data)
            if hasattr(comment, "replies"):
                comment_list.extend(parse_comments(comment.replies))
    return comment_list

async def fetch_reddit_content(
    url: str,
    api_key_manager: APIKeyManager,
    httpx_client: Optional[httpx.AsyncClient] = None,
    retries: int = 3
) -> str:
    """
    Fetch a Reddit submission and its comments, then output a plain text block.
    Comment parsing is offloaded to a thread for concurrency.

    Args:
        url: URL of the Reddit post.
        api_key_manager: Unused parameter kept for interface compatibility.
        httpx_client: Unused, kept for compatibility.
        retries: Number of retries (unused in the current implementation).

    Returns:
        A plain text string containing the submission details and comments.
    """
    reddit: asyncpraw.Reddit = get_reddit_instance()
    try:
        submission: asyncpraw.models.Submission = await reddit.submission(url=url)
        await submission.load()

        title: str = submission.title or ""
        selftext: str = submission.selftext or ""
        author: str = submission.author.name if submission.author else "[deleted]"
        score: int = submission.score or 0
        created_utc: float = submission.created_utc or 0
        num_comments: int = submission.num_comments or 0
        subreddit: str = submission.subreddit.display_name if submission.subreddit else ""

        await submission.comments.replace_more(limit=0)
        # Offload comment parsing to a thread
        comment_list: List[Dict[str, Any]] = await asyncio.to_thread(parse_comments, submission.comments)

        lines: List[str] = []
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
    finally:
        await reddit.close()