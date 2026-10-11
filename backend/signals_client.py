"""Client for signals-app's ``/v1`` thesis API (the reverse direction).

holdem → signals: ``POST /api/thesis`` pairs a holdem verdict with the
signals-app dip-timing study for the same ticker, so a single call answers
"what's the verdict, and historically when is the best day to buy this dip?".

Configured by ``SIGNALS_API_URL`` (e.g. ``http://localhost:8000``) and the
optional ``SIGNALS_API_KEY`` shared secret that signals-app's ``/v1`` checks.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

SIGNALS_API_URL_ENV = "SIGNALS_API_URL"
SIGNALS_API_KEY_ENV = "SIGNALS_API_KEY"
SIGNALS_TIMEOUT_SECONDS = 60.0


class SignalsUnavailableError(RuntimeError):
    """signals-app is not configured or did not answer."""


def signals_base_url() -> str | None:
    """Configured signals-app base URL without a trailing slash, or None."""
    raw = os.getenv(SIGNALS_API_URL_ENV, "").strip()
    return raw.rstrip("/") or None


async def _post_signals(path: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST ``body`` to signals-app ``path`` and return the JSON payload."""
    base = signals_base_url()
    if base is None:
        raise SignalsUnavailableError(f"{SIGNALS_API_URL_ENV} is not set")
    headers = {}
    if key := os.getenv(SIGNALS_API_KEY_ENV):
        headers["X-API-Key"] = key
    try:
        async with httpx.AsyncClient(timeout=SIGNALS_TIMEOUT_SECONDS) as client:
            resp = await client.post(f"{base}{path}", json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise SignalsUnavailableError(f"signals-app request failed: {exc}") from exc
    if resp.status_code != httpx.codes.OK:
        raise SignalsUnavailableError(f"signals-app returned {resp.status_code}: {resp.text[:200]}")
    return resp.json()


async def fetch_swing_grid(
    symbol: str, *, period: str = "5y", params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Run signals-app's ``swing_grid`` chain op for one symbol.

    Returns the symbol's ``swing`` row (best entry x exit combos), or raises
    when signals-app dropped the symbol (no data, no robust combo).

    Raises:
        SignalsUnavailableError: URL unset, transport failure, non-200, or dropped symbol.
    """
    steps = [
        {"op": "symbols", "params": {"symbols": [symbol]}},
        {"op": "swing_grid", "params": {**(params or {}), "period": period}},
    ]
    payload = await _post_signals("/v1/chains/run", {"steps": steps})
    wanted = symbol.upper()
    for row in payload.get("rows", []):
        if row.get("symbol") == wanted and "swing" in row:
            return row["swing"]
    dropped = payload["steps"][-1].get("dropped", {})
    raise SignalsUnavailableError(dropped.get(wanted, "swing grid returned no result"))


async def fetch_dip_study(
    symbol: str, *, period: str = "5y", params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Run signals-app's dip study for one symbol.

    Raises:
        SignalsUnavailableError: URL unset, transport failure, or non-200.
    """
    payload = await _post_signals(
        "/v1/studies/dip", {"symbols": [symbol], "period": period, "params": params or {}}
    )
    if payload.get("failed"):
        raise SignalsUnavailableError(payload["failed"][0].get("error", "dip study failed"))
    return payload["ok"][0]
