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


async def fetch_dip_study(
    symbol: str, *, period: str = "5y", params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Run signals-app's dip study for one symbol.

    Raises:
        SignalsUnavailableError: URL unset, transport failure, or non-200.
    """
    base = signals_base_url()
    if base is None:
        raise SignalsUnavailableError(f"{SIGNALS_API_URL_ENV} is not set")
    headers = {}
    if key := os.getenv(SIGNALS_API_KEY_ENV):
        headers["X-API-Key"] = key
    body = {"symbols": [symbol], "period": period, "params": params or {}}
    try:
        async with httpx.AsyncClient(timeout=SIGNALS_TIMEOUT_SECONDS) as client:
            resp = await client.post(f"{base}/v1/studies/dip", json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise SignalsUnavailableError(f"signals-app request failed: {exc}") from exc
    if resp.status_code != httpx.codes.OK:
        raise SignalsUnavailableError(f"signals-app returned {resp.status_code}: {resp.text[:200]}")
    payload = resp.json()
    if payload.get("failed"):
        raise SignalsUnavailableError(payload["failed"][0].get("error", "dip study failed"))
    return payload["ok"][0]
