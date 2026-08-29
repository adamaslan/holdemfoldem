"""Tests for cli/client.py's HTTP error mapping.

Uses httpx.MockTransport (part of httpx itself) rather than adding a new
mocking dependency for a two-test file.
"""

from __future__ import annotations

import httpx
import pytest

from cli import client as client_module
from cli.client import post_analyze


_RealAsyncClient = httpx.AsyncClient  # captured before any monkeypatching


def _mock_client_returning(status_code: int, detail: str):
    """Build an AsyncClient whose transport always returns the given response,
    for monkeypatching over httpx.AsyncClient inside post_analyze.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"detail": detail})

    transport = httpx.MockTransport(handler)

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            self._client = _RealAsyncClient(transport=transport)

        async def __aenter__(self):
            return self._client

        async def __aexit__(self, *exc):
            await self._client.aclose()

    return _FakeAsyncClient


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 422, 404])
async def test_4xx_maps_to_value_error(monkeypatch, status_code):
    """Regression: only 400 used to map to ValueError; 422 (pydantic
    validation) and other 4xx codes fell through to ConnectionError, which
    app.py reports as the misleading "Backend unreachable"."""
    monkeypatch.setattr(
        client_module.httpx, "AsyncClient", _mock_client_returning(status_code, "bad input")
    )
    with pytest.raises(ValueError, match="bad input"):
        await post_analyze("http://backend", {"symbol": ""})


@pytest.mark.asyncio
async def test_5xx_maps_to_connection_error(monkeypatch):
    monkeypatch.setattr(
        client_module.httpx, "AsyncClient", _mock_client_returning(503, "pipeline down")
    )
    with pytest.raises(ConnectionError, match="pipeline down"):
        await post_analyze("http://backend", {"symbol": "AAPL"})
