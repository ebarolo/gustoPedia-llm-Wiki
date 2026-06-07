import asyncio
import json
import logging
import os
import re
import tempfile
from typing import Any, Optional

from google import genai
from google.genai import types
from supabase import Client

from shared.retry import retry_sync

logger = logging.getLogger(__name__)

_MODEL = "gemini-3.5-flash"
_POLL_INTERVAL_S = 3.0
_MAX_POLL = 20

_CANONICAL_CATEGORIES = [
    "Antipasti", "Primi Piatti", "Secondi Piatti", "Contorni", "Dolci",
    "Pane e Lievitati", "Pizze e Focacce", "Colazione e Merende",
    "Insalate", "Zuppe e Minestre", "Salse e Condimenti", "Bevande",
]

_FALLBACK_PROMPT = (
    "Sei un assistente culinario esperto. Estrai la ricetta dal media fornito. "
    "Caption: {caption}. "
    "Rispondi SOLO con JSON valido con questi campi: "
    "is_recipe (bool), title, description, difficulty, prep_time_minutes, "
    "cook_time_minutes, servings, notes, tips, steps (array), "
    "ingredients (array of {{name,quantity,unit,is_optional,notes}}), "
    "categories (da: {categories}), tags (array). "
    "Se non è una ricetta: {{\"is_recipe\": false, \"error\": \"motivo\"}}"
)


def _load_system_prompt(db: Client, caption: str) -> str:
    try:
        resp = (
            db.table("prompts")
            .select("content")
            .eq("key", "process_recipe_system")
            .single()
            .execute()
        )
        template: str = resp.data["content"]
        return (
            template
            .replace("{{caption}}", caption)
            .replace("{{canonicalCategories}}", ", ".join(_CANONICAL_CATEGORIES))
        )
    except Exception:
        logger.exception("Failed to load prompt from DB, using fallback")
        return _FALLBACK_PROMPT.format(
            caption=caption,
            categories=", ".join(_CANONICAL_CATEGORIES),
        )


async def extract_recipe(
    media_data: bytes,
    mime_type: str,
    caption: str,
    filename: str,
    gemini_api_key: str,
    db: Client,
) -> dict[str, Any]:
    """Upload media to Gemini File API, run multimodal extraction, return parsed recipe dict."""
    client = genai.Client(api_key=gemini_api_key)

    # Write media_data bytes to a temporary file because client.files.upload expects a file path
    suffix = os.path.splitext(filename)[1] or f".{mime_type.split('/')[-1]}"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_file.write(media_data)
        temp_file_path = temp_file.name

    try:
        logger.info("Uploading %s to Gemini File API via temp file (%.2f MB)", filename, len(media_data) / 1024 / 1024)
        upload_resp = retry_sync(
            client.files.upload,
            file=temp_file_path,
            config=types.UploadFileConfig(mime_type=mime_type, display_name=filename),
            max_retries=3,
            initial_delay=1.0
        )
    finally:
        try:
            os.remove(temp_file_path)
        except Exception:
            logger.warning("Failed to remove temporary file: %s", temp_file_path)

    logger.info("Gemini file URI: %s state=%s", upload_resp.uri, upload_resp.state)

    file_info = upload_resp
    for _ in range(_MAX_POLL):
        if file_info.state.name == "ACTIVE":
            break
        if file_info.state.name == "FAILED":
            raise RuntimeError(f"Gemini File API processing failed: {file_info.state}")
        await asyncio.sleep(_POLL_INTERVAL_S)
        file_info = retry_sync(
            client.files.get,
            name=upload_resp.name,
            max_retries=3,
            initial_delay=0.5
        )
    else:
        raise TimeoutError("Gemini File API did not become ACTIVE in time.")

    final_mime = (
        upload_resp.mime_type
        if upload_resp.mime_type != "application/octet-stream"
        else mime_type
    )
    system_prompt = _load_system_prompt(db, caption)

    response = retry_sync(
        client.models.generate_content,
        model=_MODEL,
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_uri(file_uri=upload_resp.uri, mime_type=final_mime),
                    types.Part(text="Estrai la ricetta da questo media."),
                ],
            )
        ],
        config=types.GenerateContentConfig(system_instruction=system_prompt),
        max_retries=3,
        initial_delay=1.0
    )

    raw = re.sub(r"```(?:json)?\n?|\n?```", "", response.text or "").strip()
    logger.info("Gemini extraction complete, parsing JSON")
    return json.loads(raw)


def _load_image_prompt(db: Client, title: str, description: str) -> str:
    try:
        resp = (
            db.table("prompts")
            .select("content")
            .eq("key", "process_recipe_image")
            .single()
            .execute()
        )
        template: str = resp.data["content"]
        return (
            template
            .replace("{{title}}", title)
            .replace("{{description}}", description)
        )
    except Exception:
        logger.exception("Failed to load image prompt from DB, using fallback")
        return f"Crea un'immagine invitante del piatto: {title}. Descrizione: {description}."


async def generate_recipe_image(
    recipe_data: dict[str, Any],
    gemini_api_key: str,
    db: Client,
) -> Optional[bytes]:
    """Generate a recipe thumbnail image using Gemini and return raw bytes."""
    client = genai.Client(api_key=gemini_api_key)

    title = recipe_data.get("title") or ""
    description = recipe_data.get("description") or ""
    if not title:
        return None

    image_prompt = _load_image_prompt(db, title, description)
    logger.info("Generating recipe image with prompt: %s", image_prompt[:120])

    try:
        response = retry_sync(
            client.models.generate_content,
            model="gemini-3.1-flash-image",
            contents=image_prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"]
            ),
            max_retries=3,
            initial_delay=1.0
        )
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                return part.inline_data.data
    except Exception as e:
        if "not available in your country" in str(e) or "FAILED_PRECONDITION" in str(e):
            logger.warning("Gemini image generation is not available in your country (geoblocked). Using fallback thumbnail.")
        else:
            logger.warning("Failed to generate recipe image using Gemini: %s", e)
    return None
