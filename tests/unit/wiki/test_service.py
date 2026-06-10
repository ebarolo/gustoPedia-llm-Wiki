from unittest.mock import MagicMock, patch

import pytest

from wiki.models import AnalysisCreate, AnalysisResult, AnalysisUpdate
from wiki.service import WikiIngestionService

RECIPE_ROW = {
    "id": "r-1",
    "title": "Carbonara",
    "description": "Primo romano.",
    "steps": ["passo 1"],
    "tips": "",
    "notes": "",
    "difficulty": "Media",
    "prep_time_minutes": 10,
    "cook_time_minutes": 15,
    "servings": 4,
    "recipe_ingredients": [],
    "recipe_tags": [],
}

GENERATION = """---PAGE: guanciale---
Guanciale
Salume di guancia di maiale.

Corpo con link a [[carbonara]].
---END---
---PAGE: carbonara---
Carbonara
Primo piatto romano.

Corpo con link a [[guanciale]].
---END---
---PAGE: fuori-piano---
Fuori piano
Non richiesto dall'analisi.

Corpo.
---END---
"""


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    return WikiIngestionService(MagicMock())


@pytest.mark.asyncio
async def test_ingest_writes_planned_pages_only(service):
    analysis = AnalysisResult(
        update=[AnalysisUpdate(slug="guanciale", reason="r")],
        create=[AnalysisCreate(slug="carbonara", title="Carbonara", page_type="piatto", reason="r")],
        links=[["carbonara", "guanciale"]],
    )
    existing_guanciale = {
        "id": "p-guanciale",
        "slug": "guanciale",
        "title": "Guanciale",
        "page_type": "ingrediente",
        "summary": "vecchia sintesi",
        "content_md": "vecchio corpo",
        "version": 2,
        "source_recipe_ids": [],
    }

    with patch("wiki.service.WikiIngestionService._fetch_recipe", return_value=RECIPE_ROW), \
         patch("wiki.service.page_store.fetch_index", return_value=[
             {"slug": "guanciale", "title": "Guanciale", "page_type": "ingrediente", "summary": "s"}
         ]), \
         patch("wiki.service.analyzer.analyze", return_value=analysis), \
         patch("wiki.service.page_store.fetch_pages_by_slugs", return_value=[existing_guanciale]), \
         patch("wiki.service.generator.generate", return_value=GENERATION), \
         patch("wiki.service.page_store.upsert_page", side_effect=["p-guanciale", "p-carbonara"]) as upsert, \
         patch("wiki.service.page_store.slug_to_id_map", return_value={}), \
         patch("wiki.service.page_store.replace_links") as replace_links, \
         patch("wiki.service.page_store.insert_log") as insert_log, \
         patch("wiki.service.embedder.rechunk_and_embed", return_value=1), \
         patch("wiki.service.job_manager.append_log"):
        pages = await service.ingest_recipe("job-1", "r-1")

    # whitelist: il blocco fuori-piano non viene scritto
    written_slugs = [call.kwargs["slug"] for call in upsert.call_args_list]
    assert written_slugs == ["guanciale", "carbonara"]
    assert set(pages) == {"p-guanciale", "p-carbonara"}

    # update: version++ via existing, title/summary dal blocco generato
    guanciale_call = upsert.call_args_list[0]
    assert guanciale_call.kwargs["existing"] == existing_guanciale
    assert guanciale_call.kwargs["summary"] == "Salume di guancia di maiale."

    # link espliciti dai [[wikilink]] reali
    assert replace_links.call_count == 2
    targets = {call.args[1]: call.args[2] for call in replace_links.call_args_list}
    assert targets["p-guanciale"] == ["p-carbonara"]
    assert targets["p-carbonara"] == ["p-guanciale"]

    # log append-only con dettaglio analisi
    assert insert_log.call_count == 1
    assert insert_log.call_args.args[1] == "ingest"
    assert insert_log.call_args.args[2] == "Carbonara"


@pytest.mark.asyncio
async def test_ingest_empty_analysis_skips_generation(service):
    with patch("wiki.service.WikiIngestionService._fetch_recipe", return_value=RECIPE_ROW), \
         patch("wiki.service.page_store.fetch_index", return_value=[]), \
         patch("wiki.service.analyzer.analyze", return_value=AnalysisResult()), \
         patch("wiki.service.generator.generate") as generate, \
         patch("wiki.service.page_store.insert_log") as insert_log, \
         patch("wiki.service.job_manager.append_log"):
        pages = await service.ingest_recipe("job-1", "r-1")

    assert pages == []
    generate.assert_not_called()
    assert insert_log.call_args.args[4]["skipped"] is True


@pytest.mark.asyncio
async def test_ingest_no_valid_blocks_raises(service):
    analysis = AnalysisResult(
        create=[AnalysisCreate(slug="carbonara", title="Carbonara", page_type="piatto")],
    )
    with patch("wiki.service.WikiIngestionService._fetch_recipe", return_value=RECIPE_ROW), \
         patch("wiki.service.page_store.fetch_index", return_value=[]), \
         patch("wiki.service.analyzer.analyze", return_value=analysis), \
         patch("wiki.service.page_store.fetch_pages_by_slugs", return_value=[]), \
         patch("wiki.service.generator.generate", return_value="testo senza blocchi"), \
         patch("wiki.service.page_store.insert_log"), \
         patch("wiki.service.job_manager.append_log"):
        with pytest.raises(RuntimeError):
            await service.ingest_recipe("job-1", "r-1")
