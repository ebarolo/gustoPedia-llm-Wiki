# GustoPedia/wiki/analyzer.py
import json
import logging
import re

from google import genai
from google.genai import types
from supabase import Client

from shared.retry import retry_sync
from wiki.models import PAGE_TYPES, AnalysisResult
from wiki.parser import is_safe_slug
from wiki.prompts import load_prompt

logger = logging.getLogger(__name__)

_MODEL = "gemini-3.5-flash"

_WIKI_PURPOSE = (
    "Scopo della wiki: accumulare conoscenza culinaria trasversale "
    "(ingredienti, tecniche, piatti, regioni, concetti) compilata una volta "
    "all'ingest e mantenuta nel tempo, a servizio degli agenti e dell'app GustoPedia."
)


def analyze(
    db: Client,
    recipe_json: str,
    wiki_index_text: str,
    gemini_api_key: str,
) -> AnalysisResult:
    """Step 1: decide quali pagine toccare, con l'indice sotto gli occhi."""
    prompt = load_prompt(
        db,
        "wiki_analysis",
        {
            "recipe_json": recipe_json,
            "wiki_index": wiki_index_text,
            "wiki_purpose": _WIKI_PURPOSE,
        },
    )
    client = genai.Client(api_key=gemini_api_key)
    response = retry_sync(
        client.models.generate_content,
        model=_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
        max_retries=3,
        initial_delay=1.0,
    )
    raw = re.sub(r"```(?:json)?\n?|\n?```", "", response.text or "").strip()
    result = AnalysisResult.model_validate(json.loads(raw))
    return _clamp(result, wiki_index_text)


def _clamp(result: AnalysisResult, wiki_index_text: str) -> AnalysisResult:
    """L'LLM non decide fuori piano: update solo su slug esistenti,
    create solo su slug nuovi, validi e con page_type ammesso."""
    existing = {
        line.split(" | ")[0].strip()
        for line in wiki_index_text.split("\n")
        if " | " in line
    }
    result.update = [u for u in result.update if u.slug in existing]
    result.create = [
        c
        for c in result.create
        if is_safe_slug(c.slug) and c.slug not in existing and c.page_type in PAGE_TYPES
    ]
    planned = result.planned_slugs | existing
    result.links = [
        pair for pair in result.links
        if len(pair) == 2 and pair[0] in planned and pair[1] in planned
    ]
    return result
