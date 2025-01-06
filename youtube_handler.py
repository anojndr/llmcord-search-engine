import re
import logging
import random
import os
from urllib.parse import urlparse, parse_qs

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from youtube_transcript_api import YouTubeTranscriptApi

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

PROXIES_FILE = _find_proxies_file()
proxies_list = []

if PROXIES_FILE:
    logging.info("Loading proxies from %s", PROXIES_FILE)
    with open(PROXIES_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(':')
            if len(parts) == 4:
                ip, port, user, password = parts
                proxy_url = f"http://{user}:{password}@{ip}:{port}"
                proxies_list.append(proxy_url)
else:
    logging.warning("No proxies file found in the current directory or /etc/secrets.")

def get_random_proxy():
    """
    Randomly select a proxy URL string from proxies_list.
    Returns None if proxies_list is empty.
    """
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


async def fetch_youtube_content(url, api_key_manager, httpx_client, max_comments=50):
    """
    Given a YouTube URL, fetch metadata (title, channel name), transcript (if available),
    and top comments (up to max_comments). Also logs the proxy used for transcripts.

    Common reasons for "Video not found" despite a valid URL:
      - The YouTube Data API has not been enabled for your project/API key
      - The API key is restricted or invalid
      - The video is region-locked or private
    """
    video_id = extract_video_id(url)
    if not video_id:
        return "Could not extract video ID from URL."

    api_key = await api_key_manager.get_next_api_key('youtube')
    if not api_key or api_key.strip() == "":
        return "No YouTube API key available. Make sure 'youtube_api_keys' is set in config.yaml."

    try:
        youtube = build('youtube', 'v3', developerKey=api_key)

        logging.info("Fetching YouTube video info for video_id=%s", video_id)
        video_response = youtube.videos().list(
            part='snippet,contentDetails,status,statistics',
            id=video_id
        ).execute()
        logging.info("video_response: %s", video_response)

        if not video_response.get('items'):
            return "Video not found (may be deleted, private, or region-restricted)."

        video_info = video_response['items'][0]['snippet']
        title = video_info.get('title', 'Unknown Title')
        channel_title = video_info.get('channelTitle', 'Unknown Channel')

        proxy_url = get_random_proxy()
        if proxy_url:
            logging.info("Using proxy for YouTube Transcript API: %s", proxy_url)
            transcripts = YouTubeTranscriptApi.list_transcripts(
                video_id,
                proxies={"https": proxy_url}
            )
        else:
            transcripts = YouTubeTranscriptApi.list_transcripts(video_id)

        try:
            transcript = transcripts.find_transcript(['en']).fetch()
            captions = ' '.join([t['text'] for t in transcript])
        except Exception:
            captions = "No captions available for this video."

        comments = []
        comment_response = youtube.commentThreads().list(
            part='snippet',
            videoId=video_id,
            maxResults=100,
            textFormat='plainText',
            order='relevance'
        ).execute()

        while comment_response and len(comments) < max_comments:
            for item in comment_response.get('items', []):
                top_comment = item['snippet']['topLevelComment']['snippet']['textDisplay']
                comments.append(top_comment)
                if len(comments) >= max_comments:
                    break

            next_page_token = comment_response.get('nextPageToken')
            if next_page_token and len(comments) < max_comments:
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

        content = (
            f"Video Title: {title}\n"
            f"Channel Name: {channel_title}\n\n"
            f"Captions:\n{captions}\n\n"
            f"Top Comments:\n"
        )
        for i, comment in enumerate(comments, start=1):
            content += f"{i}. {comment}\n"

        return content

    except HttpError as http_err:
        logging.exception("HttpError while trying to fetch YouTube data.")
        return f"Error fetching YouTube content (HTTP error): {http_err}"

    except Exception as e:
        logging.exception("General error while fetching YouTube content.")
        return f"Error fetching YouTube content: {e}"