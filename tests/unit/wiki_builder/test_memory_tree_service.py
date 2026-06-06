# gnammyAssistant/tests/unit/wiki_builder/test_memory_tree_service.py
import pytest
import json
from unittest.mock import MagicMock, patch
from wiki_builder.memory_tree_service import MemoryTreeService


@pytest.fixture
def mock_supabase():
    client = MagicMock()
    # Mock chain returns for common select queries
    client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute = MagicMock()
    client.table.return_value.select.return_value.in_.return_value.execute = MagicMock()
    client.table.return_value.select.return_value.gte.return_value.execute = MagicMock()
    client.table.return_value.insert.return_value.execute = MagicMock()
    client.table.return_value.update.return_value.execute = MagicMock()
    client.table.return_value.delete.return_value.execute = MagicMock()
    return client


@pytest.fixture
def mock_genai():
    client = MagicMock()
    
    # Mock content generation
    mock_resp = MagicMock()
    mock_resp.text = json.dumps({
        "title": "Zafferano",
        "L2_summary": "Lo zafferano è una spezia pregiata dal colore giallo brillante.",
        "L1_nodes": [
            {"title": "Abbinamenti classici", "summary": "Si abbina ottimamente con risotti e frutti di mare."}
        ]
    })
    client.models.generate_content.return_value = mock_resp
    
    # Mock embedding generation
    mock_embed_resp = MagicMock()
    mock_values = MagicMock()
    mock_values.values = [0.1] * 768
    mock_embed_resp.embeddings = [mock_values]
    client.models.embed_content.return_value = mock_embed_resp
    
    return client


def test_update_topic_tree_entity_success(mock_supabase, mock_genai):
    # Setup mock data for wiki_entities
    mock_supabase.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {
        "name": "Zafferano",
        "slug": "zafferano",
        "type": "ingredient",
        "source_recipe_ids": ["recipe-uuid-123"],
        "mentions_in_sources": ["usare un pizzico di zafferano"]
    }
    
    # Setup mock data for recipes
    mock_supabase.table.return_value.select.return_value.in_.return_value.execute.return_value.data = [
        {"id": "recipe-uuid-123", "title": "Risotto alla Milanese", "description": "Risotto tipico allo zafferano."}
    ]
    
    # Setup mock data for inserts
    mock_supabase.table.return_value.insert.return_value.execute.return_value.data = [{"id": "new-node-id"}]
    # Setup mock data for check existing
    mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = None

    service = MemoryTreeService(supabase_client=mock_supabase, genai_client=mock_genai)
    success = service.update_topic_tree("zafferano", is_concept=False)
    
    assert success is True
    # Verifichiamo che sia stato cercato nella tabella corretta
    mock_supabase.table.assert_any_call("wiki_entities")
    # Verifichiamo l'inserimento del nodo L2
    mock_supabase.table.assert_any_call("wiki_tree_nodes")
    # Verifichiamo l'inserimento della giunzione con la ricetta
    mock_supabase.table.assert_any_call("wiki_node_recipes")


def test_generate_daily_global_tree_success(mock_supabase, mock_genai):
    # Setup mock recipes in the last 24h
    mock_supabase.table.return_value.select.return_value.gte.return_value.execute.return_value.data = [
        {"id": "recipe-1", "title": "Cacio e Pepe", "description": "Piatto romano tipico."}
    ]
    
    # Setup mock response for global digest
    mock_resp = MagicMock()
    mock_resp.text = json.dumps({
        "title": "Digest Giornaliero 06/06/2026",
        "summary": "Oggi sono state preparate ricette della tradizione laziale come la cacio e pepe."
    })
    mock_genai.models.generate_content.return_value = mock_resp
    
    mock_supabase.table.return_value.insert.return_value.execute.return_value.data = [{"id": "global-digest-id"}]
    
    service = MemoryTreeService(supabase_client=mock_supabase, genai_client=mock_genai)
    success = service.generate_daily_global_tree()
    
    assert success is True
    mock_supabase.table.assert_any_call("recipes")
    mock_supabase.table.assert_any_call("wiki_tree_nodes")
