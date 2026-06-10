# gnammyWiki/wiki/prompts.py
import logging

from supabase import Client

from shared.prompt_cache import PromptCache

logger = logging.getLogger(__name__)

_cache = PromptCache(ttl_seconds=300)


def load_prompt(db: Client, key: str, params: dict[str, str]) -> str:
    """Carica un prompt dalla tabella prompts (cache 5 min) e interpola {{param}}.

    Nessun fallback inline: un prompt wiki degradato produce pagine spazzatura,
    meglio far fallire il job e riprovare al prossimo kick.
    """
    template = _cache.get(key)
    if template is None:
        resp = db.table("prompts").select("content").eq("key", key).single().execute()
        template = resp.data["content"]
        _cache.set(key, template)
    for name, value in params.items():
        template = template.replace("{{" + name + "}}", value)
    return template
