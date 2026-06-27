import pytest
from gnammyWiki.social_ingestion.url_sanitizer import sanitize_url, detect_platform
from gnammyWiki.social_ingestion.models import Platform


def test_youtube_keeps_only_v_param():
    url = "https://www.youtube.com/watch?v=abc123&feature=share&si=xyz"
    result = sanitize_url(url)
    assert result == "https://www.youtube.com/watch?v=abc123"


def test_youtube_short_link_unchanged():
    url = "https://youtu.be/abc123?si=xyz"
    result = sanitize_url(url)
    assert "abc123" in result
    assert "si=" not in result


def test_instagram_strips_all_params():
    url = "https://www.instagram.com/reel/ABC123/?igsh=xyz&igshid=abc"
    result = sanitize_url(url)
    assert "igsh" not in result
    assert "igshid" not in result
    assert "instagram.com/reel/ABC123/" in result


def test_invalid_url_returned_unchanged():
    url = "not-a-url"
    result = sanitize_url(url)
    assert result == "not-a-url"


def test_detect_instagram():
    assert detect_platform("https://www.instagram.com/reel/ABC/") == Platform.INSTAGRAM


def test_detect_youtube():
    assert detect_platform("https://www.youtube.com/watch?v=abc") == Platform.YOUTUBE
    assert detect_platform("https://youtu.be/abc") == Platform.YOUTUBE


def test_detect_unknown_raises():
    with pytest.raises(ValueError, match="Unsupported"):
        detect_platform("https://tiktok.com/video/123")
