# gnammyWiki/wiki/service.py
import json
import logging
import os
from typing import Any

from supabase import Client

from wiki import analyzer, embedder, generator, job_manager, page_store
from wiki.models import AnalysisResult
from wiki.parser import PageBlock, extract_wikilinks, parse_page_blocks, split_page_block
from wiki.repair import repair_dangling_links

logger = logging.getLogger(__name__)


class WikiIngestionService:
    """Pipeline ingest 2-step (docs/gnammy-wiki-plan.md §5):
    analysis (cosa toccare) → generation (contenuto) → parse/validazione →
    repair → scrittura con re-embed incrementale + wiki_log."""

    def __init__(self, db: Client) -> None:
        self._db = db
        self._gemini_api_key = os.environ["GEMINI_API_KEY"]

    async def ingest_recipe(self, job_id: str, recipe_id: str) -> list[str]:
        """Esegue l'ingest wiki di una ricetta. Ritorna gli id pagine toccate."""
        db = self._db
        recipe = self._fetch_recipe(recipe_id)
        recipe_json = json.dumps(recipe, ensure_ascii=False, default=str)
        ref_label = recipe.get("title") or recipe_id

        job_manager.append_log(db, job_id, "info", f"Analisi wiki per: {ref_label}")
        index_rows = page_store.fetch_index(db)
        index_text = page_store.format_index(index_rows)
        analysis = analyzer.analyze(db, recipe_json, index_text, self._gemini_api_key)

        if analysis.is_empty:
            job_manager.append_log(db, job_id, "info", "Analisi: nulla di sostanziale da scrivere.")
            page_store.insert_log(db, "ingest", ref_label, [], {"analysis": analysis.model_dump(), "skipped": True})
            return []

        job_manager.append_log(
            db, job_id, "info",
            f"Piano: {len(analysis.update)} update, {len(analysis.create)} create.",
        )

        existing_pages = page_store.fetch_pages_by_slugs(db, [u.slug for u in analysis.update])
        pages_payload = generator.build_pages_payload(existing_pages)

        job_manager.append_log(db, job_id, "info", "Generazione pagine...")
        raw = generator.generate(
            db,
            json.dumps(analysis.model_dump(), ensure_ascii=False),
            pages_payload,
            recipe_json,
            self._gemini_api_key,
        )

        blocks, warnings = self._parse_and_whitelist(raw, analysis)
        for warning in warnings:
            job_manager.append_log(db, job_id, "warn", warning)
        if not blocks:
            raise RuntimeError("La generazione non ha prodotto blocchi pagina validi.")

        known_slugs = {r["slug"] for r in index_rows}
        blocks, stubs = repair_dangling_links(blocks, known_slugs)

        pages_touched = self._write_pages(
            blocks, stubs, analysis, existing_pages, recipe_id, job_id
        )

        page_store.insert_log(
            db, "ingest", ref_label, pages_touched,
            {"analysis": analysis.model_dump(), "warnings": warnings, "stubs": len(stubs)},
        )
        job_manager.append_log(db, job_id, "info", f"Completato: {len(pages_touched)} pagine toccate.")
        return pages_touched

    def _fetch_recipe(self, recipe_id: str) -> dict[str, Any]:
        resp = (
            self._db.table("recipes")
            .select(
                "id, title, description, steps, tips, notes, difficulty, "
                "prep_time_minutes, cook_time_minutes, servings, "
                "recipe_ingredients(quantity, unit, is_optional, notes, ingredients(name)), "
                "recipe_tags(tags(name))"
            )
            .eq("id", recipe_id)
            .single()
            .execute()
        )
        return resp.data

    def _parse_and_whitelist(
        self, raw: str, analysis: AnalysisResult
    ) -> tuple[list[PageBlock], list[str]]:
        result = parse_page_blocks(raw)
        warnings = list(result.warnings)
        whitelist = analysis.planned_slugs
        blocks: list[PageBlock] = []
        for block in result.blocks:
            if block.slug in whitelist:
                blocks.append(block)
            else:
                warnings.append(f'Blocco fuori piano "{block.slug}" scartato.')
        return blocks, warnings

    def _write_pages(
        self,
        blocks: list[PageBlock],
        stubs: list[PageBlock],
        analysis: AnalysisResult,
        existing_pages: list[dict[str, Any]],
        recipe_id: str,
        job_id: str,
    ) -> list[str]:
        db = self._db
        existing_by_slug = {p["slug"]: p for p in existing_pages}
        type_by_slug = {c.slug: c.page_type for c in analysis.create}

        page_ids: dict[str, str] = {}
        for block in blocks:
            title, summary, body = split_page_block(block.markdown)
            existing = existing_by_slug.get(block.slug)
            page_type = (
                existing["page_type"] if existing
                else type_by_slug.get(block.slug, "concetto")
            )
            page_ids[block.slug] = page_store.upsert_page(
                db,
                slug=block.slug,
                title=title or block.slug,
                page_type=page_type,
                summary=summary,
                content_md=body,
                recipe_id=recipe_id,
                existing=existing,
            )
        for stub in stubs:
            title, summary, body = split_page_block(stub.markdown)
            page_ids[stub.slug] = page_store.upsert_page(
                db,
                slug=stub.slug,
                title=title or stub.slug,
                page_type="concetto",
                summary=summary,
                content_md=body,
                recipe_id=recipe_id,
                existing=None,
            )

        # Link espliciti: dai [[wikilink]] reali del contenuto scritto
        all_slugs = sorted(
            {t for b in blocks for t in extract_wikilinks(b.markdown)} | set(page_ids)
        )
        id_map = {**page_store.slug_to_id_map(db, all_slugs), **page_ids}
        for block in blocks:
            targets = [
                id_map[t]
                for t in extract_wikilinks(block.markdown)
                if t in id_map
            ]
            page_store.replace_links(db, page_ids[block.slug], targets)

        # Re-embed incrementale: solo pagine toccate
        job_manager.append_log(db, job_id, "info", f"Re-embedding di {len(page_ids)} pagine...")
        for block in blocks + stubs:
            title, _, body = split_page_block(block.markdown)
            embedder.rechunk_and_embed(
                db, page_ids[block.slug], title or block.slug, body, self._gemini_api_key
            )

        return list(page_ids.values())
