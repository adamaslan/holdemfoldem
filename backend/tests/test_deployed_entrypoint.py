"""Regression for wiki open issue #3: the deployed entrypoint must serve the
full verdict — multi-lot P&L and Fibonacci levels — not the pre-v5 stub.

deploy-backend.sh ships backend/main.py + backend/core.py as the Cloud Run
image's main.py. This drives that exact FastAPI app over HTTP with the MCP
Finance fetches stubbed out, so it runs offline and fails if the route ever
stops returning position_pnl / fib_levels for a request that supplies lots.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import core
import main

PRICE = 150.0

CANNED_UPSTREAM = {
    "analyze_security": {
        "symbol": "TEST",
        "price": PRICE,
        "summary": {"bullish": 3, "bearish": 1, "avg_score": 62},
        "indicators": {"rsi": 55.0, "macd": 0.4, "adx": 22.0, "atr": 3.0},
        "signals": [],
    },
    "get_trade_plan": {"has_trades": False, "trade_plans": []},
    "analyze_fibonacci": {
        "levels": [
            {"name": "38.2%", "price": 140.0, "strength": "strong", "type": "retracement"},
            {"name": "61.8%", "price": 160.0, "strength": "moderate", "type": "retracement"},
        ],
        "confluenceZones": [],
    },
}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def fake_cached_or_fetch(tool_name, cache_key, fetch_fn):
        return CANNED_UPSTREAM[tool_name]

    monkeypatch.setattr(core, "_cached_or_fetch", fake_cached_or_fetch)
    monkeypatch.setattr(core, "_get_firestore", lambda: None)
    return TestClient(main.app)


def test_lots_request_returns_pnl_and_fib_levels(client: TestClient) -> None:
    response = client.post("/api/analyze", json={
        "symbol": "TEST",
        "position_lots": [
            {"qty": 10, "cost_basis": 100.0},
            {"qty": 5, "cost_basis": 120.0},
        ],
    })

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["position_pnl_detail"] is not None
    assert body["position_pnl_detail"]["unrealized_dollar"] == pytest.approx(
        (PRICE - 100.0) * 10 + (PRICE - 120.0) * 5
    )
    assert [lv["price"] for lv in body["fib_levels"]] == [140.0, 160.0]


def test_health_reports_v5_core(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["version"] == core.CORE_VERSION
