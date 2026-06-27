from gnammyWiki.social_ingestion.recipe_writer import _normalize_tag, _build_recipe_payload


def test_normalize_tag_lowercases_and_strips():
    assert _normalize_tag("  Pasta  ") == "pasta"
    assert _normalize_tag("ITALIAN") == "italian"


def test_normalize_tag_empty_returns_none():
    assert _normalize_tag("") is None
    assert _normalize_tag("   ") is None


def test_build_recipe_payload_maps_fields():
    recipe_data = {
        "title": "Test",
        "description": "Desc",
        "difficulty": "facile",
        "prep_time_minutes": 10,
        "cook_time_minutes": 20,
        "servings": 4,
        "notes": "note",
        "tips": "tip",
        "steps": ["step1"],
    }
    payload = _build_recipe_payload(
        recipe_data=recipe_data,
        embedding=[0.1, 0.2],
        social_media_url="https://r2.example.com/job.mp4",
        thumbnail_url="https://r2.example.com/thumb.jpg",
    )
    assert payload["title"] == "Test"
    assert payload["embedding"] == [0.1, 0.2]
    assert payload["url_social_media"] == "https://r2.example.com/job.mp4"
    assert payload["url_recipe_image"] == "https://r2.example.com/thumb.jpg"
