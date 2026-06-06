import asyncio
import time
import logging
from typing import Callable, TypeVar, Any, Awaitable

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def retry_async(
    func: Callable[..., Awaitable[T]],
    *args: Any,
    max_retries: int = 3,
    initial_delay: float = 0.5,
    backoff_factor: float = 2.0,
    **kwargs: Any
) -> T:
    """Retry an async function with exponential backoff.
    
    Skips retry on non-transient HTTP errors (4xx, except 429).
    """
    delay = initial_delay
    for attempt in range(1, max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            # Check for non-transient httpx status errors (4xx except 429)
            try:
                import httpx
                if isinstance(e, httpx.HTTPStatusError):
                    status = e.response.status_code
                    if 400 <= status < 500 and status != 429:
                        logger.warning("Non-transient HTTP error %d, skipping retry", status)
                        raise e
            except ImportError:
                pass

            if attempt == max_retries:
                logger.error("Async call failed after %d attempts. Exception: %s", attempt, str(e))
                raise e

            logger.warning(
                "Async call failed (attempt %d/%d), retrying in %.2fs... Exception: %s",
                attempt, max_retries, delay, str(e)
            )
            await asyncio.sleep(delay)
            delay *= backoff_factor


def retry_sync(
    func: Callable[..., T],
    *args: Any,
    max_retries: int = 3,
    initial_delay: float = 0.5,
    backoff_factor: float = 2.0,
    **kwargs: Any
) -> T:
    """Retry a synchronous function with exponential backoff.
    
    Skips retry on non-transient HTTP or API errors (4xx, except 429).
    """
    delay = initial_delay
    for attempt in range(1, max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            # Check for non-transient httpx status errors (4xx except 429)
            try:
                import httpx
                if isinstance(e, httpx.HTTPStatusError):
                    status = e.response.status_code
                    if 400 <= status < 500 and status != 429:
                        logger.warning("Non-transient HTTP error %d, skipping retry", status)
                        raise e
            except ImportError:
                pass

            # Check for non-transient Google GenAI API errors (4xx except 429)
            if type(e).__name__ == "APIError" and hasattr(e, "code"):
                code = getattr(e, "code", None)
                if isinstance(code, int) and 400 <= code < 500 and code != 429:
                    logger.warning("Non-transient Gemini API error %d, skipping retry", code)
                    raise e

            if attempt == max_retries:
                logger.error("Sync call failed after %d attempts. Exception: %s", attempt, str(e))
                raise e

            logger.warning(
                "Sync call failed (attempt %d/%d), retrying in %.2fs... Exception: %s",
                attempt, max_retries, delay, str(e)
            )
            time.sleep(delay)
            delay *= backoff_factor
