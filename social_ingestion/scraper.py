import asyncio
import logging
import re
from typing import Any

import httpx

from shared.retry import retry_async
from social_ingestion.models import Platform, ScrapeResult

logger = logging.getLogger(__name__)

_INSTAGRAM_API_HOST = "instagram-downloader-v2-scraper-reels-igtv-posts-stories.p.rapidapi.com"
_YOUTUBE_API_HOST = "youtube-video-fast-downloader-24-7.p.rapidapi.com"
_YOUTUBE_POLL_ATTEMPTS = 15
_YOUTUBE_POLL_INTERVAL_S = 3.0


def _rapidapi_headers(api_key: str, host: str) -> dict[str, str]:
    return {"x-rapidapi-key": api_key, "x-rapidapi-host": host}


def _detect_instagram_content_type(url: str) -> str:
    if "/stories/" in url:
        return "story"
    if re.search(r"/(reel|reels)/", url):
        return "reel"
    if "/p/" in url:
        return "post"
    return "generic"



def _clean_instagram_caption(raw: str) -> str:
    text = re.sub(r"[\r\n]+", " ", raw)
    text = re.sub(r"[^\w\s.,;:!?\"'()\-]", "", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _extract_youtube_video_id(url: str) -> str:
    patterns = [
        r"(?:youtu\.be/|youtube\.com/(?:embed/|v/|watch\?v=|watch\?.+&v=|shorts/|live/))([^&?#\s]+)",
        r"[?&]v=([^&?#\s]+)",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    raise ValueError(f"Cannot extract YouTube video ID from: {url}")


async def scrape(url: str, api_key: str) -> ScrapeResult:
    """Scrape media URL and caption from an Instagram or YouTube URL."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        if "instagram.com" in url:
            return await _scrape_instagram(url, api_key, client)
        elif "youtube.com" in url or "youtu.be" in url:
            return await _scrape_youtube(url, api_key, client)
        else:
            raise ValueError("Piattaforma social non supportata (solo instagram e youtube).")


async def _scrape_instagram(url: str, api_key: str, client: httpx.AsyncClient) -> ScrapeResult:
    content_type = _detect_instagram_content_type(url)
    logger.info("Instagram content type: %s", content_type)

    api_url = f"https://{_INSTAGRAM_API_HOST}/get-post"
    params = {"url": url}
    
    async def make_request():
        resp = await client.get(
            api_url,
            headers=_rapidapi_headers(api_key, _INSTAGRAM_API_HOST),
            params=params
        )
        resp.raise_for_status()
        return resp.json()

    data = await retry_async(make_request, max_retries=3, initial_delay=1.0)
    
    if not isinstance(data, dict) or "media" not in data or not isinstance(data["media"], list) or not data["media"]:
        raise ValueError(f"Invalid or empty Instagram API response format: {data}")
    
    first_item = data["media"][0]
    media_url = first_item.get("url")
    if not media_url:
        raise ValueError("No media URL found in Instagram response")
        
    thumbnail_url = first_item.get("thumb")
    is_video = first_item.get("is_video", False)
    
    raw_caption = first_item.get("caption", "")
    caption = _clean_instagram_caption(raw_caption) if raw_caption else ""
    
    mime = "video/mp4" if is_video else "image/jpeg"
    return ScrapeResult(
        media_url=media_url,
        caption=caption,
        platform=Platform.INSTAGRAM,
        mime_type=mime,
        thumbnail_url=thumbnail_url
    )


async def _scrape_youtube(url: str, api_key: str, client: httpx.AsyncClient) -> ScrapeResult:
    video_id = _extract_youtube_video_id(url)
    logger.info("YouTube video_id: %s", video_id)
    headers = _rapidapi_headers(api_key, _YOUTUBE_API_HOST)

    async def get_qualities():
        resp = await client.get(
            f"https://{_YOUTUBE_API_HOST}/get_available_quality/{video_id}", headers=headers
        )
        resp.raise_for_status()
        return resp.json()

    qualities = await retry_async(get_qualities, max_retries=3, initial_delay=1.0)
    video_quals = [
        q for q in qualities
        if q.get("type") == "video" and q.get("quality") not in (None, "Unknown")
    ]
    if not video_quals:
        raise ValueError("No video quality available for this YouTube content.")
    video_quals.sort(key=lambda q: int(re.sub(r"\D", "", q.get("quality", "9999")) or "9999"))
    lowest = video_quals[0]
    logger.info("Selected quality: %s", lowest.get("quality"))

    endpoint = "download_short" if "/shorts/" in url else "download_video"

    async def get_download_url():
        resp = await client.get(
            f"https://{_YOUTUBE_API_HOST}/{endpoint}/{video_id}?quality={lowest['id']}", headers=headers
        )
        resp.raise_for_status()
        return resp.json()

    dl_data = await retry_async(get_download_url, max_retries=3, initial_delay=1.0)
    media_url = dl_data.get("file") or dl_data.get("reserved_file")
    if not media_url:
        raise ValueError("No download URL returned from YouTube API.")

    for attempt in range(1, _YOUTUBE_POLL_ATTEMPTS + 1):
        check = await client.head(media_url)
        if check.status_code == 200:
            logger.info("YouTube file ready after %d attempts", attempt)
            break
        await asyncio.sleep(_YOUTUBE_POLL_INTERVAL_S)
    else:
        raise TimeoutError("Timeout waiting for YouTube file to become ready.")

    caption = ""
    async def get_video_info():
        resp = await client.get(
            f"https://{_YOUTUBE_API_HOST}/get-video-info/{video_id}", headers=headers
        )
        resp.raise_for_status()
        return resp.json()

    try:
        info_data = await retry_async(get_video_info, max_retries=2, initial_delay=0.5)
        caption = info_data.get("title", "")
    except Exception:
        logger.warning("Could not fetch YouTube video title")

    thumbnail_url = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
    return ScrapeResult(
        media_url=media_url,
        caption=caption,
        platform=Platform.YOUTUBE,
        mime_type="video/mp4",
        thumbnail_url=thumbnail_url
    )
