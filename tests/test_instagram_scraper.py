import pytest
from unittest.mock import AsyncMock, patch
import httpx

from social_ingestion.scraper import (
    _detect_instagram_content_type,
    _clean_instagram_caption,
    scrape,
    _scrape_instagram,
)
from social_ingestion.models import Platform, ScrapeResult

def test_detect_instagram_content_type():
    assert _detect_instagram_content_type("https://www.instagram.com/p/DG594WZOqfM/") == "post"
    assert _detect_instagram_content_type("https://www.instagram.com/reel/DZ7Fwxwt2Pn/") == "reel"
    assert _detect_instagram_content_type("https://www.instagram.com/reels/DZ7Fwxwt2Pn/") == "reel"
    assert _detect_instagram_content_type("https://www.instagram.com/stories/username/12345/") == "story"
    assert _detect_instagram_content_type("https://www.instagram.com/username/") == "generic"

def test_clean_instagram_caption():
    raw_caption = "Pasta fredda di mare\nChe ve lo dico a fa!\n\nIngredienti x 4 persone \n#summer 🍝"
    cleaned = _clean_instagram_caption(raw_caption)
    # Newlines are replaced by spaces, hashtags are stripped of '#', emojis are removed
    assert "Pasta fredda di mare" in cleaned
    assert "Che ve lo dico a fa!" in cleaned
    assert "#summer" not in cleaned
    assert "summer" in cleaned

@pytest.mark.asyncio
async def test_scrape_instagram_image_post():
    mock_response_data = {
        "media": [
            {
                "url": "https://scontent.cdninstagram.com/v/image.jpg",
                "thumb": "https://scontent.cdninstagram.com/v/thumb.jpg",
                "is_video": False,
                "caption": "Questo è un post di prova!"
            }
        ],
        "owner": {
            "username": "test_user"
        }
    }

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_resp = AsyncMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_response_data
    mock_client.get.return_value = mock_resp

    result = await _scrape_instagram(
        url="https://www.instagram.com/p/DG594WZOqfM/",
        api_key="fake-key",
        client=mock_client
    )

    assert isinstance(result, ScrapeResult)
    assert result.media_url == "https://scontent.cdninstagram.com/v/image.jpg"
    assert result.thumbnail_url == "https://scontent.cdninstagram.com/v/thumb.jpg"
    assert result.platform == Platform.INSTAGRAM
    assert result.mime_type == "image/jpeg"
    assert "Questo è un post di prova!" in result.caption

@pytest.mark.asyncio
async def test_scrape_instagram_video_reel():
    mock_response_data = {
        "media": [
            {
                "url": "https://scontent.cdninstagram.com/v/video.mp4",
                "thumb": "https://scontent.cdninstagram.com/v/thumb.jpg",
                "is_video": True,
                "caption": "Video ricetta gustosa #cooking"
            }
        ],
        "owner": {
            "username": "chef_test"
        }
    }

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_resp = AsyncMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_response_data
    mock_client.get.return_value = mock_resp

    result = await _scrape_instagram(
        url="https://www.instagram.com/reel/DZ7Fwxwt2Pn/",
        api_key="fake-key",
        client=mock_client
    )

    assert isinstance(result, ScrapeResult)
    assert result.media_url == "https://scontent.cdninstagram.com/v/video.mp4"
    assert result.thumbnail_url == "https://scontent.cdninstagram.com/v/thumb.jpg"
    assert result.platform == Platform.INSTAGRAM
    assert result.mime_type == "video/mp4"
    assert "Video ricetta gustosa cooking" in result.caption

@pytest.mark.asyncio
async def test_scrape_instagram_invalid_response():
    mock_response_data = {} # missing media key

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_resp = AsyncMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_response_data
    mock_client.get.return_value = mock_resp

    with pytest.raises(ValueError, match="Invalid or empty Instagram API response format"):
        await _scrape_instagram(
            url="https://www.instagram.com/p/DG594WZOqfM/",
            api_key="fake-key",
            client=mock_client
        )
