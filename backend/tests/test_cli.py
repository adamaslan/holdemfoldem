"""Tests for the holdfold CLI's argument parsing and dispatch, mocked at the
network/import boundary so these run without a live backend or mamba env.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cli.app import _build_request, _parse_leg, _parse_lot, app

runner = CliRunner()


class TestParseLot:
    def test_two_part_lot(self):
        assert _parse_lot("100@85.50") == {"qty": 100.0, "cost_basis": 85.50}

    def test_three_part_lot_with_date(self):
        assert _parse_lot("50@120@2025-01-15") == {
            "qty": 50.0, "cost_basis": 120.0, "acquired_at": "2025-01-15",
        }

    def test_missing_parts_raises(self):
        with pytest.raises(ValueError, match="qty@cost"):
            _parse_lot("100")

    def test_non_numeric_qty_raises(self):
        with pytest.raises(ValueError, match="non-numeric"):
            _parse_lot("abc@85.50")


class TestParseLeg:
    def test_two_part_leg(self):
        assert _parse_leg("sell_put:400") == {"role": "sell_put", "strike": 400.0}

    def test_three_part_leg_with_expiry(self):
        assert _parse_leg("buy_call:460:2026-01-16") == {
            "role": "buy_call", "strike": 460.0, "expiry": "2026-01-16",
        }

    def test_non_numeric_strike_raises(self):
        with pytest.raises(ValueError, match="non-numeric strike"):
            _parse_leg("buy_call:abc")


class TestBuildRequest:
    def test_minimal_request(self):
        req = _build_request(
            symbol="AAPL", period="3mo", asset_type="stock", risk_profile="moderate",
            strategy=None, dte=None, net_premium=None, legs=[], lots=[],
            cost_basis="average",
        )
        assert req == {
            "symbol": "AAPL", "period": "3mo", "asset_type": "stock",
            "risk_profile": "moderate", "cost_basis_method": "average",
        }

    def test_request_with_lots_and_legs(self):
        req = _build_request(
            symbol="SPY", period="1y", asset_type="stock", risk_profile="aggressive",
            strategy="iron_condor", dte=30, net_premium=2.10,
            legs=["sell_put:400", "buy_put:390"], lots=["100@85.50@2024-03-01"],
            cost_basis="fifo",
        )
        assert req["options_strategy"] == "iron_condor"
        assert req["dte"] == 30
        assert len(req["options_legs"]) == 2
        assert len(req["position_lots"]) == 1
        assert req["cost_basis_method"] == "fifo"


class TestVerdictCommand:
    def test_invalid_leg_format_exits_error(self):
        result = runner.invoke(app, ["verdict", "AAPL", "--leg", "not-a-leg"])
        assert result.exit_code == 3
        assert "Invalid input" in result.output

    def test_backend_unreachable_exits_error(self, monkeypatch):
        async def _raise_dispatch(request, remote):
            raise ConnectionError("Could not reach http://bad-host")

        monkeypatch.setattr("cli.app._dispatch", _raise_dispatch)
        result = runner.invoke(app, ["verdict", "AAPL", "--remote", "http://bad-host"])
        assert result.exit_code == 3
        assert "Backend unreachable" in result.output

    @pytest.mark.parametrize(
        "verdict_str,expected_exit",
        [("HOLD EM", 0), ("FOLD EM", 1), ("NEUTRAL", 2)],
    )
    def test_exit_code_encodes_verdict(self, monkeypatch, verdict_str, expected_exit):
        fake_result = {
            "symbol": "AAPL", "asset_type": "stock", "verdict": verdict_str,
            "confidence": 60.0, "price": 100.0, "bias": "neutral", "risk_level": "low",
            "cached": False, "bullish_count": 1, "bearish_count": 1, "avg_score": 55.0,
            "summary": "test", "disclaimer_version": "1.0",
        }

        async def _fake_dispatch(request, remote):
            return fake_result

        monkeypatch.setattr("cli.app._dispatch", _fake_dispatch)
        result = runner.invoke(app, ["verdict", "AAPL", "--json"])
        assert result.exit_code == expected_exit
