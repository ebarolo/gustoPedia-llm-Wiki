# gnammyAssistant/tests/unit/wiki_builder/test_models.py
import pytest
from wiki_builder.models import (
    EntityType, ConceptType, ExtractedEntity, ExtractedConcept,
    SourceExtractionResult, slugify,
)


def test_slugify_basic():
    assert slugify("Parmigiano Reggiano") == "parmigiano-reggiano"


def test_slugify_accents():
    assert slugify("Mantecatura à la italiana") == "mantecatura-a-la-italiana"


def test_slugify_special_chars():
    assert slugify("Pasta e Fagioli (tradizionale)") == "pasta-e-fagioli-tradizionale"


def test_slugify_already_slug():
    assert slugify("risotto-milanese") == "risotto-milanese"


def test_extracted_entity_valid():
    e = ExtractedEntity(
        name="Parmigiano Reggiano",
        type=EntityType.ingredient,
        aliases=["Parmigiano"],
        summary="Formaggio DOP stagionato a pasta dura.",
        mentions_in_source=["usato grattugiato"],
        related_entities=[],
        related_concepts=["stagionatura"],
    )
    assert e.slug == "parmigiano-reggiano"


def test_extracted_concept_valid():
    c = ExtractedConcept(
        name="mantecatura",
        type=ConceptType.technique,
        aliases=["mantecare"],
        definition="Tecnica di incorporazione di grassi a fine cottura per ottenere cremosità.",
        key_characteristics=["emulsionamento", "cremosità"],
        applications=["risotto", "pasta"],
        mentions_in_source=["mantecare con burro"],
        related_concepts=["emulsificazione"],
        related_entities=[],
    )
    assert c.slug == "mantecatura"


def test_source_extraction_result_entity_count():
    result = SourceExtractionResult(
        recipe_id="uuid-123",
        source_title="Risotto alla Milanese",
        entities=[
            ExtractedEntity(
                name="Zafferano",
                type=EntityType.ingredient,
                summary="Spezia pregiata.",
                mentions_in_source=["aggiunto a fine cottura"],
            )
        ],
        concepts=[],
    )
    assert len(result.entities) == 1
    assert result.entities[0].slug == "zafferano"
