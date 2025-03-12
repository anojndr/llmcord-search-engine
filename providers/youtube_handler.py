"""
YouTube Handler Module

This module extracts YouTube video IDs from URLs, fetches video metadata, transcripts,
and top comments via the YouTube API and YouTube Transcript API, and outputs a plain text summary.
All network operations are performed concurrently where possible.
"""

import asyncio
import html
import logging
import re
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse, parse_qs

import httpx
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from youtube_transcript_api import YouTubeTranscriptApi

from config.api_key_manager import APIKeyManager

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def extract_video_id(url: str) -> Optional[str]:
    """
    Extract a YouTube video ID from a given URL.

    Args:
        url: The YouTube URL.

    Returns:
        The extracted video ID, or None if it cannot be found.
    """
    if not url:
        logger.warning("Empty URL provided to extract_video_id")
        return None
        
    logger.debug(f"Extracting video ID from URL: {url}")
    
    # First try the query parameter approach (most common)
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    if "v" in query_params and query_params["v"]:
        extracted = query_params["v"][0]
        if extracted:
            logger.debug(f"Extracted video ID from query parameter: {extracted}")
            return extracted

    # Try various URL patterns
    patterns = [
        r'youtu\.be/([^/?&]+)',
        r'youtube\.com/watch\?v=([^&]+)',
        r'youtube\.com/embed/([^/?&]+)',
        r'youtube\.com/v/([^/?&]+)',
        r'youtube\.com/shorts/([^/?&]+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            video_id = match.group(1)
            logger.debug(f"Extracted video ID using pattern {pattern}: {video_id}")
            return video_id
    
    logger.warning(f"Could not extract video ID from URL: {url}")
    return None


def format_duration(duration_str: str) -> str:
    """
    Convert a YouTube duration string (ISO 8601) to a human-readable format.

    Args:
        duration_str: Duration string (e.g., "PT1H2M30S").

    Returns:
        Human-readable duration.
    """
    if not duration_str:
        return "Unknown duration"
        
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str)
    if not match:
        logger.warning(f"Could not parse duration string: {duration_str}")
        return "Unknown duration"

    hours, minutes, seconds = match.groups()
    parts = []

    if hours:
        parts.append(f"{int(hours)} hour{'s' if hours != '1' else ''}")
    if minutes:
        parts.append(f"{int(minutes)} minute{'s' if minutes != '1' else ''}")
    if seconds:
        parts.append(f"{int(seconds)} second{'s' if seconds != '1' else ''}")

    formatted = ", ".join(parts)
    logger.debug(f"Formatted duration '{duration_str}' to '{formatted}'")
    return formatted


def get_comments(
    youtube, 
    video_id: str, 
    max_comments: int = 50
) -> List[Dict[str, Any]]:
    """
    Fetch top comments for a YouTube video synchronously.

    Args:
        youtube: YouTube API client.
        video_id: Video ID.
        max_comments: Maximum number of comments to fetch.

    Returns:
        List of comment dictionaries.
    """
    comments = []
    try:
        logger.info(f"Fetching comments for video ID: {video_id}")
        comment_response = youtube.commentThreads().list(
            part='snippet',
            videoId=video_id,
            maxResults=100,
            textFormat='plainText',
            order='relevance'
        ).execute()

        while comment_response and len(comments) < max_comments:
            batch_items = comment_response.get('items', [])
            logger.debug(f"Retrieved {len(batch_items)} comments in this batch")
            
            for item in batch_items:
                comment_data = item['snippet']['topLevelComment']['snippet']
                comment = {
                    'text': html.unescape(comment_data.get('textDisplay', '')),
                    'author': html.unescape(comment_data.get('authorDisplayName', '')),
                    'like_count': comment_data.get('likeCount', 0),
                    'published_at': comment_data.get('publishedAt', '')
                }
                comments.append(comment)
                if len(comments) >= max_comments:
                    break

            # Check for next page
            if len(comments) < max_comments and 'nextPageToken' in comment_response:
                next_page_token = comment_response['nextPageToken']
                logger.debug(f"Fetching next page of comments with token: {next_page_token}")
                comment_response = youtube.commentThreads().list(
                    part='snippet',
                    videoId=video_id,
                    pageToken=next_page_token,
                    maxResults=100,
                    textFormat='plainText',
                    order='relevance'
                ).execute()
            else:
                break
        
        logger.info(f"Successfully fetched {len(comments)} comments for video ID: {video_id}")
        
    except HttpError as e:
        error_reason = "Comments disabled" if e.status_code == 403 else str(e)
        logger.warning(f"Error fetching comments for video {video_id}: {error_reason}")
        comments.append({
            'text': f"Error fetching comments: {error_reason}",
            'author': 'System',
            'like_count': 0,
            'published_at': ''
        })
    except Exception as e:
        logger.error(f"Unexpected error fetching comments for video {video_id}: {e}", exc_info=True)
        comments.append({
            'text': f"Error fetching comments: {str(e)}",
            'author': 'System',
            'like_count': 0,
            'published_at': ''
        })
    
    return comments


