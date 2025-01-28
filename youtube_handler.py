import re
import logging
import random
import os
import html
from urllib.parse import urlparse, parse_qs
from datetime import datetime

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from youtube_transcript_api import YouTubeTranscriptApi

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

def _find_proxies_file(filename="proxies.txt"):
    """
    Attempts to find a file named 'proxies.txt' first in the current directory,
    then in /etc/secrets. Returns the file path if it exists, else None.
    """
    if os.path.exists(filename):
        return os.path.abspath(filename)
    alt_filename = os.path.join("/etc/secrets", filename)
    if os.path.exists(alt_filename):
        return alt_filename
    return None
    
def load_proxies(filename="proxies.txt"):
    """
    Loads proxies from the specified file. Each line can be a simple URL or include user:pass.
    Returns a list of proxy URLs, or an empty list if the file is not found or empty.
    """
    filepath = _find_proxies_file(filename)
    proxies = []
    if filepath:
        logger.info("Loading proxies from %s", filepath)
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    if '@' not in line and ':' in line:
                        parts = line.split(':')
                        if len(parts) == 2:
                            ip, port = parts
                            proxy_url = f"http://{ip}:{port}"
                        elif len(parts) == 4:
                            ip, port, user, password = parts
                            proxy_url = f"http://{user}:{password}@{ip}:{port}"
                        else:
                            continue
                        proxies.append(proxy_url)
                    else:
                        proxies.append(line)
    else:
        logger.warning("No proxies file found.")
    return proxies

def get_random_proxy():
    """
    Randomly select a proxy URL string from proxies_list.
    Returns None if proxies_list is empty.
    """
    proxies_list = load_proxies()
    if not proxies_list:
        return None
    return random.choice(proxies_list)

def extract_video_id(url):
    """
    Extract a YouTube video ID from the provided URL.
    1) First, try to parse the 'v' parameter from the query string (e.g. ?v=xxxx).
    2) If that fails, fall back to known patterns (youtu.be, /embed/, /shorts/, etc.).
    Returns None if no ID can be found.
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
    """Convert YouTube duration string to human-readable format."""
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
    Given a YouTube URL, fetch metadata, transcript, and top comments.
    Returns content in XML format with detailed metadata and error handling.
    """
    video_id = extract_video_id(url)
    if not video_id:
        return "<youtube_response><error>Could not extract video ID from URL.</error></youtube_response>"

    api_key = await api_key_manager.get_next_api_key('youtube')
    if not api_key or api_key.strip() == "":
        return "<youtube_response><error>No YouTube API key available. Make sure 'youtube_api_keys' is set in config.yaml.</error></youtube_response>"

    try:
        youtube = build('youtube', 'v3', developerKey=api_key)

        logger.info("Fetching YouTube video info for video_id=%s", video_id)
        video_response = youtube.videos().list(
            part='snippet,contentDetails,statistics,status',
            id=video_id
        ).execute()

        if not video_response.get('items'):
            return "<youtube_response><error>Video not found (may be deleted, private, or region-restricted).</error></youtube_response>"

        video_data = video_response['items'][0]
        snippet = video_data['snippet']
        content_details = video_data['contentDetails']
        statistics = video_data['statistics']
        
        metadata = {
            'title': html.escape(snippet.get('title', 'Unknown Title')),
            'channel': html.escape(snippet.get('channelTitle', 'Unknown Channel')),
            'published_at': snippet.get('publishedAt', ''),
            'duration': format_duration(content_details.get('duration', '')),
            'view_count': statistics.get('viewCount', '0'),
            'like_count': statistics.get('likeCount', '0'),
            'comment_count': statistics.get('commentCount', '0'),
            'description': html.escape(snippet.get('description', '')),
            'tags': ', '.join(html.escape(tag) for tag in snippet.get('tags', []))
        }

        proxy_url = get_random_proxy()
        try:
            if proxy_url:
                logger.info("Using proxy for YouTube Transcript API: %s", proxy_url)
                transcripts = YouTubeTranscriptApi.list_transcripts(
                    video_id,
                    proxies={"https": proxy_url}
                )
            else:
                transcripts = YouTubeTranscriptApi.list_transcripts(video_id)

            transcript = transcripts.find_transcript(['en']).fetch()
            captions = ' '.join(html.escape(t['text']) for t in transcript)
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
                        'text': html.escape(comment_data.get('textDisplay', '')),
                        'author': html.escape(comment_data.get('authorDisplayName', '')),
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

        content = [
            '<youtube_response>',
            '<metadata>'
        ]
        
        for key, value in metadata.items():
            content.append(f'<{key}>{value}</{key}>')
        
        content.extend([
            '</metadata>',
            f'<transcript>{captions}</transcript>',
            '<comments>'
        ])

        for comment in comments:
            content.extend([
                '<comment>',
                f'<author>{comment["author"]}</author>',
                f'<published_at>{comment["published_at"]}</published_at>',
                f'<like_count>{comment["like_count"]}</like_count>',
                f'<text>{comment["text"]}</text>',
                '</comment>'
            ])

        content.extend(['</comments>', '</youtube_response>'])

        return '\n'.join(content)

    except HttpError as http_err:
        logger.exception("HttpError while trying to fetch YouTube data.")
        return f'<youtube_response><error>Error fetching YouTube content (HTTP error): {str(http_err)}</error></youtube_response>'

    except Exception as e:
        logger.exception("General error while fetching YouTube content.")
        return f'<youtube_response><error>Error fetching YouTube content: {str(e)}</error></youtube_response>'