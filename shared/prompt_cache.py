# GustoPedia/shared/prompt_cache.py
import time
from typing import Any, Dict, Optional


class PromptCache:
    def __init__(self, ttl_seconds: int = 300):
        self.ttl_ns = ttl_seconds * 1_000_000_000
        self._cache: Dict[str, Dict[str, Any]] = {}

    def get(self, key: str) -> Optional[str]:
        hit = self._cache.get(key)
        if hit and time.time_ns() < hit["expiry"]:
            return hit["content"]
        return None

    def set(self, key: str, content: str) -> None:
        self._cache[key] = {
            "content": content,
            "expiry": time.time_ns() + self.ttl_ns,
        }
