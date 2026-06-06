# gnammyAssistant/tests/unit/wiki_builder/test_source_analyzer.py
import json
import pytest
from unittest.mock import MagicMock
from wiki_builder.source_analyzer import SourceAnalyzer, _parse_extraction_response
from wiki_builder.models import EntityType, ConceptType


VALID_LLM_RESPONSE = json.dumps({
    "source_title": "Risotto alla Milanese",
    "entities": [
        {
            "name": "Zafferano",
            "type": "ingredient",
            "aliases": ["Crocus sativus"],
            "summary": "Spezia gialla ottenuta dagli stigmi del Crocus.",
            "mentions_in_source": ["aggiunto a fine cottura"],
            "related_entities": ["Brodo di carne"],
            "related_concepts": ["infusione"],
        }
    ],
    "concepts": [
        {
            "name": "mantecatura",
            "type": "technique",
            "aliases": ["mantecare"],
            "definition": "Incorporazione di burro e Parmigiano a fine cottura.",
            "key_characteristics": ["cremosità", "emulsionamento"],
            "applications": ["risotto", "pasta"],
            "mentions_in_source": ["mantecare con burro"],
            "related_concepts": ["emulsificazione"],
            "related_entities": ["Parmigiano Reggiano"],
        }
    ],
})


def test_parse_extraction_response_valid():
    result = _parse_extraction_response(VALID_LLM_RESPONSE, "recipe-uuid-1")
    assert result is not None
    assert result.recipe_id == "recipe-uuid-1"
    assert len(result.entities) == 1
    assert result.entities[0].name == "Zafferano"
    assert result.entities[0].type == EntityType.ingredient
    assert len(result.concepts) == 1
    assert result.concepts[0].name == "mantecatura"
    assert result.concepts[0].type == ConceptType.technique


def test_parse_extraction_response_strips_markdown_fence():
    wrapped = f"```json\n{VALID_LLM_RESPONSE}\n```"
    result = _parse_extraction_response(wrapped, "recipe-uuid-2")
    assert result is not None
    assert len(result.entities) == 1


def test_parse_extraction_response_invalid_json_returns_none():
    result = _parse_extraction_response("not valid json", "recipe-uuid-3")
    assert result is None


def test_parse_extraction_response_empty_arrays_ok():
    empty = json.dumps({"source_title": "Pasta al Pomodoro", "entities": [], "concepts": []})
    result = _parse_extraction_response(empty, "recipe-uuid-4")
    assert result is not None
    assert result.entities == []
    assert result.concepts == []


def test_parse_extraction_response_unknown_entity_type_coerced():
    response = json.dumps({
        "source_title": "Test",
        "entities": [{"name": "X", "type": "unknown_type", "summary": "s", "mentions_in_source": []}],
        "concepts": [],
    })
    result = _parse_extraction_response(response, "recipe-uuid-5")
    assert result is not None
    assert result.entities[0].type == "other"


def test_source_analyzer_calls_gemini_and_returns_result():
    mock_genai_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = VALID_LLM_RESPONSE
    mock_genai_client.models.generate_content.return_value = mock_response

    analyzer = SourceAnalyzer(genai_client=mock_genai_client)
    recipe = {
        "id": "recipe-uuid-6",
        "title": "Risotto alla Milanese",
        "description": "Classico risotto giallo milanese.",
        "difficulty": "media",
        "ingredients": ["Riso Carnaroli", "Zafferano", "Burro", "Parmigiano Reggiano"],
        "categories": ["primo", "tradizionale"],
    }
    result = analyzer.analyze(recipe)
    assert result is not None
    assert result.recipe_id == "recipe-uuid-6"
    mock_genai_client.models.generate_content.assert_called_once()
