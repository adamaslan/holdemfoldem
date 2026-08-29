"""Tests for cli/client.py's HTTP error mapping.

Uses httpx.MockTransport (part of httpx itself) rather than adding a new
mocking dependency for a small test file.
"""

from __future__ import annotations

import httpx
import pytest

from cli import client as client_module
from cli.client import post_analyze


_RealAsyncClient = httpx.AsyncClient  # captured before any monkeypatching


def _mock_client_returning(status_code: int, json_body):
    """Build an AsyncClient whose transport always returns the given response,
    for monkeypatching over httpx.AsyncClient inside post_analyze.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=json_body)

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
@pytest.mark.parametrize("status_code", [400, 422])
async def test_payload_validation_errors_map_to_value_error(monkeypatch, status_code):
    """400 (bad symbol/period) and 422 (pydantic validation) are genuine
    input errors — app.py must report "Invalid input" for these."""
    monkeypatch.setattr(
        client_module.httpx, "AsyncClient",
        _mock_client_returning(status_code, {"detail": "bad input"}),
    )
    with pytest.raises(ValueError, match="bad input"):
        await post_analyze("http://backend", {"symbol": ""})


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403, 404])
async def test_routing_and_auth_errors_map_to_connection_error(monkeypatch, status_code):
    """Regression: 401/403/404 are routing/auth/config problems, not input
    errors — they must NOT be reported as "Invalid input" (that was the
    original all-4xx-is-ValueError bug this narrows)."""
    monkeypatch.setattr(
        client_module.httpx, "AsyncClient",
        _mock_client_returning(status_code, {"detail": "not found"}),
    )
    with pytest.raises(ConnectionError, match="not found"):
        await post_analyze("http://backend", {"symbol": "AAPL"})


@pytest.mark.asyncio
async def test_5xx_maps_to_connection_error(monkeypatch):
    monkeypatch.setattr(
        client_module.httpx, "AsyncClient",
        _mock_client_returning(503, {"detail": "pipeline down"}),
    )
    with pytest.raises(ConnectionError, match="pipeline down"):
        await post_analyze("http://backend", {"symbol": "AAPL"})


@pytest.mark.asyncio
async def test_non_object_json_error_body_does_not_crash(monkeypatch):
    """Regression: a 4xx body that's a JSON array/scalar (not {"detail": ...})
    used to raise AttributeError from .get() instead of the documented
    ValueError/ConnectionError."""
    monkeypatch.setattr(
        client_module.httpx, "AsyncClient",
        _mock_client_returning(400, ["unexpected", "array", "body"]),
    )
    with pytest.raises(ValueError):
        await post_analyze("http://backend", {"symbol": ""})
