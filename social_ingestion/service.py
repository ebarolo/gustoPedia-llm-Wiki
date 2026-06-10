import asyncio
import logging
import os

from supabase import Client

from social_ingestion import job_manager, media_processor, recipe_writer
from social_ingestion.models import IngestJobResponse, JobStatus
from social_ingestion.recipe_extractor import extract_recipe, generate_recipe_image
from social_ingestion.scraper import scrape
from social_ingestion.url_sanitizer import sanitize_url

logger = logging.getLogger(__name__)


class SocialIngestionService:
    def __init__(self, db: Client) -> None:
        self._db = db
        self._rapid_api_key = os.environ["RAPID_API_KEY"]
        self._gemini_api_key = os.environ["GEMINI_API_KEY"]

    async def ingest_url(self, url: str) -> IngestJobResponse:
        """Full pipeline: sanitize → job → scrape → download → extract → write."""
        clean_url = sanitize_url(url)

        if job_manager.url_exists(self._db, clean_url):
            resp = (
                self._db.table("recipe_ingestion_jobs")
                .select("id, status, recipe_id")
                .eq("url", clean_url)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if resp.data:
                row = resp.data[0]
                return IngestJobResponse(
                    job_id=row["id"],
                    status=JobStatus(row["status"]),
                    recipe_id=row.get("recipe_id"),
                )

        job_id = job_manager.create_job(self._db, clean_url)
        job_manager.set_processing(self._db, job_id)
        job_manager.append_log(self._db, job_id, "info", f"Avvio elaborazione: {clean_url}")

        try:
            job_manager.append_log(self._db, job_id, "info", "Scraping media...")
            scrape_result = await scrape(clean_url, self._rapid_api_key)
            job_manager.append_log(self._db, job_id, "info", f"Media URL estratto: {scrape_result.media_url[:60]}")

            job_manager.append_log(self._db, job_id, "info", "Download e upload R2...")
            uploaded = await media_processor.download_and_upload(
                scrape_result.media_url, job_id, scrape_result.mime_type
            )
            job_manager.append_log(self._db, job_id, "info", f"R2 upload: {uploaded.public_url}")

            job_manager.append_log(self._db, job_id, "info", "Estrazione ricetta con Gemini...")
            recipe_data = await extract_recipe(
                media_data=uploaded.data,
                mime_type=uploaded.mime_type,
                caption=scrape_result.caption,
                filename=uploaded.key,
                gemini_api_key=self._gemini_api_key,
                db=self._db,
            )

            if recipe_data.get("is_recipe") is False:
                reason = recipe_data.get("error", "media non di ricette")
                job_manager.append_log(self._db, job_id, "warn", f"Non è una ricetta: {reason}")
                media_processor.delete_from_r2(uploaded.key)
                job_manager.set_error(self._db, job_id, "media non di ricette")
                return IngestJobResponse(job_id=job_id, status=JobStatus.ERROR, error="media non di ricette")

            job_manager.append_log(self._db, job_id, "info", "Generazione embedding...")
            embedding = recipe_writer.generate_embedding(recipe_data, self._gemini_api_key)

            # Generate illustrative recipe image using Gemini
            job_manager.append_log(self._db, job_id, "info", "Generazione immagine illustrativa con Gemini...")
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
                    job_manager.append_log(self._db, job_id, "info", f"Upload immagine generata su R2...")
                    thumbnail_url = media_processor.upload_bytes(
                        generated_img_bytes, thumb_key, "image/jpeg"
                    )
                    job_manager.append_log(self._db, job_id, "info", f"R2 immagine generata: {thumbnail_url}")
                except Exception as upload_exc:
                    logger.warning("Failed to upload generated image: %s", upload_exc)

            job_manager.append_log(self._db, job_id, "info", "Salvataggio ricetta...")
            recipe_id = recipe_writer.write_recipe(
                db=self._db,
                recipe_data=recipe_data,
                embedding=embedding,
                social_media_url=uploaded.public_url,
                thumbnail_url=thumbnail_url,
            )
            job_manager.set_completed(self._db, job_id, recipe_id)
            job_manager.append_log(self._db, job_id, "info", f"Completato. recipe_id={recipe_id}")

            return IngestJobResponse(job_id=job_id, status=JobStatus.COMPLETED, recipe_id=recipe_id)

        except Exception as exc:
            logger.exception("Social ingestion failed job_id=%s url=%s", job_id, clean_url)
            job_manager.append_log(self._db, job_id, "error", str(exc))
            job_manager.set_error(self._db, job_id, str(exc))
            return IngestJobResponse(job_id=job_id, status=JobStatus.ERROR, error=str(exc))

    async def ingest_batch(self, urls: list[str]) -> list[IngestJobResponse]:
        results = []
        for url in urls:
            result = await self.ingest_url(url)
            results.append(result)
        return results
