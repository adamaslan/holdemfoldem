"""Unit tests for backend/core.py's pure helper functions (no network calls).

compute_verdict() itself hits the live MCP Finance pipeline and Firestore, so
it isn't unit-tested here — see the CLI/MCP dispatcher tests plus the
Playwright e2e suite for end-to-end coverage of the full pipeline.
"""

from __future__ import annotations

import pytest

from core import PositionLot, PositionPnL, _compute_lots_pnl, _per_share_pnl


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
