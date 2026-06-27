import pytest
from gnammyWiki.social_ingestion.scraper import (
    _extract_instagram_media_url,
    _extract_youtube_video_id,
)


def test_extract_instagram_reel_video_url():
    data = {"data": {"video_url": "https://cdn.example.com/video.mp4"}}
    assert _extract_instagram_media_url(data, "reel") == "https://cdn.example.com/video.mp4"


def test_extract_instagram_post_display_url():
    data = {"data": {"display_url": "https://cdn.example.com/image.jpg"}}
    assert _extract_instagram_media_url(data, "post") == "https://cdn.example.com/image.jpg"


def test_extract_instagram_fallback_media_versions():
    data = {"data": {"media_versions": [{"url": "https://cdn.example.com/vid.mp4"}]}}
    assert _extract_instagram_media_url(data, "reel") == "https://cdn.example.com/vid.mp4"


def test_extract_instagram_no_url_raises():
    with pytest.raises(ValueError, match="No media URL"):
        _extract_instagram_media_url({}, "reel")


def test_extract_instagram_api_error():
    data = {"status": "error", "message": "media is not available"}
    with pytest.raises(ValueError, match="Instagram API error: media is not available"):
        _extract_instagram_media_url(data, "post")


def test_extract_instagram_invalid_data_type():
    data = {"data": "not-a-dict"}
    with pytest.raises(ValueError, match="Invalid Instagram API response format"):
        _extract_instagram_media_url(data, "post")


def test_extract_youtube_video_id_watch():
    assert _extract_youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&feature=share") == "dQw4w9WgXcQ"


def test_extract_youtube_video_id_short():
    assert _extract_youtube_video_id("https://youtu.be/dQw4w9WgXcQ?si=abc") == "dQw4w9WgXcQ"


def test_extract_youtube_video_id_shorts():
    assert _extract_youtube_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_youtube_video_id_invalid_raises():
    with pytest.raises(ValueError, match="Cannot extract"):
        _extract_youtube_video_id("https://youtube.com/channel/abc")
