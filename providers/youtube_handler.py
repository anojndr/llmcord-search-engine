"""
YouTube Handler Module

This module extracts YouTube video IDs from URLs, fetches video metadata, transcripts,
and top comments via the YouTube API and YouTube Transcript API, and outputs a plain text summary.
All network operations are performed concurrently where possible.
"""

import re
import logging
import html
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse, parse_qs
import httpx
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from youtube_transcript_api import YouTubeTranscriptApi
import asyncio

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
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    if "v" in query_params and query_params["v"]:
        extracted: str = query_params["v"][0]
        if extracted:
            return extracted

    patterns: List[str] = [
        r'youtu\.be/([^/?&]+)',
        r'youtube\.com/watch\?v=([^&]+)',
        r'youtube\.com/embed/([^/?&]+)',
        r'youtube\.com/v/([^/?&]+)',
        r'youtube\.com/shorts/([^/?&]+)'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def format_duration(duration_str: str) -> str:
    """
    Convert a YouTube duration string (ISO 8601) to a human-readable format.

    Args:
        duration_str: Duration string (e.g., "PT1H2M30S").

    Returns:
        Human-readable duration.
    """
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str)
    if not match:
        return "Unknown duration"

    hours, minutes, seconds = match.groups()
    parts: List[str] = []

    if hours:
        parts.append(f"{int(hours)} hour{'s' if hours != '1' else ''}")
    if minutes:
        parts.append(f"{int(minutes)} minute{'s' if minutes != '1' else ''}")
    if seconds:
        parts.append(f"{int(seconds)} second{'s' if seconds != '1' else ''}")

    return ", ".join(parts)

def get_comments(youtube, video_id: str, max_comments: int = 50) -> List[Dict[str, Any]]:
    """
    Fetch top comments for a YouTube video synchronously.

    Args:
        youtube: YouTube API client.
        video_id: Video ID.
        max_comments: Maximum number of comments to fetch.

    Returns:
        List of comment dictionaries.
    """
    comments: List[Dict[str, Any]] = []
    try:
        comment_response = youtube.commentThreads().list(
            part='snippet',
            videoId=video_id,
            maxResults=100,
            textFormat='plainText',
            order='relevance'
        ).execute()

        while comment_response and len(comments) < max_comments:
            for item in comment_response.get('items', []):
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

            if len(comments) < max_comments and 'nextPageToken' in comment_response:
                comment_response = youtube.commentThreads().list(
                    part='snippet',
                    videoId=video_id,
                    pageToken=comment_response['nextPageToken'],
                    maxResults=100,
                    textFormat='plainText',
                    order='relevance'
                ).execute()
            else:
                break
    except Exception as e:
        logger.warning(f"Error fetching comments: {e}")
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
    video_id: Optional[str] = extract_video_id(url)
    if not video_id:
        return "Error: Could not extract video ID from URL."

    api_key: Optional[str] = await api_key_manager.get_next_api_key('youtube')
    if not api_key or api_key.strip() == "":
        return "Error: No YouTube API key available. Make sure 'youtube_api_keys' is set in your configuration."

    try:
        youtube = build('youtube', 'v3', developerKey=api_key)

        # Fetch metadata first (required to check if video exists)
        metadata_response = await asyncio.to_thread(
            youtube.videos().list(
                part='snippet,contentDetails,statistics,status',
                id=video_id
            ).execute
        )

        if not metadata_response.get('items'):
            return "Error: Video not found (may be deleted, private, or region-restricted)."

        video_data: Dict[str, Any] = metadata_response['items'][0]
        snippet: Dict[str, Any] = video_data['snippet']
        content_details: Dict[str, Any] = video_data['contentDetails']
        statistics: Dict[str, Any] = video_data['statistics']

        metadata: Dict[str, Any] = {
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

        # Define async function for fetching transcript
        async def fetch_transcript() -> str:
            try:
                def get_transcript():
                    transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
                    transcript_obj = transcripts.find_transcript(['en'])
                    return transcript_obj.fetch()

                transcript = await asyncio.to_thread(get_transcript)
                captions: str = ' '.join(html.unescape(t['text']) for t in transcript)
                return captions
            except Exception as e:
                logger.warning(f"Error fetching transcript: {e}")
                return "No captions available for this video."

        # Fetch transcript and comments concurrently
        transcript_task = fetch_transcript()
        comments_task = asyncio.to_thread(get_comments, youtube, video_id, max_comments)

        captions, comments = await asyncio.gather(transcript_task, comments_task)

        # Format the output
        lines: List[str] = []
        lines.append(f"Title: {metadata.get('title')}")
        lines.append(f"Channel: {metadata.get('channel')}")
        lines.append(f"Published: {metadata.get('published_at')}")
        lines.append(f"Duration: {metadata.get('duration')}")
        lines.append(f"Views: {metadata.get('view_count')}  |  Likes: {metadata.get('like_count')}")
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
            lines.append(f"Author: {comment['author']} | Published: {comment['published_at']} | Likes: {comment['like_count']}")
            lines.append(comment['text'])
            lines.append("")
        return "\n".join(lines)

    except HttpError as http_err:
        logger.exception("HttpError while trying to fetch YouTube data.")
        return f"Error fetching YouTube content (HTTP error): {str(http_err)}"
    except Exception as e:
        logger.exception("General error while fetching YouTube content.")
        return f"Error fetching YouTube content: {str(e)}"