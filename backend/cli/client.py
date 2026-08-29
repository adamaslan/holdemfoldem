"""HTTP transport for the CLI's --remote path.

Kept separate from app.py so the MCP server (docs/cli-and-mcp-guide.md §4)
could reuse it if it ever needs the same "POST /api/analyze, translate
network/HTTP errors" behavior — though the MCP server currently has its own
thin copy tuned for MCP error surfaces rather than CLI exit codes.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_BACKEND_URL = "http://localhost:8001"
REQUEST_TIMEOUT_SECONDS = 60.0


def default_backend_url() -> str:
    """Resolve the backend URL from HOLDFOLD_BACKEND_URL, else localhost:8001."""
    return os.getenv("HOLDFOLD_BACKEND_URL", DEFAULT_BACKEND_URL)


async def post_analyze(base_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST a request to a running backend's /api/analyze.

    Args:
        base_url: e.g. http://localhost:8001 or a Cloud Run URL.
        payload: Raw dict matching AnalyzeRequest fields.

    Returns:
        The verdict as a plain dict.

    Raises:
        ValueError: On a 400-class response (bad input).
        ConnectionError: If the backend is unreachable or returns 5xx.
    """
    url = f"{base_url.rstrip('/')}/api/analyze"
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload)
    except httpx.RequestError as e:
        raise ConnectionError(f"Could not reach {url}: {e}") from e

    if response.status_code in (400, 422):
        # 400 (bad symbol/period) and 422 (FastAPI/pydantic payload
        # validation) are genuine input errors — map to ValueError so app.py
        # reports "Invalid input" rather than the misleading "Backend
        # unreachable". Other 4xx (401/403/404) are routing/auth/config
        # problems, not something the user's input caused, so those fall
        # through to ConnectionError below alongside 5xx.
        detail = _extract_detail(response)
        raise ValueError(detail)
    if response.status_code >= 400:
        detail = _extract_detail(response)
        raise ConnectionError(f"Backend returned {response.status_code}: {detail}")

    return response.json()


async def get_health(base_url: str) -> dict[str, Any]:
    """GET a running backend's /health.

    Raises:
        ConnectionError: If the backend is unreachable.
    """
    url = f"{base_url.rstrip('/')}/health"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
    except httpx.RequestError as e:
        raise ConnectionError(f"Could not reach {url}: {e}") from e
    except httpx.HTTPStatusError as e:
        raise ConnectionError(f"Backend returned {e.response.status_code}") from e


def _extract_detail(response: httpx.Response) -> str:
    """Pull FastAPI's {"detail": "..."} out of an error response, else raw text.

    Guards against a non-object JSON body (an array or scalar) — .get() on
    those would raise AttributeError instead of the caller's documented
    ValueError/ConnectionError.
    """
    try:
        body = response.json()
    except ValueError:
        return response.text
    if isinstance(body, dict):
        return str(body.get("detail", response.text))
    return str(body)
