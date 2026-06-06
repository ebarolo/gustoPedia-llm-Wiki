# gnammyAssistant/wiki_builder/page_factory.py
import logging
from typing import Callable, Optional
from supabase import Client
from wiki_builder.models import ExtractedEntity, ExtractedConcept

logger = logging.getLogger(__name__)


def _build_entity_text(entity: ExtractedEntity) -> str:
    parts = [f"# {entity.name}", f"Tipo: {entity.type.value}", entity.summary]
    if entity.mentions_in_source:
        parts.append("Citazioni: " + "; ".join(entity.mentions_in_source))
    if entity.related_entities:
        parts.append("Entità correlate: " + ", ".join(entity.related_entities))
    if entity.related_concepts:
        parts.append("Concetti correlati: " + ", ".join(entity.related_concepts))
    return "\n".join(parts)


def _build_concept_text(concept: ExtractedConcept) -> str:
    parts = [f"# {concept.name}", f"Tipo: {concept.type.value}", concept.definition]
    if concept.key_characteristics:
        parts.append("Caratteristiche: " + "; ".join(concept.key_characteristics))
    if concept.applications:
        parts.append("Applicazioni: " + ", ".join(concept.applications))
    if concept.mentions_in_source:
        parts.append("Citazioni: " + "; ".join(concept.mentions_in_source))
    return "\n".join(parts)


def _merge_unique(existing: list, new: list) -> list:
    seen = set(existing)
    return existing + [x for x in new if x not in seen]


class PageFactory:
    def __init__(self, supabase_client: Client, embed_fn: Callable[[str], list[float]]) -> None:
        self._db = supabase_client
        self._embed = embed_fn

    def _fetch_existing_entity(self, slug: str) -> Optional[dict]:
        resp = (
            self._db.table("wiki_entities")
            .select("slug,mentions_in_sources,source_recipe_ids,version")
            .eq("slug", slug)
            .maybe_single()
            .execute()
        )
        data = resp.data if resp is not None else None
        return data if isinstance(data, dict) else None

    def _fetch_existing_concept(self, slug: str) -> Optional[dict]:
        resp = (
            self._db.table("wiki_concepts")
            .select("slug,mentions_in_sources,source_recipe_ids,version")
            .eq("slug", slug)
            .maybe_single()
            .execute()
        )
        data = resp.data if resp is not None else None
        return data if isinstance(data, dict) else None

    def upsert_entity(self, entity: ExtractedEntity, recipe_id: str) -> None:
        existing = self._fetch_existing_entity(entity.slug)
        prev_mentions: list[str] = (existing or {}).get("mentions_in_sources") or []
        prev_recipes: list[str] = (existing or {}).get("source_recipe_ids") or []
        prev_version: int = (existing or {}).get("version") or 0

        merged_mentions = _merge_unique(prev_mentions, entity.mentions_in_source)
        merged_recipes = _merge_unique(prev_recipes, [recipe_id])

        text = _build_entity_text(entity)
        embedding = self._embed(text)

        row = {
            "slug": entity.slug,
            "name": entity.name,
            "type": entity.type.value,
            "aliases": entity.aliases,
            "summary": entity.summary,
            "description_md": text,
            "mentions_in_sources": merged_mentions,
            "source_recipe_ids": merged_recipes,
            "embedding": embedding,
            "version": prev_version + 1,
        }
        self._db.table("wiki_entities").upsert(row, on_conflict="slug").execute()
        logger.debug("Upserted entity slug=%s recipe=%s", entity.slug, recipe_id)

    def upsert_concept(self, concept: ExtractedConcept, recipe_id: str) -> None:
        existing = self._fetch_existing_concept(concept.slug)
        prev_mentions: list[str] = (existing or {}).get("mentions_in_sources") or []
        prev_recipes: list[str] = (existing or {}).get("source_recipe_ids") or []
        prev_version: int = (existing or {}).get("version") or 0

        merged_mentions = _merge_unique(prev_mentions, concept.mentions_in_source)
        merged_recipes = _merge_unique(prev_recipes, [recipe_id])

        text = _build_concept_text(concept)
        embedding = self._embed(text)

        row = {
            "slug": concept.slug,
            "name": concept.name,
            "type": concept.type.value,
            "aliases": concept.aliases,
            "definition": concept.definition,
            "key_characteristics": concept.key_characteristics,
            "applications": concept.applications,
            "mentions_in_sources": merged_mentions,
            "source_recipe_ids": merged_recipes,
            "embedding": embedding,
            "version": prev_version + 1,
        }
        self._db.table("wiki_concepts").upsert(row, on_conflict="slug").execute()
        logger.debug("Upserted concept slug=%s recipe=%s", concept.slug, recipe_id)
