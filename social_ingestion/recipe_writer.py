import logging
from typing import Any, Optional

from supabase import Client

from shared.embeddings import embed_text

logger = logging.getLogger(__name__)


def _normalize_tag(name: str) -> Optional[str]:
    cleaned = name.strip().lower()
    return cleaned if cleaned else None


def _build_recipe_payload(
    recipe_data: dict[str, Any],
    embedding: list[float],
    social_media_url: str,
    thumbnail_url: str,
) -> dict[str, Any]:
    return {
        "title": recipe_data.get("title"),
        "description": recipe_data.get("description"),
        "difficulty": recipe_data.get("difficulty"),
        "prep_time_minutes": recipe_data.get("prep_time_minutes"),
        "cook_time_minutes": recipe_data.get("cook_time_minutes"),
        "servings": recipe_data.get("servings"),
        "notes": recipe_data.get("notes"),
        "tips": recipe_data.get("tips"),
        "steps": recipe_data.get("steps"),
        "embedding": embedding,
        "url_social_media": social_media_url,
        "url_recipe_image": thumbnail_url,
    }


def generate_embedding(recipe_data: dict[str, Any], gemini_api_key: str) -> list[float]:
    ingredients = recipe_data.get("ingredients") or []
    tags = recipe_data.get("tags") or []
    text = (
        f"{recipe_data.get('title', '')}. "
        f"{recipe_data.get('description', '')}. "
        f"Tag: {', '.join(tags)}. "
        f"Ingredienti: {', '.join(i['name'] for i in ingredients if i.get('name'))}"
    )
    return embed_text(text, gemini_api_key)


def write_recipe(
    db: Client,
    recipe_data: dict[str, Any],
    embedding: list[float],
    social_media_url: str,
    thumbnail_url: str,
) -> str:
    """Insert recipe and related rows. Returns recipe_id."""
    payload = _build_recipe_payload(recipe_data, embedding, social_media_url, thumbnail_url)
    resp = db.table("recipes").insert(payload).execute()
    recipe_id: str = resp.data[0]["id"]
    logger.info("Recipe inserted id=%s title=%s", recipe_id, recipe_data.get("title"))

    _write_categories(db, recipe_id, recipe_data.get("categories") or [])
    _write_tags(db, recipe_id, recipe_data.get("tags") or [])
    _write_ingredients(db, recipe_id, recipe_data.get("ingredients") or [])
    return recipe_id


def _write_categories(db: Client, recipe_id: str, categories: list[str]) -> None:
    for cat_name in categories:
        if not cat_name or not isinstance(cat_name, str):
            continue
        name = cat_name.strip()
        if not name:
            continue
        cat_resp = db.table("categories").upsert({"name": name}, on_conflict="name").execute()
        if not cat_resp.data:
            logger.warning("Upsert category returned no data: %s", name)
            continue
        cat_id = cat_resp.data[0]["id"]
        db.table("recipe_categories").upsert(
            {"recipe_id": recipe_id, "category_id": cat_id},
            on_conflict="recipe_id,category_id",
        ).execute()


def _write_tags(db: Client, recipe_id: str, tags: list[str]) -> None:
    for raw in tags:
        name = _normalize_tag(raw) if raw else None
        if not name:
            continue
        tag_resp = db.table("tags").upsert({"name": name}, on_conflict="name").execute()
        if not tag_resp.data:
            continue
        tag_id = tag_resp.data[0]["id"]
        db.table("recipe_tags").upsert(
            {"recipe_id": recipe_id, "tag_id": tag_id},
            on_conflict="recipe_id,tag_id",
        ).execute()


def _write_ingredients(db: Client, recipe_id: str, ingredients: list[dict]) -> list[str]:
    ids: list[str] = []
    for idx, ing in enumerate(ingredients):
        name = (ing.get("name") or "").strip().lower()
        if not name:
            continue
        ing_resp = db.rpc("get_or_create_ingredient", {"p_name": name}).execute()
        if not ing_resp.data:
            logger.warning("get_or_create_ingredient returned no data for: %s", name)
            continue
        ing_id = ing_resp.data
        ids.append(ing_id)
        db.table("recipe_ingredients").insert({
            "recipe_id": recipe_id,
            "ingredient_id": ing_id,
            "quantity": ing.get("quantity"),
            "unit": ing.get("unit"),
            "is_optional": ing.get("is_optional", False),
            "notes": ing.get("notes"),
            "sort_order": idx,
        }).execute()
    return ids
