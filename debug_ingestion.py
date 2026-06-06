import asyncio
import os
import sys
from dotenv import load_dotenv

# Load local environment variables from .env
load_dotenv()

from shared.supabase import get_supabase_client
from social_ingestion.service import SocialIngestionService

async def main():
    args = sys.argv[1:]
    force = False
    if "--force" in args:
        force = True
        args.remove("--force")

    if not args:
        print("Uso: ../.venv/bin/python debug_ingestion.py [--force] <social_media_url>")
        print("Esempio: ../.venv/bin/python debug_ingestion.py --force https://www.instagram.com/reel/C8_xxxxx/")
        sys.exit(1)

    url = args[0]
    db = get_supabase_client()
    service = SocialIngestionService(db=db)

    if force:
        from social_ingestion.url_sanitizer import sanitize_url
        clean_url = sanitize_url(url)
        print(f"Forzatura dell'ingestione: reset del job precedente per la URL: {clean_url}")
        try:
            db.table("recipe_ingestion_jobs").delete().eq("url", clean_url).execute()
        except Exception as delete_exc:
            print(f"Impossibile rimuovere il job precedente dal DB (non bloccante): {delete_exc}")

    print(f"--- AVVIO INGESTIONE PER LA URL: {url} ---")
    
    try:
        result = await service.ingest_url(url)
        print("\n--- RISULTATO ---")
        print(f"Status: {result.status.value}")
        if result.recipe_id:
            print(f"Recipe ID: {result.recipe_id}")
        if result.error:
            print(f"Errore riscontrato: {result.error}")
            
    except Exception as e:
        print(f"\nERRORE CRITICO DURANTE L'ESECUZIONE: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
