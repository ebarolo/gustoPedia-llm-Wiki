# gnammyAssistant/tests/unit/wiki_builder/test_cross_linker.py
import pytest
from unittest.mock import MagicMock
from wiki_builder.cross_linker import CrossLinker
from wiki_builder.models import ExtractedEntity, ExtractedConcept, EntityType, ConceptType


def _entity(name, related_entities=None, related_concepts=None):
    return ExtractedEntity(
        name=name, type=EntityType.ingredient, summary=".",
        mentions_in_source=[],
        related_entities=related_entities or [],
        related_concepts=related_concepts or [],
    )


def _concept(name, related_concepts=None, related_entities=None):
    return ExtractedConcept(
        name=name, type=ConceptType.technique, definition=".",
        mentions_in_source=[],
        related_concepts=related_concepts or [],
        related_entities=related_entities or [],
    )


def test_resolve_entity_related_entity_slugs():
    mock_client = MagicMock()
    linker = CrossLinker(supabase_client=mock_client)
    entity = _entity("Parmigiano Reggiano", related_entities=["Grana Padano"])
    entities = [entity, _entity("Grana Padano")]
    concepts: list = []

    linker.resolve_and_persist(entities, concepts)

    update_calls = mock_client.table.return_value.update.call_args_list
    assert any(
        call_args[0][0].get("related_entity_slugs") == ["grana-padano"]
        for call_args in update_calls
    )


def test_resolve_entity_related_concept_slugs():
    mock_client = MagicMock()
    linker = CrossLinker(supabase_client=mock_client)
    entity = _entity("Risotto", related_concepts=["mantecatura"])
    concepts = [_concept("mantecatura")]
    entities = [entity]

    linker.resolve_and_persist(entities, concepts)

    update_calls = mock_client.table.return_value.update.call_args_list
    assert any(
        "mantecatura" in (call_args[0][0].get("related_concept_slugs") or [])
        for call_args in update_calls
    )


def test_unknown_related_name_is_ignored():
    mock_client = MagicMock()
    linker = CrossLinker(supabase_client=mock_client)
    entity = _entity("Risotto", related_entities=["Ingrediente Inesistente"])
    entities = [entity]
    concepts: list = []

    linker.resolve_and_persist(entities, concepts)

    update_calls = mock_client.table.return_value.update.call_args_list
    for call_args in update_calls:
        slugs = call_args[0][0].get("related_entity_slugs") or []
        assert "ingrediente-inesistente" not in slugs
