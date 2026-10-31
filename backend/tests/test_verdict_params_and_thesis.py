"""Per-request verdict thresholds, GET /api/params, and POST /api/thesis."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import core
import main
from signals_client import SignalsUnavailableError
from tests.test_deployed_entrypoint import CANNED_UPSTREAM


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def fake_cached_or_fetch(tool_name, cache_key, fetch_fn):
        return CANNED_UPSTREAM[tool_name]

    monkeypatch.setattr(core, "_cached_or_fetch", fake_cached_or_fetch)
    monkeypatch.setattr(core, "_get_firestore", lambda: None)
    return TestClient(main.app)


def test_defaults_unchanged_and_echoed(client: TestClient) -> None:
    body = client.post("/api/analyze", json={"symbol": "TEST"}).json()
    # avg_score 62, 3 bull vs 1 bear, no trade plan → plain HOLD EM at 62.
    assert body["verdict"] == "HOLD EM"
    assert body["confidence"] == pytest.approx(62.0)
    assert body["params_used"] == core.VerdictParams().model_dump()


def test_raised_thresholds_discount_confidence(client: TestClient) -> None:
    body = client.post("/api/analyze", json={
        "symbol": "TEST",
        "params": {"neutral_threshold": 65, "hold_threshold": 70, "weak_signal_discount": 0.5},
    }).json()
    assert body["verdict"] == "HOLD EM"
    assert body["confidence"] == pytest.approx(31.0)
    assert body["params_used"]["hold_threshold"] == 70


def test_atr_bands_are_tunable(client: TestClient) -> None:
    # ATR 3.0 on a 150 price = 2% → "normal" by default, "elevated" if the band drops.
    default = client.post("/api/analyze", json={"symbol": "TEST"}).json()
    tuned = client.post("/api/analyze", json={
        "symbol": "TEST", "params": {"vol_normal_pct": 1.5},
    }).json()
    assert default["volatility_regime"] == "normal"
    assert tuned["volatility_regime"] == "elevated"


@pytest.mark.parametrize("bad", [
    {"hold_thresh": 60},
    {"neutral_threshold": 70, "hold_threshold": 60},
    {"max_confidence": 500},
])
def test_bad_params_rejected(client: TestClient, bad: dict) -> None:
    assert client.post("/api/analyze", json={"symbol": "TEST", "params": bad}).status_code == 422


def test_params_route_lists_defaults(client: TestClient) -> None:
    body = client.get("/api/params").json()
    assert body["defaults"]["hold_threshold"] == core.HOLD_THRESHOLD
    assert "weak_signal_discount" in body["schema"]


def test_thesis_degrades_when_signals_unset(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SIGNALS_API_URL", raising=False)
    body = client.post("/api/thesis", json={"analyze": {"symbol": "TEST"}}).json()
    assert body["verdict"]["verdict"] == "HOLD EM"
    assert body["dip_study"] is None
    assert "SIGNALS_API_URL" in body["warnings"][0]


def test_thesis_attaches_dip_study(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    async def fake_fetch(symbol, *, period, params):
        seen.update(symbol=symbol, period=period, params=params)
        return {"symbol": symbol, "windows": [{"window": 10, "best_entry_delay": 1}]}

    monkeypatch.setattr(main, "fetch_dip_study", fake_fetch)
    body = client.post("/api/thesis", json={
        "analyze": {"symbol": "TEST"}, "dip_period": "2y", "dip_params": {"dip_pct": 7},
    }).json()
    assert body["dip_study"]["windows"][0]["best_entry_delay"] == 1
    assert seen == {"symbol": "TEST", "period": "2y", "params": {"dip_pct": 7}}
    assert body["warnings"] == []


def test_signals_error_type_is_runtime_error() -> None:
    assert issubclass(SignalsUnavailableError, RuntimeError)


def _fake_async_client(*, payload=None, json_error=False, status=200):
    class FakeResp:
        status_code = status
        text = "fake-body"

        def json(self):
            if json_error:
                raise ValueError("Expecting value")
            return payload

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> bool:
            return False

        async def post(self, *args, **kwargs):
            return FakeResp()

    return FakeClient


def test_dip_invalid_json_maps_to_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    import signals_client

    monkeypatch.setenv("SIGNALS_API_URL", "http://signals.test")
    monkeypatch.setattr(
        signals_client.httpx, "AsyncClient", _fake_async_client(json_error=True)
    )
    with pytest.raises(SignalsUnavailableError):
        asyncio.run(signals_client.fetch_dip_study("TEST"))


def test_dip_empty_ok_list_maps_to_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    import signals_client

    monkeypatch.setenv("SIGNALS_API_URL", "http://signals.test")
    monkeypatch.setattr(
        signals_client.httpx, "AsyncClient", _fake_async_client(payload={"ok": []})
    )
    with pytest.raises(SignalsUnavailableError):
        asyncio.run(signals_client.fetch_dip_study("TEST"))
def test_thesis_swing_is_opt_in_and_passes_params(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict] = []

    async def fake_dip(symbol, *, period, params):
        return {"symbol": symbol}

    async def fake_swing(symbol, *, period, params):
        calls.append({"symbol": symbol, "period": period, "params": params})
        return {"best": [{"entry": "dip(5,12)", "avg_pct": 5.2}]}

    monkeypatch.setattr(main, "fetch_dip_study", fake_dip)
    monkeypatch.setattr(main, "fetch_swing_grid", fake_swing)

    off = client.post("/api/thesis", json={"analyze": {"symbol": "TEST"}}).json()
    assert off["swing"] is None and calls == []

    on = client.post("/api/thesis", json={
        "analyze": {"symbol": "TEST"}, "swing_params": {"top": 3}, "swing_period": "3y",
    }).json()
    assert on["swing"]["best"][0]["entry"] == "dip(5,12)"
    assert calls == [{"symbol": "TEST", "period": "3y", "params": {"top": 3}}]


def test_thesis_swing_failure_is_a_warning(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_dip(symbol, *, period, params):
        return {"symbol": symbol}

    async def fake_swing(symbol, *, period, params):
        raise SignalsUnavailableError("no robust combo")

    monkeypatch.setattr(main, "fetch_dip_study", fake_dip)
    monkeypatch.setattr(main, "fetch_swing_grid", fake_swing)
    body = client.post("/api/thesis", json={"analyze": {"symbol": "TEST"}, "swing_params": {}}).json()
    assert body["swing"] is None
    assert body["warnings"] == ["swing_unavailable: no robust combo"]


async def test_fetch_swing_grid_parses_the_chain_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shape copied from a live POST /v1/chains/run: ``rows`` is a list of row dicts."""
    import signals_client

    async def fake_post(path, body):
        assert path == "/v1/chains/run"
        assert body["steps"][1] == {"op": "swing_grid", "params": {"top": 2, "period": "5y"}}
        return {
            "symbols": ["SNDK"],
            "rows": [{"symbol": "SNDK", "swing": {"best": [{"entry": "dip(5,5)"}]}}],
            "steps": [{"op": "symbols", "dropped": {}}, {"op": "swing_grid", "dropped": {}}],
        }

    monkeypatch.setattr(signals_client, "_post_signals", fake_post)
    swing = await signals_client.fetch_swing_grid("sndk", params={"top": 2})
    assert swing["best"][0]["entry"] == "dip(5,5)"


async def test_fetch_swing_grid_reports_why_symbol_was_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import signals_client

    async def fake_post(path, body):
        return {
            "symbols": [],
            "rows": [],
            "steps": [{"op": "symbols", "dropped": {}},
                      {"op": "swing_grid", "dropped": {"SNDK": "no robust combo"}}],
        }

    monkeypatch.setattr(signals_client, "_post_signals", fake_post)
    with pytest.raises(SignalsUnavailableError, match="no robust combo"):
        await signals_client.fetch_swing_grid("SNDK")
