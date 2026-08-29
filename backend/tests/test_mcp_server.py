"""Tests for the MCP server's tool dispatch, mocked at the HTTP boundary so
these run without a live backend.
"""

from __future__ import annotations

import httpx
import pytest

from mcp_server.server import call_tool, list_tools


@pytest.mark.asyncio
async def test_list_tools_returns_three_tools():
    tools = await list_tools()
    names = {t.name for t in tools}
    assert names == {"get_verdict", "evaluate_options_strategy", "check_health"}


@pytest.mark.asyncio
async def test_unknown_tool_raises():
    with pytest.raises(ValueError, match="Unknown tool"):
        await call_tool("nope", {})


@pytest.mark.asyncio
async def test_get_verdict_summarizes_not_dumps(monkeypatch):
    fake_verdict = {
        "symbol": "AAPL", "asset_type": "stock", "verdict": "HOLD EM",
        "confidence": 65.6, "price": 319.70, "bias": "bullish", "risk_level": "low",
        "cached": False, "bullish_count": 13, "bearish_count": 8, "avg_score": 62.5,
        "entry": 319.70, "stop": 310.64, "target": 346.87, "risk_reward": 3.0,
        "suppressions": [], "warnings": [], "degraded": False,
        "summary": "13 bullish / 8 bearish signals.",
        "disclaimer_version": "1.0",
        "payoff_curve": [{"price": p, "pnl": p * 2} for p in range(200)],  # would bloat raw dump
    }

    async def _fake_post_analyze(payload):
        return fake_verdict

    monkeypatch.setattr("mcp_server.server._post_analyze", _fake_post_analyze)

    [content] = await call_tool("get_verdict", {"symbol": "AAPL"})
    assert "HOLD EM" in content.text
    assert "65.6%" in content.text
    assert "R/R 3.0" in content.text
    # The 200-point payoff curve must not be dumped verbatim into the summary.
    assert "pnl" not in content.text


@pytest.mark.asyncio
async def test_get_verdict_surfaces_degraded_and_warnings(monkeypatch):
    fake_verdict = {
        "symbol": "AAPL", "asset_type": "stock", "verdict": "NEUTRAL",
        "confidence": 50.0, "price": 100.0, "bias": "neutral", "risk_level": "medium",
        "cached": True, "bullish_count": 1, "bearish_count": 1, "avg_score": 50.0,
        "suppressions": [{"code": "RR_UNFAVORABLE", "label": "R:R below 1.5:1"}],
        "warnings": ["options_chain_unavailable"],
        "degraded": True,
        "summary": "thin data",
        "disclaimer_version": "1.0",
    }

    async def _fake_post_analyze(payload):
        return fake_verdict

    monkeypatch.setattr("mcp_server.server._post_analyze", _fake_post_analyze)

    [content] = await call_tool("get_verdict", {"symbol": "AAPL"})
    assert "DEGRADED" in content.text
    assert "options_chain_unavailable" in content.text
    assert "R:R below 1.5:1" in content.text


@pytest.mark.asyncio
async def test_backend_unreachable_returns_friendly_message(monkeypatch):
    async def _raise_connect_error(payload):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr("mcp_server.server._post_analyze", _raise_connect_error)

    [content] = await call_tool("get_verdict", {"symbol": "AAPL"})
    assert "unreachable" in content.text.lower()


@pytest.mark.asyncio
async def test_backend_rejects_bad_input(monkeypatch):
    request = httpx.Request("POST", "http://localhost:8001/api/analyze")
    response = httpx.Response(400, json={"detail": "Symbol required"}, request=request)

    async def _raise_http_error(payload):
        raise httpx.HTTPStatusError("Bad Request", request=request, response=response)

    monkeypatch.setattr("mcp_server.server._post_analyze", _raise_http_error)

    [content] = await call_tool("get_verdict", {"symbol": ""})
    assert "Symbol required" in content.text


@pytest.mark.asyncio
async def test_check_health_reports_backend_status(monkeypatch):
    async def _fake_get_health():
        return {"status": "ok", "version": "5.0", "firestore": True}

    monkeypatch.setattr("mcp_server.server._get_health", _fake_get_health)

    [content] = await call_tool("check_health", {})
    assert '"status": "ok"' in content.text
