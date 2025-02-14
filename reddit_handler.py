import asyncpraw
import logging
import html
import os

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

def get_reddit_instance():
    """
    Creates an asyncpraw Reddit instance using credentials from the environment.
    If the needed environment variables are not set, the instance will be created with empty strings,
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
    Recursively traverse asyncpraw comment forests.
    Appends each comment’s data (if available) to comment_list.
    """
    for comment in comments:
        # Ensure we are only processing Comment objects (and skip MoreComments)
        if isinstance(comment, asyncpraw.models.Comment):
            # Some comments may be deleted or removed
            if comment.body:
                comment_data = {
                    'body': html.escape(comment.body),
                    'author': html.escape(comment.author.name) if comment.author else "[deleted]",
                    'score': comment.score or 0,
                    'created_utc': comment.created_utc or 0
                }
                comment_list.append(comment_data)
            # Recursively process replies
            if hasattr(comment, "replies"):
                _parse_comments(comment.replies, comment_list)

async def fetch_reddit_content(url, api_key_manager, httpx_client=None, retries=3):
    """
    Fetches a Reddit submission and its comments by using asyncpraw.
    The submission information and comments are then formatted into XML.

    Args:
        url (str): The URL of the Reddit post.
        api_key_manager: (Unused in this implementation, kept for compatibility.)
        httpx_client: (Unused, kept for compatibility.)
        retries (int): Number of retries (not used in this asyncpraw version).

    Returns:
        str: XML-formatted content containing the submission and its comments.
    """
    try:
        reddit = get_reddit_instance()
        # Create a Submission object directly from the URL.
        submission = await reddit.submission(url=url)
        await submission.load()  # Make sure all metadata is loaded

        # Extract submission details
        title = html.escape(submission.title or "")
        selftext = html.escape(submission.selftext or "")
        author = html.escape(submission.author.name) if submission.author else "[deleted]"
        score = submission.score or 0
        created_utc = submission.created_utc or 0
        num_comments = submission.num_comments or 0
        subreddit = html.escape(submission.subreddit.display_name) if submission.subreddit else ""

        # Replace any "more comments" and retrieve the full comments forest.
        await submission.comments.replace_more(limit=0)
        comment_list = []
        _parse_comments(submission.comments, comment_list)

        # Build XML-formatted response
        xml_parts = [
            "<reddit_response>",
            "  <post>",
            "    <metadata>",
            f"      <subreddit>{subreddit}</subreddit>",
            f"      <author>{author}</author>",
            f"      <created_utc>{created_utc}</created_utc>",
            f"      <score>{score}</score>",
            f"      <num_comments>{num_comments}</num_comments>",
            "    </metadata>",
            f"    <title>{title}</title>",
            f"    <selftext>{selftext}</selftext>",
            "  </post>",
            "  <comments>"
        ]

        # Append every comment in XML format
        for comment in comment_list:
            xml_parts.extend([
                "    <comment>",
                f"      <author>{comment['author']}</author>",
                f"      <score>{comment['score']}</score>",
                f"      <created_utc>{comment['created_utc']}</created_utc>",
                f"      <body>{comment['body']}</body>",
                "    </comment>"
            ])

        xml_parts.extend([
            "  </comments>",
            "</reddit_response>"
        ])

        return "\n".join(xml_parts)

    except Exception as e:
        logger.exception("Error fetching Reddit content: %s", e)
        return f"<reddit_response><error>Error fetching Reddit content: {e}</error></reddit_response>"