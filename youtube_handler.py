"""
YouTube Handler Module

This module extracts YouTube video IDs from URLs, fetches video metadata, transcripts,
and top comments via the YouTube API and YouTube Transcript API, and outputs a plain text summary.
"""

import re
import logging
import os
import html
from urllib.parse import urlparse, parse_qs
from datetime import datetime

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from youtube_transcript_api import YouTubeTranscriptApi

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def extract_video_id(url):
    """
    Extract a YouTube video ID from a given URL.
    
    Args:
        url (str): The YouTube URL.
    
    Returns:
        str or None: The extracted video ID, or None if it cannot be found.
    """
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    if "v" in query_params and query_params["v"]:
        extracted = query_params["v"][0]
        if extracted:
            return extracted

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
            return match.group(1)
    return None


def format_duration(duration_str):
    """
    Convert a YouTube duration string (ISO 8601) to a human-readable format.
    
    Args:
        duration_str (str): Duration string (e.g., "PT1H2M30S").
    
    Returns:
        str: Human-readable duration.
    """
    import re
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str)
    if not match:
        return "Unknown duration"
    
    hours, minutes, seconds = match.groups()
    parts = []
    
    if hours:
        parts.append(f"{int(hours)} hour{'s' if hours != '1' else ''}")
    if minutes:
        parts.append(f"{int(minutes)} minute{'s' if minutes != '1' else ''}")
    if seconds:
        parts.append(f"{int(seconds)} second{'s' if seconds != '1' else ''}")
        
    return ", ".join(parts)


async def fetch_youtube_content(url, api_key_manager, httpx_client, max_comments=50):
    """
    Fetch YouTube video information including metadata, transcript, and top comments.
    Returns a plain text summary containing all gathered details.
    
    Args:
        url (str): YouTube video URL.
        api_key_manager: API key manager instance.
        httpx_client: HTTP client.
        max_comments (int): Maximum number of comments to retrieve.
    
    Returns:
        str: Plain text content containing video metadata, transcript, and comments.
    """
    video_id = extract_video_id(url)
    if not video_id:
        return "Error: Could not extract video ID from URL."

    api_key = await api_key_manager.get_next_api_key('youtube')
    if not api_key or api_key.strip() == "":
        return "Error: No YouTube API key available. Make sure 'youtube_api_keys' is set in your configuration."

    try:
        youtube = build('youtube', 'v3', developerKey=api_key)

        logger.info("Fetching YouTube video info for video_id=%s", video_id)
        video_response = youtube.videos().list(
            part='snippet,contentDetails,statistics,status',
            id=video_id
        ).execute()

        if not video_response.get('items'):
            return "Error: Video not found (may be deleted, private, or region-restricted)."

        video_data = video_response['items'][0]
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

        # Fetch transcript without using any proxies
        try:
            transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
            transcript = transcripts.find_transcript(['en']).fetch()
            captions = ' '.join(html.unescape(t['text']) for t in transcript)
        except Exception as e:
            logger.warning(f"Error fetching transcript: {e}")
            captions = "No captions available for this video."

        comments = []
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

        lines = []
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