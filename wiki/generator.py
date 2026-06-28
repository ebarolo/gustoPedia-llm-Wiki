# GustoPedia/wiki/generator.py
import logging

from google import genai
from supabase import Client

from shared.retry import retry_sync
from wiki.prompts import load_prompt

logger = logging.getLogger(__name__)

_MODEL = "gemini-3.5-flash"


def generate(
    db: Client,
    analysis_json: str,
    pages_payload: str,
    recipe_json: str,
    gemini_api_key: str,
) -> str:
    """Step 2: scrive i blocchi ---PAGE--- con le pagine reali sotto gli occhi."""
    prompt = load_prompt(
        db,
        "wiki_generation",
        {
            "analysis_json": analysis_json,
            "pages_payload": pages_payload,
            "recipe_json": recipe_json,
        },
    )
    client = genai.Client(api_key=gemini_api_key)
    response = retry_sync(
        client.models.generate_content,
        model=_MODEL,
        contents=prompt,
        max_retries=3,
        initial_delay=1.0,
    )
    return response.text or ""


def build_pages_payload(pages: list[dict]) -> str:
    """Blocco testuale col contenuto attuale delle pagine da aggiornare."""
    if not pages:
        return "(nessuna pagina esistente da aggiornare: solo creazioni)"
    parts = []
    for p in pages:
        parts.append(
            f"### slug: {p['slug']}\n"
            f"{p['title']}\n{p['summary']}\n\n{p['content_md']}"
        )
    return "\n\n---\n\n".join(parts)
