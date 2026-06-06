import pytest
import httpx
from unittest.mock import MagicMock, AsyncMock
from shared.retry import retry_async, retry_sync


class MockAPIError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


def test_retry_sync_success_first_attempt():
    func = MagicMock(return_value="success")
    result = retry_sync(func, max_retries=3, initial_delay=0.01)
    assert result == "success"
    assert func.call_count == 1


def test_retry_sync_success_on_retry():
    func = MagicMock(side_effect=[ValueError("transient error"), "success"])
    result = retry_sync(func, max_retries=3, initial_delay=0.01)
    assert result == "success"
    assert func.call_count == 2


def test_retry_sync_fails_after_max_retries():
    func = MagicMock(side_effect=ValueError("persistent error"))
    with pytest.raises(ValueError, match="persistent error"):
        retry_sync(func, max_retries=3, initial_delay=0.01)
    assert func.call_count == 3


def test_retry_sync_non_transient_http_error():
    req = httpx.Request("GET", "https://example.com")
    resp = httpx.Response(404, request=req)
    func = MagicMock(side_effect=httpx.HTTPStatusError("404 Error", request=req, response=resp))
    
    with pytest.raises(httpx.HTTPStatusError):
        retry_sync(func, max_retries=3, initial_delay=0.01)
    assert func.call_count == 1


def test_retry_sync_transient_http_error():
    req = httpx.Request("GET", "https://example.com")
    resp = httpx.Response(429, request=req)
    func = MagicMock(side_effect=[
        httpx.HTTPStatusError("429 Error", request=req, response=resp),
        "success"
    ])
    result = retry_sync(func, max_retries=3, initial_delay=0.01)
    assert result == "success"
    assert func.call_count == 2


def test_retry_sync_non_transient_api_error():
    func = MagicMock(side_effect=MockAPIError(400, "Bad Request"))
    MockAPIError.__name__ = "APIError"
    
    with pytest.raises(MockAPIError):
        retry_sync(func, max_retries=3, initial_delay=0.01)
    assert func.call_count == 1


@pytest.mark.asyncio
async def test_retry_async_success_first_attempt():
    func = AsyncMock(return_value="success")
    result = await retry_async(func, max_retries=3, initial_delay=0.01)
    assert result == "success"
    assert func.call_count == 1


@pytest.mark.asyncio
async def test_retry_async_success_on_retry():
    func = AsyncMock(side_effect=[ValueError("transient"), "success"])
    result = await retry_async(func, max_retries=3, initial_delay=0.01)
    assert result == "success"
    assert func.call_count == 2


@pytest.mark.asyncio
async def test_retry_async_fails_after_max_retries():
    func = AsyncMock(side_effect=ValueError("persistent"))
    with pytest.raises(ValueError, match="persistent"):
        await retry_async(func, max_retries=3, initial_delay=0.01)
    assert func.call_count == 3
