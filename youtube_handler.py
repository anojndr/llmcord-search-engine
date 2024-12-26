import re
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi


def extract_video_id(url):
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


async def fetch_youtube_content(url, api_key, max_comments=50):
    video_id = extract_video_id(url)
    if not video_id:
        return "Could not extract video ID from URL."

    try:
        youtube = build('youtube', 'v3', developerKey=api_key)

        video_response = youtube.videos().list(
            part='snippet',
            id=video_id
        ).execute()

        if not video_response['items']:
            return "Video not found."

        video_info = video_response['items'][0]['snippet']
        title = video_info['title']
        channel_title = video_info['channelTitle']

        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            transcript = transcript_list.find_transcript(['en']).fetch()
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
            for item in comment_response['items']:
                comment = item['snippet']['topLevelComment']['snippet']['textDisplay']
                comments.append(comment)
                if len(comments) >= max_comments:
                    break
            if 'nextPageToken' in comment_response and len(comments) < max_comments:
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

        content = f"Video Title: {title}\nChannel Name: {channel_title}\n\nCaptions:\n{captions}\n\nTop Comments:\n"
        for idx, comment in enumerate(comments, start=1):
            content += f"{idx}. {comment}\n"

        return content

    except Exception as e:
        return f"Error fetching YouTube content: {e}"