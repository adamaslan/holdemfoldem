"""Unit tests for backend/core.py's pure helper functions (no network calls).

compute_verdict() itself hits the live MCP Finance pipeline and Firestore, so
it isn't unit-tested here — see the CLI/MCP dispatcher tests plus the
Playwright e2e suite for end-to-end coverage of the full pipeline.
"""

from __future__ import annotations

import pytest

import core
from core import PositionLot, PositionPnL, _compute_lots_pnl, _per_share_pnl, _cache_key_for, _cached_or_fetch


class TestFractionalQtyPnl:
    """Regression for the per-share P&L bug: `unrealized_dollar / max(qty, 1)`
    clamped any total quantity below 1 up to 1, corrupting per-share P&L for
    fractional lots (e.g. BTC-USD, fractional shares).

    Exercises _per_share_pnl directly — the actual production function used
    by _build_verdict — rather than recomputing the formula inline, so a
    regression in the production path fails these tests.
    """

    def test_fractional_qty_reports_correct_per_share_pnl(self):
        lot = PositionLot(qty=0.5, cost_basis=100.0)
        pnl = _compute_lots_pnl(
            lots=[lot], current_price=200.0, method="average",
            split_adjustments=0, dividends_received=None,
        )
        # unrealized_dollar = (200 - 100) * 0.5 = 50.0
        assert pnl.unrealized_dollar == 50.0

        # The bug: 50.0 / max(0.5, 1) = 50.0 (wrong — 2x too low). Correct
        # per-share P&L is 50.0 / 0.5 = 100.0.
        assert _per_share_pnl(pnl, [lot]) == 100.0

    def test_zero_qty_returns_none_not_zero(self):
        """A zero total quantity must produce None (skip display), not a
        division-by-max(0, 1) artifact of 0.0 that looks like a real answer.
        """
        pnl = PositionPnL(
            unrealized_dollar=0.0, unrealized_pct=0.0, realized_dollar=0.0,
            fees_paid_total=0.0, dividends_received=None,
            split_adjustments_applied=0, cost_basis_effective=0.0,
            cost_basis_method="average", breakdown_by_lot=None,
        )
        assert _per_share_pnl(pnl, []) is None


class TestMixedSideLots:
    """Regression: _compute_lots_pnl used the first lot's side to sign the
    whole aggregate, so a mixed long+short lot list could report a profit
    when the true net P&L was zero. Now rejected outright.
    """

    def test_mixed_sides_raises_value_error(self):
        lots = [
            PositionLot(qty=10, cost_basis=100.0, side="long"),
            PositionLot(qty=10, cost_basis=100.0, side="short"),
        ]
        with pytest.raises(ValueError, match="mixes long and short"):
            _compute_lots_pnl(
                lots=lots, current_price=150.0, method="average",
                split_adjustments=0, dividends_received=None,
            )

    def test_uniform_long_sides_still_works(self):
        lots = [
            PositionLot(qty=10, cost_basis=100.0, side="long"),
            PositionLot(qty=5, cost_basis=90.0, side="long"),
        ]
        pnl = _compute_lots_pnl(
            lots=lots, current_price=150.0, method="average",
            split_adjustments=0, dividends_received=None,
        )
        assert pnl.unrealized_dollar > 0


class _FakeFirestoreCache:
    """In-memory stand-in for MCPFirestoreCache, keyed exactly like the real
    one: (tool_name, cache_key) -> {"result": ..., "updated_at": ...}.
    """

    def __init__(self):
        self.docs: dict[tuple[str, str], dict] = {}
        self.reads: list[tuple[str, str]] = []
        self.writes: list[tuple[str, str]] = []

    def read_tool_result(self, tool_name: str, cache_key: str):
        self.reads.append((tool_name, cache_key))
        return self.docs.get((tool_name, cache_key))

    def write_tool_result(self, tool_name: str, cache_key: str, result):
        self.writes.append((tool_name, cache_key))
        self.docs[(tool_name, cache_key)] = {
            "result": result,
            "updated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        }


class TestCacheKeyIncludesPeriod:
    """Regression for the multi-timeframe cache bug (FIBONACCI.md §12.1, PO1):
    `_cached_or_fetch`'s Firestore key used to be just `symbol`, so switching
    the portal's Period dropdown inside the 1-hour TTL returned the OLD
    period's ladder mislabeled as the new one. `analyze_security`,
    `get_trade_plan` and `analyze_fibonacci` are all fetched with a cache key
    built by `_cache_key_for(symbol, period)`, so two periods for one symbol
    must land in two distinct Firestore documents.
    """

    def test_cache_key_differs_by_period(self):
        assert _cache_key_for("AAPL", "1d") != _cache_key_for("AAPL", "1y")
        assert _cache_key_for("AAPL", "1d") == _cache_key_for("AAPL", "1d")

    def test_cache_key_omits_none_parts(self):
        # options_risk_analysis has no period param — key stays symbol-only.
        assert _cache_key_for("AAPL") == "AAPL"
        assert _cache_key_for("AAPL", None) == "AAPL"

    @pytest.mark.asyncio
    async def test_two_periods_produce_two_cache_entries(self, monkeypatch):
        fake_fs = _FakeFirestoreCache()
        monkeypatch.setattr(core, "_get_firestore", lambda: fake_fs)

        fetch_calls: list[str] = []

        async def fetch_for(period: str):
            fetch_calls.append(period)
            return {"period": period, "levels": [f"level-for-{period}"]}

        key_1d = _cache_key_for("AAPL", "1d")
        key_1y = _cache_key_for("AAPL", "1y")

        result_1d = await _cached_or_fetch(
            "analyze_fibonacci", key_1d, lambda: fetch_for("1d")
        )
        result_1y = await _cached_or_fetch(
            "analyze_fibonacci", key_1y, lambda: fetch_for("1y")
        )

        # Two distinct Firestore documents, not one overwritten by the other.
        assert len(fake_fs.docs) == 2
        assert ("analyze_fibonacci", key_1d) in fake_fs.docs
        assert ("analyze_fibonacci", key_1y) in fake_fs.docs
        assert result_1d["period"] == "1d"
        assert result_1y["period"] == "1y"
        assert fetch_calls == ["1d", "1y"]

        # A second request for the *same* period hits the fresh cache and
        # does not re-fetch — proves the fix didn't also break cache reuse.
        result_1d_again = await _cached_or_fetch(
            "analyze_fibonacci", key_1d, lambda: fetch_for("1d")
        )
        assert result_1d_again["period"] == "1d"
        assert fetch_calls == ["1d", "1y"]  # no third fetch call