async def fetch_youtube_content(
    url: str,
    api_key_manager: APIKeyManager,
    httpx_client: httpx.AsyncClient,
    max_comments: int = 50
) -> str:
    """
    Fetch YouTube video information including metadata, transcript, and top comments concurrently.
    Returns a plain text summary containing all gathered details.

    Args:
        url: YouTube video URL.
        api_key_manager: API key manager instance.
        httpx_client: HTTP client (unused but kept for interface compatibility).
        max_comments: Maximum number of comments to retrieve.

    Returns:
        Plain text content containing video metadata, transcript, and comments.
    """
    # Extract video ID
    video_id = extract_video_id(url)
    if not video_id:
        error_msg = f"Could not extract video ID from URL: {url}"
        logger.error(error_msg)
        return f"Error: {error_msg}"

    # Get API key
    api_key = await api_key_manager.get_next_api_key('youtube')
    if not api_key or api_key.strip() == "":
        error_msg = (
            "No YouTube API key available. Make sure 'youtube_api_keys' is set "
            "in your configuration."
        )
        logger.error(error_msg)
        return f"Error: {error_msg}"

    try:
        logger.info(f"Building YouTube API client for video ID: {video_id}")
        youtube = build('youtube', 'v3', developerKey=api_key)

        # Fetch metadata first (required to check if video exists)
        logger.info(f"Fetching video metadata for video ID: {video_id}")
        metadata_response = await asyncio.to_thread(
            youtube.videos().list(
                part='snippet,contentDetails,statistics,status',
                id=video_id
            ).execute
        )

        if not metadata_response.get('items'):
            error_msg = (
                "Video not found (may be deleted, private, or region-restricted)"
            )
            logger.warning(f"{error_msg} for video ID: {video_id}")
            return f"Error: {error_msg}"

        # Extract metadata
        video_data = metadata_response['items'][0]
        snippet = video_data['snippet']
        content_details = video_data['contentDetails']
        statistics = video_data['statistics']

        metadata = {
            'title': html.unescape(snippet.get('title', 'Unknown Title')),
            'channel': html.unescape(snippet.get('channelTitle', 'Unknown Channel')),
            'published_at': snippet.get('publishedAt', ''),
            'duration': format_duration(content_details.get('duration', '')),
            'view_count': statistics.get('viewCount', '0'),
            'like_count': statistics.get('likeCount', '0'),
            'comment_count': statistics.get('commentCount', '0'),
            'description': html.unescape(snippet.get('description', '')),
            'tags': ', '.join([html.unescape(tag) for tag in snippet.get('tags', [])])
        }
        
        logger.info(
            f"Successfully fetched metadata for '{metadata['title']}' by "
            f"{metadata['channel']}"
        )

        # Fetch transcript and comments concurrently
        logger.info(f"Starting concurrent tasks: transcript and comments for video ID: {video_id}")
        transcript_task = _fetch_transcript(video_id)
        comments_task = asyncio.to_thread(get_comments, youtube, video_id, max_comments)

        captions, comments = await asyncio.gather(transcript_task, comments_task)

        # Format the output
        return _format_youtube_content(metadata, captions, comments)

    except HttpError as http_err:
        error_msg = f"HttpError while trying to fetch YouTube data: {http_err}"
        logger.error(error_msg, exc_info=True)
        return f"Error fetching YouTube content: {error_msg}"
    except Exception as e:
        error_msg = f"General error while fetching YouTube content: {e}"
        logger.error(error_msg, exc_info=True)
        return f"Error fetching YouTube content: {error_msg}"


async def _fetch_transcript(video_id: str) -> str:
    """
    Fetch transcript for a YouTube video.
    
    Args:
        video_id: YouTube video ID
        
    Returns:
        Transcript text or error message
    """
    try:
        logger.info(f"Fetching transcript for video ID: {video_id}")
        
        # Define synchronous function to run in thread
        def get_transcript():
            try:
                transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
                transcript_obj = transcripts.find_transcript(['en'])
                return transcript_obj.fetch()
            except Exception as e:
                logger.warning(f"Error in get_transcript: {e}")
                return []

        # Run transcript fetch in a thread
        transcript = await asyncio.to_thread(get_transcript)
        
        if transcript:
            captions = ' '.join(html.unescape(t['text']) for t in transcript)
            logger.info(f"Successfully fetched transcript ({len(captions)} characters)")
            return captions
        else:
            logger.warning(f"No transcript data returned for video ID: {video_id}")
            return "No captions available for this video."
    except Exception as e:
        logger.error(f"Error fetching transcript for video ID {video_id}: {e}", exc_info=True)
        return "No captions available for this video."


def _format_youtube_content(
    metadata: Dict[str, Any],
    captions: str,
    comments: List[Dict[str, Any]]
) -> str:
    """
    Format YouTube content as plain text.
    
    Args:
        metadata: Video metadata
        captions: Video transcript
        comments: List of comments
        
    Returns:
        Formatted text content
    """
    lines = []
    lines.append(f"Title: {metadata.get('title')}")
    lines.append(f"Channel: {metadata.get('channel')}")
    lines.append(f"Published: {metadata.get('published_at')}")
    lines.append(f"Duration: {metadata.get('duration')}")
    lines.append(
        f"Views: {metadata.get('view_count')}  |  Likes: {metadata.get('like_count')}"
    )
    lines.append("")
    lines.append("Description:")
    lines.append(metadata.get('description'))
    lines.append("")
    lines.append("Transcript:")
    lines.append(captions)
    lines.append("")
    lines.append("Comments:")
    
    for comment in comments:
        lines.append("----------------")
        lines.append(
            f"Author: {comment['author']} | Published: {comment['published_at']} | "
            f"Likes: {comment['like_count']}"
        )
        lines.append(comment['text'])
        lines.append("")
    
    return "\n".join(lines)