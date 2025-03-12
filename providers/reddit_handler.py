"""
Reddit Handler Module

This module uses asyncpraw to fetch Reddit submissions and their comments.
The content is then formatted into plain text for further processing.
Comment parsing is offloaded to a thread to ensure concurrency.
"""

import asyncio
import html
import logging
import os
from typing import Dict, Any, List, Optional

import asyncpraw
import httpx

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
    client_id = os.getenv("REDDIT_CLIENT_ID", "")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET", "")
    user_agent = os.getenv(
        "REDDIT_USER_AGENT",
        "llmcord_reddit_extractor (by /u/yourusername)"
    )
    
    if not client_id or not client_secret:
        logger.warning("Reddit API credentials not properly configured")
    
    # Log with redacted client_id
    log_client_id = client_id[:4] + "..." if client_id and len(client_id) > 4 else "N/A"
    logger.debug(f"Creating Reddit instance with client_id={log_client_id} and user_agent={user_agent}")
    
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
    try:
        comment_count = 0
        for comment in comments:
            if isinstance(comment, asyncpraw.models.Comment):
                if comment.body:
                    comment_data = {
                        'body': html.escape(comment.body),
                        'author': html.escape(comment.author.name) if comment.author else "[deleted]",
                        'score': comment.score or 0,
                        'created_utc': comment.created_utc or 0
                    }
                    comment_list.append(comment_data)
                    comment_count += 1
                # Recursively parse replies
                if hasattr(comment, "replies"):
                    comment_list.extend(parse_comments(comment.replies))
        
        logger.debug(f"Parsed {comment_count} comments at this level")
    except Exception as e:
        logger.error(f"Error parsing Reddit comments: {e}", exc_info=True)
    
    return comment_list


async def fetch_reddit_content(
    url: str,
    api_key_manager: APIKeyManager,
    httpx_client: Optional[httpx.AsyncClient] = None
) -> str:
    """
    Fetch a Reddit submission and its comments, then output a plain text block.
    Comment parsing is offloaded to a thread for concurrency.

    Args:
        url: URL of the Reddit post.
        api_key_manager: Unused parameter kept for interface compatibility.
        httpx_client: Unused, kept for compatibility.

    Returns:
        A plain text string containing the submission details and comments.
    """
    logger.info(f"Fetching Reddit content from URL: {url}")
    reddit = get_reddit_instance()
    
    try:
        logger.debug("Creating submission object")
        submission = await reddit.submission(url=url)
        await submission.load()

        # Extract submission metadata
        title = submission.title or ""
        selftext = submission.selftext or ""
        author = submission.author.name if submission.author else "[deleted]"
        score = submission.score or 0
        created_utc = submission.created_utc or 0
        num_comments = submission.num_comments or 0
        subreddit = submission.subreddit.display_name if submission.subreddit else ""
        
        logger.info(
            f"Found Reddit post: '{title[:50]}{'...' if len(title) > 50 else ''}' "
            f"with {num_comments} comments in r/{subreddit}"
        )

        # Replace "More Comments" buttons with actual comments
        logger.debug(
            "Replacing 'more comments' expandable buttons with actual comments"
        )
        await submission.comments.replace_more(limit=0)
        
        # Offload comment parsing to a thread to avoid blocking
        logger.debug("Parsing comments in a separate thread")
        comment_list = await asyncio.to_thread(
            parse_comments, submission.comments
        )
        logger.info(f"Successfully parsed {len(comment_list)} comments")

        # Format the output
        return _format_reddit_content(
            title, author, subreddit, created_utc, score, 
            num_comments, selftext, comment_list
        )

    except asyncpraw.exceptions.RedditAPIException as api_err:
        logger.error(
            f"Reddit API error for URL '{url}': {api_err}", 
            exc_info=True
        )
        return f"Error fetching Reddit content: Reddit API error - {api_err}"
    except Exception as e:
        logger.error(
            f"Error fetching Reddit content from URL '{url}': {e}", 
            exc_info=True
        )
        return f"Error fetching Reddit content: {e}"
    finally:
        logger.debug("Closing Reddit client session")
        await reddit.close()


def _format_reddit_content(
    title: str,
    author: str,
    subreddit: str,
    created_utc: float,
    score: int,
    num_comments: int,
    selftext: str,
    comment_list: List[Dict[str, Any]]
) -> str:
    """
    Format Reddit content as plain text.
    
    Args:
        title: Post title
        author: Post author
        subreddit: Subreddit name
        created_utc: Post creation time (UTC)
        score: Post score
        num_comments: Number of comments
        selftext: Post body text
        comment_list: List of comment data dictionaries
        
    Returns:
        Formatted text content
    """
    lines = []
    lines.append(f"Post Title: {title}")
    lines.append(f"Author: {author}  |  Subreddit: {subreddit}")
    lines.append(
        f"Posted (UTC): {created_utc}  |  Score: {score}  |  "
        f"Comments: {num_comments}"
    )
    lines.append("")
    lines.append("Body:")
    lines.append(selftext)
    lines.append("")
    lines.append("Comments:")
    
    for comment in comment_list:
        lines.append("-----------------")
        lines.append(
            f"Author: {comment['author']} | Score: {comment['score']} | "
            f"Posted (UTC): {comment['created_utc']}"
        )
        lines.append(comment['body'])
        lines.append("")
    
    return "\n".join(lines)