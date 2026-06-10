import logging

from google import genai
from google.genai import types

from shared.retry import retry_sync

logger = logging.getLogger(__name__)

EMBED_MODEL = "gemini-embedding-2"
EMBED_DIMENSIONS = 768


def embed_text(
    text: str,
    gemini_api_key: str,
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> list[float]:
    """Generate a 768-dim embedding for arbitrary text via gemini-embedding-2."""
    client = genai.Client(api_key=gemini_api_key)
    result = retry_sync(
        client.models.embed_content,
        model=EMBED_MODEL,
        contents=text,
        config=types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=EMBED_DIMENSIONS,
        ),
        max_retries=3,
        initial_delay=0.5,
    )
    return result.embeddings[0].values
