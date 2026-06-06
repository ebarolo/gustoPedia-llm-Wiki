# gnammyAssistant/wiki_builder/wiki_service.py
import logging
import time
from typing import Any, Optional

from google import genai as google_genai
from supabase import Client

from wiki_builder.cross_linker import CrossLinker
from wiki_builder.page_factory import PageFactory
from wiki_builder.source_analyzer import SourceAnalyzer

logger = logging.getLogger(__name__)

_EMBED_MODEL = "gemini-embedding-2"
_EMBED_DIMENSIONS = 768
_BACKFILL_DELAY_SECONDS = 1.5


def _make_embed_fn(genai_client: Any):
    def embed(text: str) -> list[float]:
        from shared.retry import retry_sync
        result = retry_sync(
            genai_client.models.embed_content,
            model=_EMBED_MODEL,
            contents=text,
            config={"output_dimensionality": _EMBED_DIMENSIONS},
            max_retries=3,
            initial_delay=0.5
        )
        return result.embeddings[0].values
    return embed


def _fetch_recipe(recipe_id: str, client: Client) -> Optional[dict]:
    resp = (
        client.table("recipes")
        .select(
            "id, title, description, difficulty, "
            "ingredients:recipe_ingredients(ingredients:ingredients(name)), "
            "categories:recipe_categories(categories:categories(name))"
        )
        .eq("id", recipe_id)
        .single()
        .execute()
    )
    if not resp.data:
        return None
    raw = resp.data
    return {
        "id": raw["id"],
        "title": raw.get("title", ""),
        "description": raw.get("description", ""),
        "difficulty": raw.get("difficulty", ""),
        "ingredients": [
            ri["ingredients"]["name"]
            for ri in (raw.get("ingredients") or [])
            if ri.get("ingredients")
        ],
        "categories": [
            rc["categories"]["name"]
            for rc in (raw.get("categories") or [])
            if rc.get("categories")
        ],
    }


def _log_status(client: Client, recipe_id: str, status: str, **kwargs) -> None:
    try:
        client.table("wiki_ingestion_log").upsert(
            {"recipe_id": recipe_id, "status": status, **kwargs},
            on_conflict="recipe_id",
        ).execute()
    except Exception:
        logger.exception("Failed to write ingestion log for recipe_id=%s", recipe_id)


class WikiService:
    def __init__(self, supabase_client: Client, gemini_api_key: str) -> None:
        self._db = supabase_client
        genai_client = google_genai.Client(api_key=gemini_api_key)
        embed_fn = _make_embed_fn(genai_client)
        self._analyzer = SourceAnalyzer(genai_client=genai_client)
        self._factory = PageFactory(supabase_client=supabase_client, embed_fn=embed_fn)
        self._linker = CrossLinker(supabase_client=supabase_client)
        from wiki_builder.memory_tree_service import MemoryTreeService
        self._tree_service = MemoryTreeService(supabase_client=supabase_client, genai_client=genai_client)

    def ingest_recipe(self, recipe_id: str) -> dict[str, Any]:
        _log_status(self._db, recipe_id, "processing")
        recipe = _fetch_recipe(recipe_id, self._db)
        if not recipe:
            _log_status(self._db, recipe_id, "error", error_msg="Recipe not found")
            return {"ok": False, "error": "Recipe not found"}

        result = self._analyzer.analyze(recipe)
        if result is None:
            _log_status(self._db, recipe_id, "error", error_msg="LLM extraction failed")
            return {"ok": False, "error": "LLM extraction failed"}

        upsert_errors: list[str] = []
        for entity in result.entities:
            try:
                self._factory.upsert_entity(entity, recipe_id)
            except Exception:
                logger.exception("upsert_entity failed slug=%s recipe=%s", entity.slug, recipe_id)
                upsert_errors.append(entity.slug)

        for concept in result.concepts:
            try:
                self._factory.upsert_concept(concept, recipe_id)
            except Exception:
                logger.exception("upsert_concept failed slug=%s recipe=%s", concept.slug, recipe_id)
                upsert_errors.append(concept.slug)

        self._linker.resolve_and_persist(result.entities, result.concepts)

        # Aggiornamento asincrono dei Topic Trees (Lazy) in background
        import threading
        def run_lazy_updates(slugs_entities, slugs_concepts):
            for slug in slugs_entities:
                try:
                    self._tree_service.update_topic_tree(slug, is_concept=False)
                except Exception:
                    logger.exception("Lazy Topic Tree update failed for entity slug=%s", slug)
            for slug in slugs_concepts:
                try:
                    self._tree_service.update_topic_tree(slug, is_concept=True)
                except Exception:
                    logger.exception("Lazy Topic Tree update failed for concept slug=%s", slug)

        entity_slugs_to_update = [e.slug for e in result.entities if e.slug not in upsert_errors]
        concept_slugs_to_update = [c.slug for c in result.concepts if c.slug not in upsert_errors]
        
        threading.Thread(
            target=run_lazy_updates,
            args=(entity_slugs_to_update, concept_slugs_to_update),
            daemon=True
        ).start()

        _log_status(
            self._db, recipe_id, "done",
            entities_extracted=len(result.entities),
            concepts_extracted=len(result.concepts),
        )
        logger.info(
            "Ingested recipe_id=%s entities=%d concepts=%d upsert_errors=%d",
            recipe_id, len(result.entities), len(result.concepts), len(upsert_errors),
        )
        return {
            "ok": True,
            "entities": len(result.entities),
            "concepts": len(result.concepts),
            "upsert_errors": len(upsert_errors),
        }

    def trigger_daily_digest(self) -> bool:
        """Avvia la generazione del global tree giornaliero."""
        try:
            return self._tree_service.generate_daily_global_tree()
        except Exception:
            logger.exception("Failed to generate daily global tree digest")
            return False


    def backfill(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        done_resp = self._db.table("wiki_ingestion_log").select("recipe_id").eq("status", "done").limit(100000).execute()
        done_ids = {row["recipe_id"] for row in (done_resp.data or [])}

        all_resp = self._db.table("recipes").select("id").limit(100000).execute()
        all_ids = [row["id"] for row in (all_resp.data or [])]

        pending = [rid for rid in all_ids if rid not in done_ids]
        batch = pending[offset: offset + limit]

        results = []
        for recipe_id in batch:
            outcome = self.ingest_recipe(recipe_id)
            results.append({"recipe_id": recipe_id, **outcome})
            time.sleep(_BACKFILL_DELAY_SECONDS)

        return {"processed": len(batch), "results": results}
