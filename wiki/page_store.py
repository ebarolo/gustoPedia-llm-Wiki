# gnammyWiki/wiki/page_store.py
import logging
from typing import Any, Optional

from supabase import Client

logger = logging.getLogger(__name__)


def fetch_index(db: Client) -> list[dict[str, Any]]:
    resp = (
        db.table("wiki_pages")
        .select("slug, title, page_type, summary")
        .order("page_type")
        .order("title")
        .execute()
    )
    return resp.data or []


def format_index(index_rows: list[dict[str, Any]]) -> str:
    """Indice testuale per i prompt: slug | tipo | titolo | sintesi."""
    if not index_rows:
        return "(wiki vuota: nessuna pagina ancora)"
    return "\n".join(
        f"{r['slug']} | {r['page_type']} | {r['title']} | {r['summary']}"
        for r in index_rows
    )


def fetch_pages_by_slugs(db: Client, slugs: list[str]) -> list[dict[str, Any]]:
    if not slugs:
        return []
    resp = db.table("wiki_pages").select("*").in_("slug", slugs).execute()
    return resp.data or []


def _resolve_ingredient_id(db: Client, slug: str, title: str) -> Optional[str]:
    """Aggancia la pagina ingrediente alla riga ingredients per nome o alias."""
    candidates = {title.strip().lower(), slug.replace("-", " ")}
    for name in candidates:
        resp = db.table("ingredients").select("id").eq("name", name).limit(1).execute()
        if resp.data:
            return resp.data[0]["id"]
    for name in candidates:
        resp = (
            db.table("ingredients")
            .select("id")
            .contains("aliases", [name])
            .limit(1)
            .execute()
        )
        if resp.data:
            return resp.data[0]["id"]
    return None


def _resolve_tag_id(db: Client, slug: str, title: str) -> Optional[str]:
    for name in (title.strip().lower(), slug.replace("-", " ")):
        resp = db.table("tags").select("id").eq("name", name).limit(1).execute()
        if resp.data:
            return resp.data[0]["id"]
    return None


def upsert_page(
    db: Client,
    *,
    slug: str,
    title: str,
    page_type: str,
    summary: str,
    content_md: str,
    recipe_id: Optional[str],
    existing: Optional[dict[str, Any]] = None,
) -> str:
    """Crea o rimpiazza una pagina (version++). Ritorna l'id pagina."""
    if existing:
        source_ids = list(existing.get("source_recipe_ids") or [])
        if recipe_id and recipe_id not in source_ids:
            source_ids.append(recipe_id)
        db.table("wiki_pages").update(
            {
                "title": title,
                "summary": summary,
                "content_md": content_md,
                "source_recipe_ids": source_ids,
                "version": (existing.get("version") or 1) + 1,
            }
        ).eq("id", existing["id"]).execute()
        return existing["id"]

    payload: dict[str, Any] = {
        "slug": slug,
        "title": title,
        "page_type": page_type,
        "summary": summary,
        "content_md": content_md,
        "source_recipe_ids": [recipe_id] if recipe_id else [],
    }
    if page_type == "ingrediente":
        payload["ingredient_id"] = _resolve_ingredient_id(db, slug, title)
    elif page_type in ("tecnica", "regione"):
        payload["tag_id"] = _resolve_tag_id(db, slug, title)

    resp = db.table("wiki_pages").insert(payload).execute()
    return resp.data[0]["id"]


def replace_links(db: Client, from_page_id: str, to_page_ids: list[str]) -> None:
    db.table("wiki_links").delete().eq("from_page", from_page_id).execute()
    rows = [
        {"from_page": from_page_id, "to_page": to_id}
        for to_id in to_page_ids
        if to_id != from_page_id
    ]
    if rows:
        db.table("wiki_links").upsert(rows, on_conflict="from_page,to_page").execute()


def slug_to_id_map(db: Client, slugs: list[str]) -> dict[str, str]:
    if not slugs:
        return {}
    resp = db.table("wiki_pages").select("id, slug").in_("slug", slugs).execute()
    return {r["slug"]: r["id"] for r in (resp.data or [])}


def insert_log(
    db: Client,
    op: str,
    ref_label: str,
    pages_touched: list[str],
    detail: dict[str, Any],
) -> None:
    db.table("wiki_log").insert(
        {
            "op": op,
            "ref_label": ref_label,
            "pages_touched": pages_touched,
            "detail": detail,
        }
    ).execute()
