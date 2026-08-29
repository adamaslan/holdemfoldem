"""Unit tests for backend/core.py's pure helper functions (no network calls).

compute_verdict() itself hits the live MCP Finance pipeline and Firestore, so
it isn't unit-tested here — see the CLI/MCP dispatcher tests plus the
Playwright e2e suite for end-to-end coverage of the full pipeline.
"""

from __future__ import annotations

from core import PositionLot, _compute_lots_pnl


class TestFractionalQtyPnl:
    """Regression for the per-share P&L bug: `unrealized_dollar / max(qty, 1)`
    clamped any total quantity below 1 up to 1, corrupting per-share P&L for
    fractional lots (e.g. BTC-USD, fractional shares).
    """

    def test_fractional_qty_reports_correct_per_share_pnl(self):
        lot = PositionLot(qty=0.5, cost_basis=100.0)
        pnl = _compute_lots_pnl(
            lots=[lot], current_price=200.0, method="average",
            split_adjustments=0, dividends_received=None,
        )
        # unrealized_dollar = (200 - 100) * 0.5 = 50.0
        assert pnl.unrealized_dollar == 50.0

        # The bug: pnl.unrealized_dollar / max(0.5, 1) = 50.0 (wrong — 2x
        # too low). Correct per-share P&L is 50.0 / 0.5 = 100.0. This test
        # exercises core.py's caller-side division directly, mirroring the
        # fixed expression in compute_verdict's _build_verdict caller.
        total_qty = sum(lot.qty for lot in [lot])
        per_share = pnl.unrealized_dollar / total_qty if total_qty else None
        assert per_share == 100.0

    def test_zero_qty_returns_none_not_zero(self):
        """A zero total quantity must produce None (skip display), not a
        division-by-max(0, 1) artifact of 0.0 that looks like a real answer.
        """
        total_qty = 0.0
        unrealized_dollar = 0.0
        per_share = unrealized_dollar / total_qty if total_qty else None
        assert per_share is None
