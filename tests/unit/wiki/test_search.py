from unittest.mock import MagicMock, patch

from gnammyWiki.wiki.search import search_wiki_pages


def _db_returning(rows):
    db = MagicMock()
    db.rpc.return_value.execute.return_value.data = rows
    return db


def test_search_passes_embedding(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    db = _db_returning([{"slug": "guanciale"}])
    with patch("wiki.search.embed_text", return_value=[0.1] * 768):
        rows = search_wiki_pages(db, "guanciale", top_k=3, page_types=["ingrediente"])
    assert rows == [{"slug": "guanciale"}]
    params = db.rpc.call_args.args[1]
    assert params["query_embedding"] == [0.1] * 768
    assert params["match_count"] == 3
    assert params["page_types"] == ["ingrediente"]


def test_search_embedding_failure_falls_back_to_keyword(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    db = _db_returning([])
    with patch("wiki.search.embed_text", side_effect=RuntimeError("timeout")):
        rows = search_wiki_pages(db, "guanciale")
    assert rows == []
    params = db.rpc.call_args.args[1]
    assert params["query_embedding"] is None
