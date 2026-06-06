# gnammyAssistant/tests/unit/wiki_builder/test_page_factory.py
import pytest
from unittest.mock import MagicMock
from wiki_builder.page_factory import PageFactory, _build_entity_text, _build_concept_text
from wiki_builder.models import ExtractedEntity, ExtractedConcept, EntityType, ConceptType


def _make_entity(**kwargs) -> ExtractedEntity:
    defaults = dict(
        name="Parmigiano Reggiano",
        type=EntityType.ingredient,
        summary="Formaggio DOP.",
        mentions_in_source=["usato grattugiato"],
    )
    defaults.update(kwargs)
    return ExtractedEntity(**defaults)


def _make_concept(**kwargs) -> ExtractedConcept:
    defaults = dict(
        name="mantecatura",
        type=ConceptType.technique,
        definition="Incorporazione di burro a fine cottura.",
        key_characteristics=["cremosità"],
        applications=["risotto"],
        mentions_in_source=["mantecare con burro"],
    )
    defaults.update(kwargs)
    return ExtractedConcept(**defaults)


def test_build_entity_text_contains_name_and_summary():
    entity = _make_entity()
    text = _build_entity_text(entity)
    assert "Parmigiano Reggiano" in text
    assert "Formaggio DOP." in text


def test_build_concept_text_contains_definition():
    concept = _make_concept()
    text = _build_concept_text(concept)
    assert "mantecatura" in text
    assert "Incorporazione di burro" in text


def test_upsert_entity_calls_supabase_upsert():
    mock_client = MagicMock()
    mock_embed = MagicMock(return_value=[0.1] * 768)
    factory = PageFactory(supabase_client=mock_client, embed_fn=mock_embed)

    entity = _make_entity()
    recipe_id = "recipe-uuid-1"
    factory.upsert_entity(entity, recipe_id)

    mock_client.table.assert_called_with("wiki_entities")
    upsert_call = mock_client.table.return_value.upsert.call_args
    row = upsert_call[0][0]
    assert row["slug"] == "parmigiano-reggiano"
    assert row["name"] == "Parmigiano Reggiano"
    assert row["type"] == "ingredient"
    assert recipe_id in row["source_recipe_ids"]
    assert len(row["embedding"]) == 768


def test_upsert_concept_calls_supabase_upsert():
    mock_client = MagicMock()
    mock_embed = MagicMock(return_value=[0.2] * 768)
    factory = PageFactory(supabase_client=mock_client, embed_fn=mock_embed)

    concept = _make_concept()
    recipe_id = "recipe-uuid-2"
    factory.upsert_concept(concept, recipe_id)

    mock_client.table.assert_called_with("wiki_concepts")
    upsert_call = mock_client.table.return_value.upsert.call_args
    row = upsert_call[0][0]
    assert row["slug"] == "mantecatura"
    assert row["type"] == "technique"
    assert recipe_id in row["source_recipe_ids"]


def test_upsert_entity_merges_mentions_and_recipe_ids():
    existing = {
        "slug": "parmigiano-reggiano",
        "mentions_in_sources": ["precedente citazione"],
        "source_recipe_ids": ["old-recipe-uuid"],
        "version": 2,
    }
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = existing
    mock_embed = MagicMock(return_value=[0.1] * 768)
    factory = PageFactory(supabase_client=mock_client, embed_fn=mock_embed)

    entity = _make_entity(mentions_in_source=["nuova citazione"])
    factory.upsert_entity(entity, "new-recipe-uuid")

    upsert_call = mock_client.table.return_value.upsert.call_args
    row = upsert_call[0][0]
    assert "precedente citazione" in row["mentions_in_sources"]
    assert "nuova citazione" in row["mentions_in_sources"]
    assert "old-recipe-uuid" in row["source_recipe_ids"]
    assert "new-recipe-uuid" in row["source_recipe_ids"]
    assert row["version"] == 3
