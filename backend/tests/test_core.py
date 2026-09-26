"""Unit tests for backend/core.py's pure helper functions (no network calls).

compute_verdict() itself hits the live MCP Finance pipeline and Firestore, so
it isn't unit-tested here — see the CLI/MCP dispatcher tests plus the
Playwright e2e suite for end-to-end coverage of the full pipeline.
"""

from __future__ import annotations

import pytest

from core import PositionLot, PositionPnL, _compute_lots_pnl, _extract_fib_levels, _per_share_pnl


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


class TestExtractFibLevels:
    PRICE = 150.0

    @staticmethod
    def _lv(name: str, price: float) -> dict:
        return {"name": name, "price": price, "strength": "s", "type": "retracement"}

    def test_returns_nearest_levels_not_first_in_registry_order(self):
        far = [self._lv(f"far{i}", 300.0 + i) for i in range(10)]
        near = [self._lv("nearA", 149.0), self._lv("nearB", 152.0)]
        levels, _, _, _ = _extract_fib_levels({"levels": far + near}, self.PRICE)
        names = [lv.name for lv in levels]
        assert len(levels) == 8
        assert "nearA" in names and "nearB" in names

    def test_nearest_support_and_resistance_use_every_level(self):
        # Eight levels crowd just above price, so the only level below price
        # is outside the returned ladder but is still the nearest support.
        crowd = [self._lv(f"up{i}", 151.0 + i) for i in range(8)]
        below = [self._lv("below", 100.0)]
        levels, _, support, resistance = _extract_fib_levels({"levels": crowd + below}, self.PRICE)
        assert support == 100.0
        assert resistance == 151.0
        assert "below" not in [lv.name for lv in levels]

    def test_skips_zero_price_and_handles_empty(self):
        assert _extract_fib_levels({"levels": [self._lv("z", 0)]}, self.PRICE)[0] == []
        assert _extract_fib_levels({}, self.PRICE) == ([], [], None, None)
