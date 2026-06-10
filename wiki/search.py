# gnammyWiki/wiki/search.py
import logging
import os
from typing import Any, Optional

from supabase import Client

from shared.embeddings import embed_text

logger = logging.getLogger(__name__)


def search_wiki_pages(
    db: Client,
    query: str,
    top_k: int = 5,
    page_types: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Ricerca ibrida via RPC match_wiki_pages.

    Degradazione garbata (§6.4): se l'embedding della query fallisce si passa
    NULL e la RPC risponde in modalità keyword-only — mai un errore utente.
    """
    embedding: Optional[list[float]] = None
    try:
        embedding = embed_text(
            query,
            os.environ["GEMINI_API_KEY"],
            task_type="RETRIEVAL_QUERY",
        )
    except Exception:
        logger.warning("Embedding query fallito, ricerca keyword-only: %s", query)

    resp = db.rpc(
        "match_wiki_pages",
        {
            "query_text": query,
            "query_embedding": embedding,
            "match_count": top_k,
            "page_types": page_types,
        },
    ).execute()
    return resp.data or []
