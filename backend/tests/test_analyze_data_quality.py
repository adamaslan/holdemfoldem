"""Regression tests for /api/analyze data-quality bugs seen on CLOU (2026-10-02).

1. fib_levels carried the same price twice (88.6% as RETRACE and HARMONIC).
2. atr was null / volatility_regime "unknown" because analyze_security() never
   emits indicators["atr"].
3. A suppression code leaked as "SuppressionCode.NO_TREND" (Enum str()).

Synthetic payloads only: no network, no Firestore.
"""

from __future__ import annotations

import math

import pytest

from core import (
    AnalyzeRequest,
    _build_verdict,
    _dedupe_fib_levels,
    _extract_fib_levels,
    _resolve_atr,
    _suppression_code,
)

CLOU_PRICE = 28.81


def _analysis(indicators: dict | None = None) -> dict:
    """Shape of analyze_security(): indicators carry no 'atr' key."""
    return {
        "symbol": "CLOU",
        "price": CLOU_PRICE,
        "summary": {"bullish": 1, "bearish": 0, "avg_score": 75},
        "indicators": indicators
        if indicators is not None
        else {"rsi": 49.85, "macd": 0.1, "adx": 12.19, "volume": 1000},
        "signals": [],
    }


def _no_trend_trade(atr: float = 0.9) -> dict:
    """Shape of get_trade_plan().model_dump() when NO_TREND suppresses the plan."""
    from src.technical_analysis_mcp.risk.models import SuppressionCode

    return {
        "has_trades": False,
        "trade_plans": (),
        "all_suppressions": (
            {"code": SuppressionCode.NO_TREND, "message": "ADX 12 < 20",
             "threshold": 20.0, "actual": 12.19},
        ),
        "risk_assessment": {"metrics": {"atr": atr, "adx": 12.19}},
    }


def _verdict(analysis: dict, trade: dict, fib: dict | None = None):
    return _build_verdict(
        analysis, trade, fib or {}, None,
        AnalyzeRequest(symbol="CLOU"), cached=False,
    )


class TestFibLevelDedup:
    CLOU_FIB = {
        "levels": [
            {"name": "61.8%", "price": 30.1, "strength": "SIGNIFICANT", "type": "RETRACE"},
            {"name": "88.6%", "price": 28.5778, "strength": "SIGNIFICANT", "type": "HARMONIC"},
            {"name": "88.6%", "price": 28.5778, "strength": "SIGNIFICANT", "type": "RETRACE"},
            {"name": "127.0%", "price": 33.0, "strength": "MODERATE", "type": "HARMONIC"},
        ],
        "confluenceZones": [],
    }

    def test_same_ratio_and_price_under_two_kinds_is_emitted_once(self):
        levels, _, _, _ = _extract_fib_levels(self.CLOU_FIB, CLOU_PRICE)
        assert [lv.name for lv in levels].count("88.6%") == 1
        assert len(levels) == 3

    def test_retrace_is_preferred_over_harmonic(self):
        levels, _, _, _ = _extract_fib_levels(self.CLOU_FIB, CLOU_PRICE)
        kept = next(lv for lv in levels if lv.name == "88.6%")
        assert kept.type == "RETRACE"
        assert kept.price == 28.5778

    def test_entry_shape_is_unchanged(self):
        levels, _, _, _ = _extract_fib_levels(self.CLOU_FIB, CLOU_PRICE)
        assert set(levels[0].model_dump()) == {
            "name", "price", "distance_pct", "strength", "type",
        }

    def test_same_ratio_at_a_different_price_is_kept(self):
        raw = [
            {"name": "88.6%", "price": 28.5778, "type": "RETRACE"},
            {"name": "88.6%", "price": 35.0, "type": "HARMONIC"},
        ]
        assert len(_dedupe_fib_levels(raw)) == 2

    def test_prices_within_tolerance_collapse(self):
        raw = [
            {"name": "88.6%", "price": 28.5778, "type": "HARMONIC"},
            {"name": "88.6%", "price": 28.5780, "type": "RETRACE"},
        ]
        kept = _dedupe_fib_levels(raw)
        assert len(kept) == 1 and kept[0]["type"] == "RETRACE"

    def test_duplicates_do_not_consume_the_eight_level_cap(self):
        raw = [{"name": f"{i}%", "price": 10.0 + i, "type": "RETRACE"} for i in range(8)]
        raw.insert(1, {"name": "0%", "price": 10.0, "type": "HARMONIC"})
        levels, _, _, _ = _extract_fib_levels({"levels": raw}, 12.0)
        assert [lv.name for lv in levels] == [f"{i}%" for i in range(8)]

    def test_full_verdict_has_unique_levels(self):
        verdict = _verdict(_analysis(), _no_trend_trade(), self.CLOU_FIB)
        keys = [(lv.name, lv.price) for lv in verdict.fib_levels]
        assert len(keys) == len(set(keys))


class TestAtrPopulated:
    def test_atr_falls_back_to_trade_plan_risk_metrics(self):
        """analyze_security never emits indicators['atr']; get_trade_plan does."""
        verdict = _verdict(_analysis(), _no_trend_trade(atr=0.9))
        assert verdict.atr == 0.9
        assert verdict.volatility_regime == "elevated"  # 0.9 / 28.81 = 3.1%

    def test_indicator_atr_wins_when_present(self):
        analysis = _analysis({"rsi": 50, "adx": 12, "atr": 0.3})
        assert _verdict(analysis, _no_trend_trade(atr=0.9)).atr == 0.3

    @pytest.mark.parametrize("bad", [0, 0.0, -1.0, math.nan, math.inf, None, "x"])
    def test_unusable_atr_resolves_to_none_not_a_fake_value(self, bad):
        trade = {"risk_assessment": {"metrics": {"atr": bad}}}
        assert _resolve_atr({"atr": bad}, trade) is None

    def test_missing_risk_assessment_is_tolerated(self):
        assert _resolve_atr({}, {}) is None
        assert _resolve_atr({}, {"risk_assessment": None}) is None

    def test_intentional_trade_plan_nulls_stay_null(self):
        verdict = _verdict(_analysis(), _no_trend_trade())
        assert verdict.entry is None
        assert verdict.stop is None
        assert verdict.target is None


class TestSuppressionCodeSerialization:
    def test_enum_member_serializes_as_bare_code(self):
        from src.technical_analysis_mcp.risk.models import SuppressionCode

        assert _suppression_code({"code": SuppressionCode.NO_TREND}) == "NO_TREND"
        assert _suppression_code(SuppressionCode.NO_TREND) == "NO_TREND"

    @pytest.mark.parametrize("raw", [
        {"code": "NO_TREND"}, "NO_TREND", {"code": "SuppressionCode.NO_TREND"},
    ])
    def test_plain_and_already_leaked_strings_normalize(self, raw):
        assert _suppression_code(raw) == "NO_TREND"

    def test_verdict_code_and_label_resolve(self):
        verdict = _verdict(_analysis(), _no_trend_trade())
        [info] = verdict.suppressions
        assert info.code == "NO_TREND"
        assert info.label == "No trend (ADX <20)"  # label lookup also failed before
        assert "SuppressionCode" not in verdict.model_dump_json()
