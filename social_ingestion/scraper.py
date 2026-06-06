import asyncio
import logging
import re
from typing import Any

import httpx

from shared.retry import retry_async
from social_ingestion.models import Platform, ScrapeResult

logger = logging.getLogger(__name__)

_INSTAGRAM_API_HOST = "instagram-public-bulk-scraper.p.rapidapi.com"
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


def _extract_instagram_media_url(data: dict[str, Any], content_type: str) -> str:
    if data.get("status") == "error":
        raise ValueError(f"Instagram API error: {data.get('message', 'Unknown error')}")

    d = data.get("data", data)
    if not isinstance(d, dict):
        raise ValueError(f"Invalid Instagram API response format: data is {type(d).__name__}")

    if content_type in ("story", "reel"):
        url = (
            d.get("video_url")
            or (d.get("media_versions") or [{}])[0].get("url")
            or data.get("video_url")
        )
    else:
        url = (
            d.get("video_url")
            or d.get("display_url")
            or data.get("video_url")
            or data.get("display_url")
        )
    if not url:
        raise ValueError(f"No media URL found in Instagram response for type={content_type}")
    return url


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

    encoded = httpx.URL(url)
    api_url = f"https://{_INSTAGRAM_API_HOST}/v1/media_info?code_or_id_or_url={encoded}"
    
    async def make_request():
        resp = await client.get(api_url, headers=_rapidapi_headers(api_key, _INSTAGRAM_API_HOST))
        resp.raise_for_status()
        return resp.json()

    data = await retry_async(make_request, max_retries=3, initial_delay=1.0)

    media_url = _extract_instagram_media_url(data, content_type)
    edges = (data.get("data") or {}).get("edge_media_to_caption", {}).get("edges", [])
    caption_text = edges[0].get("node", {}).get("text", "") if edges else ""
    caption = _clean_instagram_caption(caption_text)

    d = data.get("data", data)
    thumbnail_url = d.get("display_url") if isinstance(d, dict) else None

    mime = "video/mp4" if content_type in ("reel", "story") else "image/jpeg"
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
