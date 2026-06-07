import os
import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from wiki_builder.pdf_ingestion_service import PDFIngestionService

@pytest.fixture(autouse=True)
def mock_env():
    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-api-key"}):
        yield

@pytest.fixture
def mock_db():
    client = MagicMock()
    
    # Mock storage download
    mock_storage = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.download.return_value = b"%PDF-1.4 mock content"
    mock_storage.from_.return_value = mock_bucket
    client.storage = mock_storage
    
    # Mock table query chain
    mock_table = MagicMock()
    mock_table.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "book_metadata": {
            "chapters": [
                {
                    "title": "Chapter 1",
                    "page_start": 2,
                    "page_end": 5,
                    "status": "pending"
                }
            ]
        }
    }
    mock_table.insert.return_value.execute.return_value.data = [{"id": "child-job-123"}]
    mock_table.update.return_value.execute.return_value.data = [{"id": "parent-job-123"}]
    client.table.return_value = mock_table
    
    # Mock RPC execution
    mock_rpc = MagicMock()
    mock_rpc.execute.return_value.data = None
    client.rpc.return_value = mock_rpc
    
    return client

@pytest.mark.asyncio
@patch("wiki_builder.pdf_ingestion_service.PDFProcessor")
@patch("wiki_builder.pdf_ingestion_service.genai.Client")
@patch("wiki_builder.pdf_ingestion_service.generate_recipe_image")
@patch("wiki_builder.pdf_ingestion_service.media_processor.upload_bytes")
@patch("wiki_builder.pdf_ingestion_service.recipe_writer.generate_embedding")
@patch("wiki_builder.pdf_ingestion_service.recipe_writer.write_recipe")
@patch("wiki_builder.pdf_ingestion_service.WikiService")
@patch("wiki_builder.pdf_ingestion_service.job_manager")
async def test_process_recipe_pdf_success(
    mock_job_manager,
    mock_wiki_service,
    mock_write_recipe,
    mock_gen_embedding,
    mock_r2_upload,
    mock_gen_img,
    mock_genai_client,
    mock_pdf_processor,
    mock_db
):
    # Setup mocks
    mock_pdf_processor.extract_markdown.return_value = "Mock Markdown Recipe content"
    
    # Gemini AI mock response
    mock_ai = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "is_recipe": True,
        "title": "Torta Margherita",
        "description": "Una torta soffice e semplice.",
        "ingredients": [{"name": "farina", "quantity": "200", "unit": "g"}]
    })
    mock_ai.models.generate_content.return_value = mock_response
    mock_genai_client.return_value = mock_ai
    
    mock_gen_img.return_value = b"fake-image-bytes"
    mock_r2_upload.return_value = "https://r2.example.com/thumb.jpg"
    mock_gen_embedding.return_value = [0.1] * 768
    mock_write_recipe.return_value = "new-recipe-uuid"
    
    service = PDFIngestionService(db=mock_db)
    
    # Mock load prompt to avoid DB select for prompts
    service._load_prompt = MagicMock(return_value="System prompt text")
    
    result = await service.process_recipe_pdf("job-123", "folder/recipe.pdf")
    
    assert result == {"ok": True, "recipe_id": "new-recipe-uuid"}
    mock_pdf_processor.extract_markdown.assert_called_once()
    mock_write_recipe.assert_called_once()
    mock_job_manager.set_completed.assert_called_once_with(mock_db, "job-123", "new-recipe-uuid")


@pytest.mark.asyncio
@patch("wiki_builder.pdf_ingestion_service.PDFProcessor")
@patch("wiki_builder.pdf_ingestion_service.genai.Client")
@patch("wiki_builder.pdf_ingestion_service.job_manager")
async def test_process_book_pdf_success(
    mock_job_manager,
    mock_genai_client,
    mock_pdf_processor,
    mock_db
):
    # Setup mocks
    mock_pdf_processor.get_toc_and_page_count.return_value = (
        [[1, "Chapter 1", 2], [1, "Chapter 2", 6]], 10
    )
    
    mock_ai = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "chapters": [
            {"title": "Chapter 1", "page_start": 2, "page_end": 5},
            {"title": "Chapter 2", "page_start": 6, "page_end": 10}
        ]
    })
    mock_ai.models.generate_content.return_value = mock_response
    mock_genai_client.return_value = mock_ai
    
    service = PDFIngestionService(db=mock_db)
    service._load_prompt = MagicMock(return_value="Index prompt text")
    
    result = await service.process_book_pdf("job-parent", "folder/book.pdf")
    
    assert result == {"ok": True, "chapters": 2}
    mock_pdf_processor.get_toc_and_page_count.assert_called_once()
    mock_db.table.assert_called_with("recipe_ingestion_jobs")


@pytest.mark.asyncio
@patch("wiki_builder.pdf_ingestion_service.PDFProcessor")
@patch("wiki_builder.pdf_ingestion_service.genai.Client")
@patch("wiki_builder.pdf_ingestion_service.generate_recipe_image")
@patch("wiki_builder.pdf_ingestion_service.media_processor.upload_bytes")
@patch("wiki_builder.pdf_ingestion_service.recipe_writer.generate_embedding")
@patch("wiki_builder.pdf_ingestion_service.recipe_writer.write_recipe")
@patch("wiki_builder.pdf_ingestion_service.WikiService")
@patch("wiki_builder.pdf_ingestion_service.job_manager")
async def test_process_book_chapter_success(
    mock_job_manager,
    mock_wiki_service,
    mock_write_recipe,
    mock_gen_embedding,
    mock_r2_upload,
    mock_gen_img,
    mock_genai_client,
    mock_pdf_processor,
    mock_db
):
    # Setup mocks
    mock_pdf_processor.extract_markdown.return_value = "Chapter recipe content"
    
    mock_ai = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "recipes": [
            {
                "title": "Bruschetta",
                "description": "Bruschetta rustica",
                "ingredients": []
            }
        ]
    })
    mock_ai.models.generate_content.return_value = mock_response
    mock_genai_client.return_value = mock_ai
    
    mock_gen_img.return_value = None  # No thumbnail generated
    mock_gen_embedding.return_value = [0.1] * 768
    mock_write_recipe.return_value = "recipe-uuid-1"
    
    service = PDFIngestionService(db=mock_db)
    service._load_prompt = MagicMock(return_value="Section prompt template")
    
    result = await service.process_book_chapter("job-child", "job-parent", 0, "folder/book.pdf")
    
    assert result == {"ok": True, "recipes_inserted": 1}
    mock_pdf_processor.extract_markdown.assert_called_once()
    mock_db.rpc.assert_any_call("complete_book_chapter", {
        "p_parent_id": "job-parent",
        "p_chapter_index": 0,
        "p_status": "completed",
        "p_recipes_count": 1,
        "p_error_msg": None,
    })
