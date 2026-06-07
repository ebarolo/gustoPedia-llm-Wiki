# gnammyAssistant/wiki_builder/source_analyzer.py
import json
import logging
import re
from typing import Any, Optional

from wiki_builder.models import (
    ExtractedConcept, ExtractedEntity, SourceExtractionResult,
    EntityType, ConceptType,
)

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT_TEMPLATE = """\
Sei un esperto curatore della knowledge base culinaria di Gnammy.
Data la seguente ricetta, estrai entità e concetti culinari in italiano.

ENTITÀ: elementi nominativi specifici (ingrediente, piatto, regione, prodotto, tecnica specifica, chef).
CONCETTI: principi culinari generali (tecnica di cottura, profilo gusto, pattern dietetico, scienza alimentare, tradizione culturale, occasione).

Ricetta:
- Titolo: {title}
- Ingredienti: {ingredients}
- Categorie: {categories}
- Difficoltà: {difficulty}
- Descrizione: {description}

Regole:
- Estrai max 8 entità e max 5 concetti per ricetta.
- Ogni name deve essere in italiano corretto (es. "Parmigiano Reggiano", "mantecatura").
- summary e definition: 1-2 frasi in italiano, concise.
- mentions_in_source: citazioni brevi dal testo della ricetta fornito.
- Tipi entità validi: ingredient, dish, region, technique, product, chef, other.
- Tipi concetto validi: technique, flavor_profile, dietary_pattern, food_science, cultural, occasion, other.
- Se type non corrisponde a nessun valore valido, usa "other".

Rispondi SOLO con JSON valido, senza markdown fence, senza testo aggiuntivo:
{{
  "source_title": "...",
  "entities": [
    {{
      "name": "...",
      "type": "ingredient|dish|region|technique|product|chef|other",
      "aliases": ["..."],
      "summary": "...",
      "mentions_in_source": ["..."],
      "related_entities": ["nome entità correlata"],
      "related_concepts": ["nome concetto correlato"]
    }}
  ],
  "concepts": [
    {{
      "name": "...",
      "type": "technique|flavor_profile|dietary_pattern|food_science|cultural|occasion|other",
      "aliases": ["..."],
      "definition": "...",
      "key_characteristics": ["..."],
      "applications": ["..."],
      "mentions_in_source": ["..."],
      "related_concepts": ["..."],
      "related_entities": ["..."]
    }}
  ]
}}"""

_GENERATION_MODEL = "gemini-flash-latest"


def _coerce_entity_type(raw: str) -> str:
    valid = {e.value for e in EntityType}
    return raw if raw in valid else "other"


def _coerce_concept_type(raw: str) -> str:
    valid = {c.value for c in ConceptType}
    return raw if raw in valid else "other"


def _parse_extraction_response(raw: str, recipe_id: str) -> Optional[SourceExtractionResult]:
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM JSON for recipe_id=%s", recipe_id)
        return None

    raw_entities = data.get("entities") or []
    raw_concepts = data.get("concepts") or []

    entities: list[ExtractedEntity] = []
    for e in raw_entities:
        if not isinstance(e, dict) or not e.get("name"):
            continue
        e["type"] = _coerce_entity_type(e.get("type", "other"))
        try:
            entities.append(ExtractedEntity(**e))
        except Exception:
            logger.debug("Skipping malformed entity: %s", e)

    concepts: list[ExtractedConcept] = []
    for c in raw_concepts:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        c["type"] = _coerce_concept_type(c.get("type", "other"))
        try:
            concepts.append(ExtractedConcept(**c))
        except Exception:
            logger.debug("Skipping malformed concept: %s", c)

    return SourceExtractionResult(
        recipe_id=recipe_id,
        source_title=data.get("source_title", ""),
        entities=entities,
        concepts=concepts,
    )


class SourceAnalyzer:
    def __init__(self, genai_client: Any, supabase_client: Optional[Any] = None) -> None:
        self._client = genai_client
        self._db = supabase_client

    def _load_prompt(self, key: str) -> Optional[str]:
        if not self._db:
            return None
        try:
            resp = (
                self._db.table("prompts")
                .select("content")
                .eq("key", key)
                .single()
                .execute()
            )
            return resp.data["content"]
        except Exception as e:
            logger.warning("Failed to load prompt %s from DB, using fallback: %s", key, e)
            return None

    def analyze(self, recipe: dict[str, Any]) -> Optional[SourceExtractionResult]:
        db_prompt = self._load_prompt("wiki_extract_entities_concepts")
        if db_prompt:
            prompt = (
                db_prompt
                .replace("{{title}}", recipe.get("title", ""))
                .replace("{{ingredients}}", ", ".join(recipe.get("ingredients", [])))
                .replace("{{categories}}", ", ".join(recipe.get("categories", [])))
                .replace("{{difficulty}}", recipe.get("difficulty", "n/d"))
                .replace("{{description}}", recipe.get("description", ""))
            )
        else:
            prompt = _EXTRACTION_PROMPT_TEMPLATE.format(
                title=recipe.get("title", ""),
                ingredients=", ".join(recipe.get("ingredients", [])),
                categories=", ".join(recipe.get("categories", [])),
                difficulty=recipe.get("difficulty", "n/d"),
                description=recipe.get("description", ""),
            )
        try:
            from shared.retry import retry_sync
            response = retry_sync(
                self._client.models.generate_content,
                model=_GENERATION_MODEL,
                contents=prompt,
                max_retries=3,
                initial_delay=1.0
            )
            raw_text: str = response.text or ""
        except Exception:
            logger.exception("Gemini call failed for recipe_id=%s", recipe.get("id"))
            return None

        return _parse_extraction_response(raw_text, recipe.get("id", ""))
