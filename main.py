import logging
import os

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from wiki_builder.router import router as wiki_router
from social_ingestion.router import router as social_router

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(title="Gnammy Wiki Builder API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "http://127.0.0.1:4200",
        "https://gnammy.app"
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(wiki_router)
app.include_router(social_router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "wiki-builder"}
