# gnammyWiki/wiki/embedder.py
import logging

from supabase import Client

from shared.embeddings import embed_text
from wiki.chunker import build_embed_text, chunk_markdown

logger = logging.getLogger(__name__)


def rechunk_and_embed(
    db: Client,
    page_id: str,
    title: str,
    content_md: str,
    gemini_api_key: str,
) -> int:
    """Rimpiazza i chunk della pagina: chunking per heading + embedding per chunk.

    Chiamato SOLO sulle pagine toccate dall'ingest (re-embed incrementale).
    Ritorna il numero di chunk scritti.
    """
    db.table("wiki_page_chunks").delete().eq("page_id", page_id).execute()

    chunks = chunk_markdown(content_md)
    if not chunks:
        return 0

    rows = []
    for chunk in chunks:
        embedding = embed_text(
            build_embed_text(title, chunk.heading_path, chunk.text),
            gemini_api_key,
            task_type="RETRIEVAL_DOCUMENT",
        )
        rows.append(
            {
                "page_id": page_id,
                "chunk_index": chunk.index,
                "heading_path": chunk.heading_path,
                "chunk_text": chunk.text,
                "embedding": embedding,
            }
        )
    db.table("wiki_page_chunks").insert(rows).execute()
    return len(rows)
