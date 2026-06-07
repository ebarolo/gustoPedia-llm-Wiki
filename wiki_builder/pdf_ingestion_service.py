import os
import tempfile
import logging
import json
import re
import asyncio
from typing import Dict, Any

from google import genai
from google.genai import types
from supabase import Client

from shared.retry import retry_sync
from social_ingestion import job_manager, media_processor, recipe_writer
from social_ingestion.recipe_extractor import generate_recipe_image
from wiki_builder.pdf_processor import PDFProcessor
from wiki_builder.wiki_service import WikiService

logger = logging.getLogger(__name__)

_MODEL = "gemini-3.5-flash"
_CANONICAL_CATEGORIES = [
    "Antipasti", "Primi Piatti", "Secondi Piatti", "Contorni", "Dolci",
    "Pane e Lievitati", "Pizze e Focacce", "Colazione e Merende",
    "Insalate", "Zuppe e Minestre", "Salse e Condimenti", "Bevande",
]


class PDFIngestionService:
    def __init__(self, db: Client) -> None:
        self._db = db
        self._gemini_api_key = os.environ["GEMINI_API_KEY"]

    def _load_prompt(self, key: str) -> str:
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
            logger.exception("Failed to load prompt %s from DB", key)
            raise RuntimeError(f"Required prompt '{key}' not found in database: {str(e)}") from e

    async def process_recipe_pdf(self, job_id: str, file_path: str) -> Dict[str, Any]:
        """Processes a single recipe PDF: download -> pymupdf4llm -> gemini -> save -> wiki."""
        job_manager.append_log(self._db, job_id, "info", f"Scarico PDF: {file_path}")
        
        # 1. Download PDF from Supabase Storage
        try:
            response = self._db.storage.from_("recipe-pdfs").download(file_path)
        except Exception as e:
            msg = f"Errore download PDF da Storage: {str(e)}"
            logger.exception(msg)
            job_manager.append_log(self._db, job_id, "error", msg)
            job_manager.set_error(self._db, job_id, msg)
            return {"ok": False, "error": msg}

        # 2. Extract Markdown using PyMuPDF4LLM
        job_manager.append_log(self._db, job_id, "info", "Estrazione layout ed OCR locale con PyMuPDF4LLM...")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(response)
            temp_path = tmp.name

        try:
            markdown_content = PDFProcessor.extract_markdown(temp_path, exclude_header_footer=True)
            job_manager.append_log(self._db, job_id, "info", f"PDF convertito. Dimensione testo: {len(markdown_content)} caratteri")
        except Exception as e:
            msg = f"Errore conversione PDF a Markdown: {str(e)}"
            logger.exception(msg)
            job_manager.append_log(self._db, job_id, "error", msg)
            job_manager.set_error(self._db, job_id, msg)
            return {"ok": False, "error": msg}
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        # 3. Call Gemini to extract recipe JSON from Markdown
        job_manager.append_log(self._db, job_id, "info", "Inizio estrazione della ricetta tramite Gemini...")
        system_prompt = self._load_prompt("process_recipe_pdf_system")
        system_prompt = system_prompt.replace("{{canonicalCategories}}", ", ".join(_CANONICAL_CATEGORIES))

        client = genai.Client(api_key=self._gemini_api_key)
        try:
            prompt_text = (
                f"Analizza il seguente testo estratto da un documento PDF ed estrai la ricetta strutturata.\n\n"
                f"Documento:\n{markdown_content}"
            )
            response = retry_sync(
                client.models.generate_content,
                model=_MODEL,
                contents=prompt_text,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json"
                ),
                max_retries=3,
                initial_delay=1.0
            )
            raw = re.sub(r"```(?:json)?\n?|\n?```", "", response.text or "").strip()
            recipe_data = json.loads(raw)
        except Exception as e:
            msg = f"Errore estrazione AI / parsing JSON: {str(e)}"
            logger.exception(msg)
            job_manager.append_log(self._db, job_id, "error", msg)
            job_manager.set_error(self._db, job_id, msg)
            return {"ok": False, "error": msg}

        # Validate is_recipe
        if recipe_data.get("is_recipe") is not True:
            reason = recipe_data.get("error", "il documento non contiene una ricetta riconoscibile")
            job_manager.append_log(self._db, job_id, "warn", f"Non è una ricetta: {reason}")
            job_manager.set_error(self._db, job_id, reason)
            return {"ok": False, "error": reason}

        # 4. Generate Illustrative Thumbnail Image
        job_manager.append_log(self._db, job_id, "info", "Generazione immagine di copertina...")
        thumbnail_url = ""
        generated_img_bytes = await generate_recipe_image(
            recipe_data=recipe_data,
            gemini_api_key=self._gemini_api_key,
            db=self._db
        )
        if generated_img_bytes:
            try:
                import time
                thumb_key = f"thumbnail_{job_id}_{int(time.time())}.jpg"
                job_manager.append_log(self._db, job_id, "info", "Caricamento immagine generata su R2...")
                thumbnail_url = media_processor.upload_bytes(
                    generated_img_bytes, thumb_key, "image/jpeg"
                )
                job_manager.append_log(self._db, job_id, "info", f"R2 immagine salvata: {thumbnail_url}")
            except Exception as e:
                logger.warning("Failed to upload generated thumbnail: %s", e)
                job_manager.append_log(self._db, job_id, "warn", f"Errore upload copertina (non-fatale): {str(e)}")

        # 5. Insert recipe and categories/tags/ingredients
        try:
            job_manager.append_log(self._db, job_id, "info", "Generazione embedding semantico...")
            embedding = recipe_writer.generate_embedding(recipe_data, self._gemini_api_key)

            job_manager.append_log(self._db, job_id, "info", "Salvataggio ricetta nel database...")
            recipe_id = recipe_writer.write_recipe(
                db=self._db,
                recipe_data=recipe_data,
                embedding=embedding,
                social_media_url=file_path,  # Use file_path as social_media_url reference
                thumbnail_url=thumbnail_url,
            )
            job_manager.set_completed(self._db, job_id, recipe_id)
            job_manager.append_log(self._db, job_id, "info", f"Completato! ricetta_id={recipe_id}")

            # Trigger wiki updates locally
            asyncio.create_task(self._trigger_wiki(recipe_id))
            return {"ok": True, "recipe_id": recipe_id}
        except Exception as e:
            msg = f"Errore salvataggio ricetta nel DB: {str(e)}"
            logger.exception(msg)
            job_manager.append_log(self._db, job_id, "error", msg)
            job_manager.set_error(self._db, job_id, msg)
            return {"ok": False, "error": msg}

    async def process_book_pdf(self, job_id: str, file_path: str) -> Dict[str, Any]:
        """Processes cookbook PDF: download -> get TOC -> gemini index -> insert child jobs."""
        job_manager.append_log(self._db, job_id, "info", f"Analisi libro di ricette: {file_path}")
        
        # 1. Download PDF
        try:
            response = self._db.storage.from_("recipe-pdfs").download(file_path)
        except Exception as e:
            msg = f"Errore download libro da Storage: {str(e)}"
            logger.exception(msg)
            job_manager.set_error(self._db, job_id, msg)
            return {"ok": False, "error": msg}

        # 2. Extract TOC and page count using PyMuPDF
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(response)
            temp_path = tmp.name

        try:
            toc, page_count = PDFProcessor.get_toc_and_page_count(temp_path)
            job_manager.append_log(self._db, job_id, "info", f"TOC estratto ({len(toc)} elementi), pagine totali: {page_count}")
        except Exception as e:
            msg = f"Errore lettura metadati PDF: {str(e)}"
            logger.exception(msg)
            job_manager.set_error(self._db, job_id, msg)
            return {"ok": False, "error": msg}
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        # 3. Ask Gemini to identify chapters based on TOC
        job_manager.append_log(self._db, job_id, "info", "Identificazione capitoli tramite AI...")
        index_prompt = self._load_prompt("process_book_pdf_index")
        
        client = genai.Client(api_key=self._gemini_api_key)
        try:
            prompt_text = (
                f"Ecco l'indice TOC (Table Of Contents) estratto dal PDF:\n{json.dumps(toc, indent=2)}\n\n"
                f"Il libro ha {page_count} pagine totali. Genera l'indice strutturato dei capitoli che contengono ricette."
            )
            response = retry_sync(
                client.models.generate_content,
                model=_MODEL,
                contents=prompt_text,
                config=types.GenerateContentConfig(
                    system_instruction=index_prompt,
                    response_mime_type="application/json"
                ),
                max_retries=3,
                initial_delay=1.0
            )
            raw = re.sub(r"```(?:json)?\n?|\n?```", "", response.text or "").strip()
            index_data = json.loads(raw)
            chapters = index_data.get("chapters") or []
        except Exception as e:
            msg = f"Errore elaborazione indice capitoli: {str(e)}"
            logger.exception(msg)
            job_manager.set_error(self._db, job_id, msg)
            return {"ok": False, "error": msg}

        if not chapters:
            msg = "Nessun capitolo trovato o estratto dal libro."
            job_manager.set_error(self._db, job_id, msg)
            return {"ok": False, "error": msg}

        # 4. Save book metadata
        chapters_meta = [
            {
                "index": i,
                "title": ch["title"],
                "page_start": ch["page_start"],
                "page_end": ch["page_end"],
                "status": "pending",
                "child_job_id": None,
                "recipes_extracted": 0,
                "error_message": None,
            }
            for i, ch in enumerate(chapters)
        ]

        book_metadata = {
            "gemini_file_uri": "local_pymupdf4llm",  # Marker showing we process locally
            "gemini_cache_name": None,
            "phase": "extracting_chapters",
            "total_chapters": len(chapters),
            "chapters": chapters_meta,
            "total_recipes": 0,
            "extracted": 0,
            "failed_chapters": 0,
        }

        self._db.table("recipe_ingestion_jobs").update({
            "book_metadata": book_metadata
        }).eq("id", job_id).execute()

        # 5. Insert child jobs for each chapter
        job_manager.append_log(self._db, job_id, "info", f"Inserimento di {len(chapters)} sotto-job per ciascun capitolo...")
        for i in range(len(chapters)):
            child_job_resp = (
                self._db.table("recipe_ingestion_jobs")
                .insert({
                    "url": f"pdf-book-chapter://{job_id}/{i}",
                    "source_type": "book_chapter",
                    "file_path": file_path,
                    "status": "pending",
                    "parent_job_id": job_id,
                })
                .execute()
            )
            if child_job_resp.data:
                chapters_meta[i]["child_job_id"] = child_job_resp.data[0]["id"]

        # Update metadata with child job ids
        self._db.table("recipe_ingestion_jobs").update({
            "book_metadata": book_metadata
        }).eq("id", job_id).execute()

        job_manager.append_log(self._db, job_id, "info", "Fase 1 completata. Sotto-job generati con successo.")
        return {"ok": True, "chapters": len(chapters)}

    async def process_book_chapter(self, job_id: str, parent_job_id: str, chapter_index: int, file_path: str) -> Dict[str, Any]:
        """Processes a single chapter PDF: download -> pymupdf4llm range -> gemini -> save -> rpc."""
        # 1. Load parent job to get chapter metadata
        try:
            parent_resp = self._db.table("recipe_ingestion_jobs").select("book_metadata").eq("id", parent_job_id).single().execute()
            meta = parent_resp.data["book_metadata"]
            chapter = meta["chapters"][chapter_index]
        except Exception as e:
            msg = f"Errore caricamento metadati del genitore: {str(e)}"
            logger.exception(msg)
            job_manager.set_error(self._db, job_id, msg)
            return {"ok": False, "error": msg}

        page_start = chapter["page_start"]
        page_end = chapter["page_end"]
        job_manager.append_log(self._db, job_id, "info", f"Capitolo: \"{chapter['title']}\" (pagg. {page_start}-{page_end})")

        # 2. Download PDF
        try:
            response = self._db.storage.from_("recipe-pdfs").download(file_path)
        except Exception as e:
            msg = f"Errore download PDF per capitolo: {str(e)}"
            logger.exception(msg)
            job_manager.set_error(self._db, job_id, msg)
            self._db.rpc("complete_book_chapter", {
                "p_parent_id": parent_job_id,
                "p_chapter_index": chapter_index,
                "p_status": "error",
                "p_recipes_count": 0,
                "p_error_msg": msg,
            }).execute()
            return {"ok": False, "error": msg}

        # 3. Extract Markdown for specific pages
        job_manager.append_log(self._db, job_id, "info", f"Estrazione layout pagine {page_start}-{page_end} con PyMuPDF4LLM...")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(response)
            temp_path = tmp.name

        try:
            # pages are 0-based
            page_list = list(range(page_start - 1, page_end))
            markdown_content = PDFProcessor.extract_markdown(temp_path, pages=page_list, exclude_header_footer=True)
            job_manager.append_log(self._db, job_id, "info", f"Testo estratto: {len(markdown_content)} caratteri")
        except Exception as e:
            msg = f"Errore estrazione pagine PDF: {str(e)}"
            logger.exception(msg)
            job_manager.set_error(self._db, job_id, msg)
            self._db.rpc("complete_book_chapter", {
                "p_parent_id": parent_job_id,
                "p_chapter_index": chapter_index,
                "p_status": "error",
                "p_recipes_count": 0,
                "p_error_msg": msg,
            }).execute()
            return {"ok": False, "error": msg}
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        # 4. Ask Gemini to extract all recipes in the chapter
        job_manager.append_log(self._db, job_id, "info", "Estrazione ricette del capitolo tramite Gemini...")
        section_prompt = self._load_prompt("process_book_pdf_section")
        section_prompt = (
            section_prompt
            .replace("{{page_start}}", str(page_start))
            .replace("{{page_end}}", str(page_end))
            .replace("{{canonicalCategories}}", ", ".join(_CANONICAL_CATEGORIES))
        )

        client = genai.Client(api_key=self._gemini_api_key)
        try:
            prompt_text = (
                f"Estrai tutte le ricette presenti nelle seguenti pagine del capitolo:\n\n{markdown_content}"
            )
            response = retry_sync(
                client.models.generate_content,
                model=_MODEL,
                contents=prompt_text,
                config=types.GenerateContentConfig(
                    system_instruction=section_prompt,
                    response_mime_type="application/json"
                ),
                max_retries=3,
                initial_delay=1.0
            )
            raw = re.sub(r"```(?:json)?\n?|\n?```", "", response.text or "").strip()
            recipes_data = json.loads(raw)
            extracted_recipes = recipes_data.get("recipes") or []
        except Exception as e:
            msg = f"Errore parsing ricette del capitolo: {str(e)}"
            logger.exception(msg)
            job_manager.set_error(self._db, job_id, msg)
            self._db.rpc("complete_book_chapter", {
                "p_parent_id": parent_job_id,
                "p_chapter_index": chapter_index,
                "p_status": "error",
                "p_recipes_count": 0,
                "p_error_msg": msg,
            }).execute()
            return {"ok": False, "error": msg}

        job_manager.append_log(self._db, job_id, "info", f"Trovate {len(extracted_recipes)} ricette. Salvataggio in corso...")
        recipes_inserted = 0
        for recipe in extracted_recipes:
            if not recipe.get("title"):
                continue
            try:
                # Embedding
                embedding = recipe_writer.generate_embedding(recipe, self._gemini_api_key)
                
                # Thumbnail
                thumbnail_url = ""
                generated_img_bytes = await generate_recipe_image(
                    recipe_data=recipe,
                    gemini_api_key=self._gemini_api_key,
                    db=self._db
                )
                if generated_img_bytes:
                    try:
                        import time
                        thumb_key = f"thumbnail_book_{job_id}_{int(time.time())}_{recipes_inserted}.jpg"
                        thumbnail_url = media_processor.upload_bytes(generated_img_bytes, thumb_key, "image/jpeg")
                    except Exception as e:
                        logger.warning("Failed to upload chapter recipe image: %s", e)

                recipe_id = recipe_writer.write_recipe(
                    db=self._db,
                    recipe_data=recipe,
                    embedding=embedding,
                    social_media_url=file_path,
                    thumbnail_url=thumbnail_url
                )
                recipes_inserted += 1
                asyncio.create_task(self._trigger_wiki(recipe_id))
            except Exception as e:
                logger.exception("Failed to insert book chapter recipe title=%s", recipe.get("title"))
                job_manager.append_log(self._db, job_id, "warn", f"Errore ricetta \"{recipe.get('title')}\": {str(e)}")

        # 5. Mark job completed
        job_manager.set_completed(self._db, job_id, "") # Empty recipe_id as this yields multiple recipes
        job_manager.append_log(self._db, job_id, "info", f"Completato! Ricette inserite: {recipes_inserted}")

        # Notify parent job atomically
        self._db.rpc("complete_book_chapter", {
            "p_parent_id": parent_job_id,
            "p_chapter_index": chapter_index,
            "p_status": "completed",
            "p_recipes_count": recipes_inserted,
            "p_error_msg": None,
        }).execute()

        return {"ok": True, "recipes_inserted": recipes_inserted}

    async def _trigger_wiki(self, recipe_id: str) -> None:
        try:
            svc = WikiService(supabase_client=self._db, gemini_api_key=self._gemini_api_key)
            svc.ingest_recipe(recipe_id)
            logger.info("Wiki ingestion triggered locally for recipe_id=%s", recipe_id)
        except Exception:
            logger.exception("Wiki ingestion failed locally for recipe_id=%s (non-blocking)", recipe_id)
