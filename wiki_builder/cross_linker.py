# gnammyAssistant/wiki_builder/cross_linker.py
import logging
from supabase import Client
from wiki_builder.models import ExtractedEntity, ExtractedConcept, slugify

logger = logging.getLogger(__name__)


class CrossLinker:
    def __init__(self, supabase_client: Client) -> None:
        self._db = supabase_client

    def resolve_and_persist(
        self,
        entities: list[ExtractedEntity],
        concepts: list[ExtractedConcept],
    ) -> None:
        # Cross-links are resolved only within the current batch (entities/concepts
        # extracted from the same recipe). Links to entities ingested in previous
        # recipes are not resolved here. A full cross-batch resolution pass would
        # require querying existing slugs from DB — out of scope for incremental ingestion.
        entity_slugs = {e.slug for e in entities}
        concept_slugs = {c.slug for c in concepts}

        for entity in entities:
            rel_entity_slugs = [
                s for name in entity.related_entities
                if (s := slugify(name)) in entity_slugs and s != entity.slug
            ]
            rel_concept_slugs = [
                s for name in entity.related_concepts
                if (s := slugify(name)) in concept_slugs
            ]
            if rel_entity_slugs or rel_concept_slugs:
                try:
                    self._db.table("wiki_entities").update({
                        "related_entity_slugs": rel_entity_slugs,
                        "related_concept_slugs": rel_concept_slugs,
                    }).eq("slug", entity.slug).execute()
                except Exception:
                    logger.exception("Cross-link update failed for entity slug=%s", entity.slug)

        for concept in concepts:
            rel_concept_slugs = [
                s for name in concept.related_concepts
                if (s := slugify(name)) in concept_slugs and s != concept.slug
            ]
            rel_entity_slugs = [
                s for name in concept.related_entities
                if (s := slugify(name)) in entity_slugs
            ]
            if rel_concept_slugs or rel_entity_slugs:
                try:
                    self._db.table("wiki_concepts").update({
                        "related_concept_slugs": rel_concept_slugs,
                        "related_entity_slugs": rel_entity_slugs,
                    }).eq("slug", concept.slug).execute()
                except Exception:
                    logger.exception("Cross-link update failed for concept slug=%s", concept.slug)
