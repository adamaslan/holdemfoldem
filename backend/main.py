"""
Hold Em or Fold Em — Backend v5
Proper options payoff math using strikes, net premium (credit/debit), and underlying price.
"""

import asyncio
import logging
import math
import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ── Load .env (local dev only — Cloud Run uses env vars set at deploy time) ───
_env_path = Path(__file__).parent.parent.parent / "gcp-app-w-mcp1" / "mcp-finance1" / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

# ── Add mcp source to path ────────────────────────────────────────────────────
# Local: sibling gcp-app-w-mcp1/mcp-finance1   Cloud Run: /app (Dockerfile COPY src ./src)
_local_mcp = Path(__file__).parent.parent.parent / "gcp-app-w-mcp1" / "mcp-finance1"
_cloudrun_mcp = Path("/app")
_mcp_path = _local_mcp if _local_mcp.exists() else _cloudrun_mcp
sys.path.insert(0, str(_mcp_path))
os.chdir(str(_mcp_path))

from src.technical_analysis_mcp.server import (  # noqa: E402
    analyze_security,
    get_trade_plan,
    analyze_fibonacci,
    options_risk_analysis,
)
from src.technical_analysis_mcp.cache.firestore_cache import MCPFirestoreCache  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Hold Em or Fold Em", version="5.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Firestore cache ───────────────────────────────────────────────────────────
_firestore: MCPFirestoreCache | None | bool = None


def _get_firestore() -> MCPFirestoreCache | None:
    global _firestore
    if _firestore is None:
        try:
            _firestore = MCPFirestoreCache()
        except Exception as e:
            logger.warning("Firestore unavailable: %s", e)
            _firestore = False
    return _firestore if _firestore is not False else None


async def _cached_or_fetch(tool_name: str, cache_key: str, fetch_fn):
    """fetch_fn is a zero-arg callable that returns a coroutine (avoids unawaited-coroutine warnings)."""
    fs = _get_firestore()
    if fs:
        doc = fs.read_tool_result(tool_name, cache_key)
        if doc and doc.get("result"):
            return doc["result"]
    result = await fetch_fn()
    if fs and result:
        fs.write_tool_result(tool_name, cache_key, result)
    return result


# ── Constants ─────────────────────────────────────────────────────────────────
HOLD_THRESHOLD    = 60
NEUTRAL_THRESHOLD = 55
MAX_CONF          = 95.0
PAYOFF_POINTS     = 60     # resolution of payoff curve

SUPPRESSION_LABELS = {
    "STOP_TOO_WIDE":          "Stop too wide (>3 ATR)",
    "STOP_TOO_TIGHT":         "Stop too tight (<0.5 ATR)",
    "RR_UNFAVORABLE":         "R:R below 1.5:1",
    "NO_CLEAR_INVALIDATION":  "No clear invalidation level",
    "VOLATILITY_TOO_HIGH":    "Volatility too high (ATR >3%)",
    "VOLATILITY_TOO_LOW":     "Volatility too low (ATR <1.5%)",
    "NO_TREND":               "No trend (ADX <20)",
    "CONFLICTING_SIGNALS":    "Too many conflicting signals",
    "INSUFFICIENT_DATA":      "Insufficient price history",
}

STRATEGY_NOTES: dict[str, str] = {
    "long_call":          "Long call profits when the underlying rises above strike + premium paid.",
    "long_put":           "Long put profits when the underlying falls below strike − premium paid.",
    "covered_call":       "Own 100 shares + sell call to collect premium; capped upside above strike.",
    "cash_secured_put":   "Sell put secured by cash; keep premium if above strike at expiry, else buy shares at discount.",
    "bull_call_spread":   "Buy lower-strike call / sell upper-strike call. Max profit = spread width − debit. Max loss = debit.",
    "bear_put_spread":    "Buy upper-strike put / sell lower-strike put. Max profit = spread width − debit. Max loss = debit.",
    "call_credit_spread": "Sell lower-strike call / buy upper-strike call. Max profit = credit. Max loss = spread width − credit.",
    "put_credit_spread":  "Sell upper-strike put / buy lower-strike put. Max profit = credit. Max loss = spread width − credit.",
    "iron_condor":        "Sell OTM put spread + sell OTM call spread. Profit in range between short strikes. Max profit = net credit.",
    "iron_butterfly":     "Sell ATM straddle + buy OTM wings. Max profit at ATM price. Wider body = more credit, less range.",
    "straddle":           "Buy ATM call + ATM put. Profits from large move either direction. Ideal for high-IV events like earnings.",
    "strangle":           "Buy OTM put + OTM call. Cheaper than straddle but needs a larger underlying move to profit.",
    "calendar_spread":    "Sell near-term option / buy same-strike far-term option. Profits from theta decay and stable price.",
    "diagonal_spread":    "Buy far-term ITM / sell near-term OTM. Directional + theta benefit. Like a cheaper covered call.",
}

# Strategy taxonomy for verdict logic
NEUTRAL_STRATEGIES    = {"iron_condor", "iron_butterfly", "covered_call",
                          "cash_secured_put", "call_credit_spread", "put_credit_spread", "calendar_spread"}
VOLATILITY_STRATEGIES = {"straddle", "strangle"}
BEARISH_STRATEGIES    = {"long_put", "bear_put_spread"}
# Everything else is treated as bullish-leaning


# ── Request / Response models ─────────────────────────────────────────────────

class OptionsLegRequest(BaseModel):
    role:    str
    strike:  float | None = None
    expiry:  str   | None = None
    premium: float | None = None  # reserved for per-leg premium (currently unused)


class AnalyzeRequest(BaseModel):
    symbol:           str
    period:           str   = "3mo"
    asset_type:       str   = "stock"
    risk_profile:     str   = "moderate"
    options_strategy: str   | None = None
    options_legs:     list[OptionsLegRequest] | None = None
    dte:              int   | None = Field(default=None, description="Days to expiration")
    # Net premium: positive = credit received, negative = debit paid (per share)
    net_premium:      float | None = Field(default=None, description="Net credit (+) or debit (−) per share")
    premium_sign:     int   | None = Field(default=None, description="+1 credit strategy, -1 debit strategy")
    # Optional underlying price bounds for payoff chart
    spot_low:         float | None = None
    spot_high:        float | None = None
    # Existing position
    position_qty:     float | None = None
    position_entry:   float | None = None
    position_side:    str          = "long"


class SuppressionInfo(BaseModel):
    code:  str
    label: str


class FibLevel(BaseModel):
    name:         str
    price:        float
    distance_pct: float
    strength:     str
    type:         str


class OptionsGreeks(BaseModel):
    iv:        float | None
    pcr:       float | None
    delta_atm: float | None
    theta_atm: float | None
    vega_atm:  float | None


class OptionsLegResponse(BaseModel):
    role:    str
    strike:  float | None
    expiry:  str   | None
    premium: float | None = None


class PayoffPoint(BaseModel):
    price: float
    pnl:   float


class HoldFoldVerdict(BaseModel):
    # ── Core ──────────────────────────────────────────────────────────────────
    symbol:     str
    asset_type: str
    verdict:    str    # HOLD EM | FOLD EM | NEUTRAL
    confidence: float
    price:      float
    bias:       str
    risk_level: str
    cached:     bool

    # ── Signals ───────────────────────────────────────────────────────────────
    bullish_count: int
    bearish_count: int
    avg_score:     float
    top_signals:   list[dict]

    # ── Indicators ────────────────────────────────────────────────────────────
    rsi:               float | None
    macd:              float | None
    adx:               float | None
    atr:               float | None
    volatility_regime: str
    volume_spike:      str | None

    # ── Suppressions ──────────────────────────────────────────────────────────
    suppressions: list[SuppressionInfo]

    # ── Trade plan ────────────────────────────────────────────────────────────
    trade_timeframe:   str   | None
    entry:             float | None
    stop:              float | None
    target:            float | None
    risk_reward:       float | None
    stop_pct:          float | None
    upside_pct:        float | None
    vehicle:           str   | None
    vehicle_notes:     str   | None
    primary_signal:    str   | None
    supporting_signals: list[str]

    # ── Position P&L ──────────────────────────────────────────────────────────
    position_qty:       float | None
    position_entry:     float | None
    position_side:      str
    position_pnl_pct:   float | None
    position_pnl_dollar: float | None
    position_vs_stop:   str   | None
    position_vs_target: str   | None

    # ── Fibonacci ─────────────────────────────────────────────────────────────
    fib_levels:             list[FibLevel]
    fib_confluence_zones:   list[dict]
    nearest_fib_support:    float | None
    nearest_fib_resistance: float | None

    # ── Options ───────────────────────────────────────────────────────────────
    options_greeks:   OptionsGreeks | None
    options_strategy: str           | None
    options_legs:     list[OptionsLegResponse] | None
    dte:              int   | None
    net_premium:      float | None   # positive = credit, negative = debit
    max_profit:       float | None
    max_loss:         float | None
    spread_width:     float | None
    breakeven_prices: list[float] | None
    pop:              float | None   # probability of profit (0-100)
    payoff_curve:     list[PayoffPoint] | None
    strategy_note:    str   | None

    # ── Summary ───────────────────────────────────────────────────────────────
    summary:        str
    data_timestamp: str | None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _volatility_regime(atr: float | None, price: float) -> str:
    if not atr or price == 0:
        return "unknown"
    pct = (atr / price) * 100
    if pct < 1.0:   return "low"
    if pct < 2.5:   return "normal"
    if pct < 5.0:   return "elevated"
    return "extreme"


def _risk_level(avg_score: float, rr: float | None, atr_pct: float | None) -> str:
    score = 0
    if avg_score < 50:            score += 2
    elif avg_score < 60:          score += 1
    if rr is not None and rr < 1.5:      score += 1
    if atr_pct is not None and atr_pct > 3.0: score += 1
    if atr_pct is not None and atr_pct > 5.0: score += 1
    return ["low", "medium", "high", "extreme"][min(score, 3)]


def _position_eval(
    price: float, entry: float | None, stop: float | None,
    target: float | None, qty: float | None, side: str,
) -> tuple[float | None, float | None, str | None, str | None]:
    if not entry:
        return None, None, None, None
    mult      = 1 if side == "long" else -1
    pnl_pct   = ((price - entry) / entry) * 100 * mult
    pnl_dollar = (price - entry) * mult
    vs_stop = vs_target = None
    if stop:
        long_stop  = "Above stop ✓" if price > stop else "BELOW STOP ✗"
        short_stop = "Below stop ✓" if price < stop else "ABOVE STOP ✗"
        vs_stop = long_stop if side == "long" else short_stop
    if target:
        long_target  = "AT/ABOVE TARGET ✓" if price >= target else f"${target - price:.2f} to target"
        short_target = "AT/BELOW TARGET ✓" if price <= target else f"${price - target:.2f} to target"
        vs_target = long_target if side == "long" else short_target
    return round(pnl_pct, 2), round(pnl_dollar, 4), vs_stop, vs_target


def _extract_fib_levels(
    fib_data: dict, current_price: float
) -> tuple[list[FibLevel], list[dict], float | None, float | None]:
    levels_raw = fib_data.get("levels", [])
    zones_raw  = fib_data.get("confluenceZones", [])
    levels: list[FibLevel] = []
    for lv in levels_raw[:8]:
        lv_price = lv.get("price", 0)
        if not lv_price:
            continue
        dist_pct = ((lv_price - current_price) / current_price) * 100
        levels.append(FibLevel(
            name=lv.get("name", lv.get("key", "")),
            price=round(lv_price, 4),
            distance_pct=round(dist_pct, 2),
            strength=lv.get("strength", ""),
            type=lv.get("type", ""),
        ))
    below = [lv for lv in levels if lv.price < current_price]
    above = [lv for lv in levels if lv.price > current_price]
    nearest_support    = max((lv.price for lv in below), default=None)
    nearest_resistance = min((lv.price for lv in above), default=None)
    top_zones = [
        {"price": round(z.get("price", 0), 4), "strength": z.get("strength", ""),
         "signal_count": z.get("signalCount", 0), "confluence_score": round(z.get("confluenceScore", 0), 2)}
        for z in zones_raw[:3]
    ]
    return levels, top_zones, nearest_support, nearest_resistance


def _extract_options_greeks(options_data: dict) -> OptionsGreeks | None:
    if not options_data:
        return None
    metrics = options_data.get("metrics", options_data)
    iv    = metrics.get("implied_volatility") or metrics.get("iv") or metrics.get("avg_iv")
    pcr   = metrics.get("put_call_ratio") or metrics.get("pcr")
    delta = metrics.get("delta_atm") or metrics.get("delta")
    theta = metrics.get("theta_atm") or metrics.get("theta")
    vega  = metrics.get("vega_atm") or metrics.get("vega")
    return OptionsGreeks(
        iv=round(iv, 4) if iv else None,
        pcr=round(pcr, 3) if pcr else None,
        delta_atm=round(delta, 4) if delta else None,
        theta_atm=round(theta, 4) if theta else None,
        vega_atm=round(vega, 4) if vega else None,
    )


# ── Core options payoff engine ────────────────────────────────────────────────

def _call_payoff(spot: float, strike: float) -> float:
    return max(spot - strike, 0.0)


def _put_payoff(spot: float, strike: float) -> float:
    return max(strike - spot, 0.0)


def _strategy_pnl_at_expiry(
    strategy: str,
    strikes: list[float],
    net_premium: float,   # positive = credit received, negative = debit paid
    spot: float,
) -> float | None:
    """
    Compute per-share P&L at expiry for a given underlying spot price.
    net_premium > 0 means we received credit (income); < 0 means we paid debit.
    All returned values are per share.
    """
    s = sorted(strikes)

    if strategy == "long_call" and len(s) >= 1:
        return _call_payoff(spot, s[0]) + net_premium   # net_premium is negative (debit)

    if strategy == "long_put" and len(s) >= 1:
        return _put_payoff(spot, s[0]) + net_premium

    if strategy == "covered_call" and len(s) >= 1:
        # Underlying P&L relative to stock cost basis is tracked separately;
        # here we model just the call leg: short call + net premium received
        return -_call_payoff(spot, s[0]) + net_premium

    if strategy == "cash_secured_put" and len(s) >= 1:
        return -_put_payoff(spot, s[0]) + net_premium

    if strategy == "bull_call_spread" and len(s) >= 2:
        long_leg  = _call_payoff(spot, s[0])
        short_leg = _call_payoff(spot, s[1])
        return long_leg - short_leg + net_premium  # net_premium is negative

    if strategy == "bear_put_spread" and len(s) >= 2:
        long_leg  = _put_payoff(spot, s[1])   # buy higher-strike put
        short_leg = _put_payoff(spot, s[0])   # sell lower-strike put
        return long_leg - short_leg + net_premium

    if strategy == "call_credit_spread" and len(s) >= 2:
        short_leg = _call_payoff(spot, s[0])  # sell lower-strike call
        long_leg  = _call_payoff(spot, s[1])  # buy upper-strike call (hedge)
        return -short_leg + long_leg + net_premium  # net_premium is positive

    if strategy == "put_credit_spread" and len(s) >= 2:
        short_leg = _put_payoff(spot, s[1])   # sell upper-strike put
        long_leg  = _put_payoff(spot, s[0])   # buy lower-strike put (hedge)
        return -short_leg + long_leg + net_premium

    if strategy == "iron_condor" and len(s) >= 4:
        # long put wing, short put, short call, long call wing
        put_long  = _put_payoff(spot,  s[0])
        put_short = _put_payoff(spot,  s[1])
        call_short = _call_payoff(spot, s[2])
        call_long  = _call_payoff(spot, s[3])
        return (put_long - put_short) + (-call_short + call_long) + net_premium

    if strategy == "iron_butterfly" and len(s) >= 3:
        # long put (wing low), short put + short call (ATM), long call (wing high)
        # With 4 strikes where s[1]==s[2] (ATM)
        unique = sorted(set(s))
        if len(unique) == 3:
            w_low, atm, w_high = unique
        elif len(unique) >= 4:
            w_low, atm = unique[0], unique[1]
            w_high = unique[-1]
        else:
            return None
        put_long   = _put_payoff(spot,  w_low)
        put_short  = _put_payoff(spot,  atm)
        call_short = _call_payoff(spot, atm)
        call_long  = _call_payoff(spot, w_high)
        return put_long - put_short - call_short + call_long + net_premium

    if strategy == "straddle" and len(s) >= 1:
        # buy ATM call + ATM put at the same strike
        atm_strike = s[0]
        return _call_payoff(spot, atm_strike) + _put_payoff(spot, atm_strike) + net_premium

    if strategy == "strangle" and len(s) >= 2:
        put_leg  = _put_payoff(spot, s[0])
        call_leg = _call_payoff(spot, s[1])
        return call_leg + put_leg + net_premium

    return None


def _compute_payoff_metrics(
    strategy: str,
    req_legs: list[OptionsLegRequest],
    net_premium: float | None,
    spot_low: float | None,
    spot_high: float | None,
    current_price: float,
    iv: float | None,
    dte: int | None,
) -> tuple[float | None, float | None, float | None, list[float], float | None, list[PayoffPoint]]:
    """
    Returns: (max_profit, max_loss, spread_width, breakevens, pop, payoff_curve)
    All per-share values; multiply by 100 for contract.
    """
    strikes = sorted([lg.strike for lg in req_legs if lg.strike is not None])
    if not strikes:
        return None, None, None, [], None, []

    premium = net_premium or 0.0  # default to 0 if not provided (payoff shape still useful)

    # Build price range for payoff chart
    if spot_low and spot_high and spot_low < spot_high:
        price_min, price_max = spot_low, spot_high
    else:
        # Auto-range: ±30% from current price, anchored around all strikes
        all_prices = strikes + [current_price]
        price_min = min(all_prices) * 0.70
        price_max = max(all_prices) * 1.30

    price_min = max(price_min, 0.01)
    step = (price_max - price_min) / PAYOFF_POINTS

    payoff_points: list[PayoffPoint] = []
    pnls: list[float] = []
    for i in range(PAYOFF_POINTS + 1):
        spot = price_min + i * step
        pnl  = _strategy_pnl_at_expiry(strategy, strikes, premium, spot)
        if pnl is not None:
            payoff_points.append(PayoffPoint(price=round(spot, 2), pnl=round(pnl, 4)))
            pnls.append(pnl)

    if not pnls:
        return None, None, None, [], None, []

    max_profit_raw = max(pnls)
    max_loss_raw   = min(pnls)
    # Cap "unlimited" at sentinel value; client treats >= 1e9 as unlimited
    INF = 1e9
    max_profit = round(max_profit_raw, 4) if max_profit_raw < INF else INF
    max_loss   = round(abs(max_loss_raw), 4) if max_loss_raw > -INF else INF

    # Spread width (distance between outermost strikes that form a spread)
    spread_width: float | None = None
    if len(strikes) >= 2 and strategy not in ("straddle", "strangle", "long_call", "long_put"):
        spread_width = round(strikes[-1] - strikes[0], 2)

    # Breakeven prices: where payoff crosses zero
    breakevens: list[float] = []
    for i in range(len(payoff_points) - 1):
        p0, pnl0 = payoff_points[i].price,  payoff_points[i].pnl
        p1, pnl1 = payoff_points[i+1].price, payoff_points[i+1].pnl
        if pnl0 * pnl1 < 0:  # sign change → zero crossing
            be = p0 + (p1 - p0) * (-pnl0) / (pnl1 - pnl0)
            breakevens.append(round(be, 2))
    # Deduplicate breakevens within $0.10 of each other
    deduped: list[float] = []
    for be in breakevens:
        if not deduped or abs(be - deduped[-1]) > 0.10:
            deduped.append(be)
    breakevens = deduped

    # Probability of Profit (PoP): VERY ROUGH estimate.
    # This is the fraction of the analyzed price range where PnL > 0,
    # assuming a uniform distribution. Overestimates PoP for OTM strategies.
    # A better model would weight by a log-normal distribution using IV and DTE.
    pop: float | None = None
    if pnls:
        profitable = sum(1 for pnl in pnls if pnl > 0)
        pop = round(profitable / len(pnls) * 100, 1)

    return max_profit, max_loss, spread_width, breakevens, pop, payoff_points


def _strategy_verdict_bias(strategy: str | None) -> str:
    if strategy is None:        return "neutral"
    if strategy in NEUTRAL_STRATEGIES:    return "neutral"
    if strategy in VOLATILITY_STRATEGIES: return "volatility"
    if strategy in BEARISH_STRATEGIES:    return "bearish"
    return "bullish"


def _build_verdict(
    analysis: dict, trade: dict, fib: dict,
    opts: dict | None, req: AnalyzeRequest, cached: bool,
) -> HoldFoldVerdict:
    symbol    = analysis.get("symbol", req.symbol)
    price     = float(analysis.get("price", 0.0))
    timestamp = analysis.get("timestamp")

    sig_summary = analysis.get("summary", {})
    bullish   = int(sig_summary.get("bullish", 0))
    bearish   = int(sig_summary.get("bearish", 0))
    avg_score = float(sig_summary.get("avg_score", 50))

    indicators = analysis.get("indicators", {})
    rsi      = indicators.get("rsi")
    macd_val = indicators.get("macd")
    adx      = indicators.get("adx")
    atr      = indicators.get("atr")
    atr_pct  = ((atr / price) * 100) if atr and price else None

    signals_raw: list[dict] = analysis.get("signals", [])
    volume_spike = None
    for s in signals_raw:
        if "VOLUME" in s.get("signal", ""):
            volume_spike = s.get("description", s["signal"])
            break

    # Trade plan
    plans: list[dict] = trade.get("trade_plans", [])
    plan       = plans[0] if plans else {}
    has_trades = bool(trade.get("has_trades", False))

    entry          = plan.get("entry_price")
    stop           = plan.get("stop_price")
    target         = plan.get("target_price")
    rr             = plan.get("risk_reward_ratio")
    bias           = plan.get("bias", "neutral")
    vehicle        = plan.get("vehicle")
    vehicle_notes  = plan.get("vehicle_notes")
    primary_signal = plan.get("primary_signal")
    supporting     = plan.get("supporting_signals", [])
    trade_timeframe = plan.get("timeframe")

    stop_pct   = round(abs((entry - stop)   / entry) * 100, 2) if entry and stop   else None
    upside_pct = round(abs((target - entry) / entry) * 100, 2) if entry and target else None

    suppression_codes = [
        str(s.get("code", s)) if isinstance(s, dict) else str(s)
        for s in trade.get("all_suppressions", [])
    ]
    suppressions = [
        SuppressionInfo(code=c, label=SUPPRESSION_LABELS.get(c, c))
        for c in suppression_codes
    ]

    # Derive effective bias
    effective_bias = bias
    if has_trades and effective_bias == "neutral" and entry is not None and target is not None and entry != target:
        effective_bias = "bullish" if target > entry else "bearish"

    # Options strategy overrides verdict logic
    strat = req.options_strategy
    if strat in NEUTRAL_STRATEGIES or strat in VOLATILITY_STRATEGIES:
        if avg_score >= HOLD_THRESHOLD:
            verdict_str = "HOLD EM"; confidence = min(avg_score * 1.05, MAX_CONF)
        elif avg_score >= NEUTRAL_THRESHOLD:
            verdict_str = "HOLD EM"; confidence = avg_score
        else:
            verdict_str = "NEUTRAL"; confidence = 50.0
        effective_bias = _strategy_verdict_bias(strat)
    elif has_trades and effective_bias == "bullish" and avg_score >= HOLD_THRESHOLD:
        verdict_str = "HOLD EM"; confidence = min(avg_score * 1.05, MAX_CONF)
    elif has_trades and effective_bias == "bearish" and avg_score >= HOLD_THRESHOLD:
        verdict_str = "FOLD EM"; confidence = min(avg_score * 1.05, MAX_CONF)
    elif bullish > bearish and avg_score >= NEUTRAL_THRESHOLD:
        verdict_str = "HOLD EM"; confidence = avg_score
    elif bearish > bullish and avg_score >= NEUTRAL_THRESHOLD:
        verdict_str = "FOLD EM"; confidence = avg_score
    elif bullish > bearish:
        verdict_str = "HOLD EM"; confidence = avg_score * 0.85
    elif bearish > bullish:
        verdict_str = "FOLD EM"; confidence = avg_score * 0.85
    else:
        verdict_str = "NEUTRAL"; confidence = 50.0

    if strat in BEARISH_STRATEGIES and verdict_str == "HOLD EM":
        verdict_str = "FOLD EM"

    vol_regime = _volatility_regime(atr, price)
    risk_lvl   = _risk_level(avg_score, rr, atr_pct)

    pnl_pct, pnl_dollar, vs_stop, vs_target = _position_eval(
        price, req.position_entry, stop, target, req.position_qty, req.position_side
    )

    fib_levels, fib_zones, nearest_support, nearest_resistance = _extract_fib_levels(fib, price)

    options_greeks = _extract_options_greeks(opts) if opts else None

    # Build options leg response
    options_legs_response: list[OptionsLegResponse] | None = None
    if req.options_legs:
        options_legs_response = [
            OptionsLegResponse(
                role=lg.role,
                strike=lg.strike,
                expiry=lg.expiry or (f"{req.dte}dte" if req.dte else None),
                premium=None,
            )
            for lg in req.options_legs
        ]

    # Payoff math — signed net premium: positive = credit, negative = debit
    # The sign is determined by premium_sign (sent from frontend) applied to the magnitude
    signed_premium: float | None = None
    if req.net_premium is not None and req.premium_sign is not None:
        signed_premium = req.net_premium * req.premium_sign
    elif req.net_premium is not None:
        signed_premium = req.net_premium  # trust whatever sign comes in

    max_profit = max_loss = spread_width = pop = None
    breakeven_prices: list[float] = []
    payoff_curve: list[PayoffPoint] = []

    if strat and req.options_legs:
        iv_val = options_greeks.iv if options_greeks else None
        max_profit, max_loss, spread_width, breakeven_prices, pop, payoff_curve = _compute_payoff_metrics(
            strategy=strat,
            req_legs=req.options_legs,
            net_premium=signed_premium,
            spot_low=req.spot_low,
            spot_high=req.spot_high,
            current_price=price,
            iv=iv_val,
            dte=req.dte,
        )

    strategy_note = STRATEGY_NOTES.get(strat) if strat else None

    # Summary
    parts = [f"{bullish} bullish / {bearish} bearish signals. Avg score {avg_score:.0f}/100."]
    if vol_regime not in ("unknown", "normal"):
        parts.append(f"{vol_regime.capitalize()} volatility environment.")
    if strat:
        dte_str = f" ({req.dte}d DTE)" if req.dte else ""
        parts.append(f"Strategy: {strat.replace('_', ' ').title()}{dte_str}.")
        if signed_premium is not None:
            parts.append(
                f"{'Credit' if signed_premium > 0 else 'Debit'}: ${abs(signed_premium):.2f}/share "
                f"(${abs(signed_premium) * 100:.0f}/contract)."
            )
        if max_profit is not None and max_profit < 1e9:
            parts.append(f"Max profit ${max_profit:.2f}/share.")
        if max_loss is not None and max_loss < 1e9:
            parts.append(f"Max loss ${max_loss:.2f}/share.")
        if breakeven_prices:
            parts.append(f"Breakeven{'s' if len(breakeven_prices) > 1 else ''}: "
                         f"{', '.join(f'${be:.2f}' for be in breakeven_prices)}.")
    if has_trades and all([entry, stop, target, rr]):
        parts.append(f"Underlying plan: entry ${entry:.2f} → target ${target:.2f}, stop ${stop:.2f} ({rr:.2f}x R/R).")
    elif suppressions:
        parts.append(f"No trade plan: {suppressions[0].label}.")
    if req.position_entry and pnl_pct is not None:
        parts.append(
            f"Your position: entered at ${req.position_entry:.2f}, "
            f"currently {'+' if pnl_pct >= 0 else ''}{pnl_pct:.1f}%."
        )
    if nearest_support:
        parts.append(f"Nearest Fib support ${nearest_support:.2f}.")
    if nearest_resistance:
        parts.append(f"Nearest Fib resistance ${nearest_resistance:.2f}.")

    return HoldFoldVerdict(
        symbol=symbol,
        asset_type=req.asset_type,
        verdict=verdict_str,
        confidence=round(confidence, 1),
        price=price,
        bias=effective_bias,
        risk_level=risk_lvl,
        cached=cached,
        bullish_count=bullish,
        bearish_count=bearish,
        avg_score=round(avg_score, 1),
        top_signals=signals_raw[:8],
        rsi=round(rsi, 2) if rsi else None,
        macd=round(macd_val, 4) if macd_val else None,
        adx=round(adx, 2) if adx else None,
        atr=round(atr, 4) if atr else None,
        volatility_regime=vol_regime,
        volume_spike=volume_spike,
        suppressions=suppressions,
        trade_timeframe=trade_timeframe,
        entry=entry, stop=stop, target=target,
        risk_reward=rr, stop_pct=stop_pct, upside_pct=upside_pct,
        vehicle=vehicle, vehicle_notes=vehicle_notes,
        primary_signal=primary_signal, supporting_signals=supporting,
        position_qty=req.position_qty,
        position_entry=req.position_entry,
        position_side=req.position_side,
        position_pnl_pct=pnl_pct,
        position_pnl_dollar=pnl_dollar,
        position_vs_stop=vs_stop,
        position_vs_target=vs_target,
        fib_levels=fib_levels,
        fib_confluence_zones=fib_zones,
        nearest_fib_support=nearest_support,
        nearest_fib_resistance=nearest_resistance,
        options_greeks=options_greeks,
        options_strategy=strat,
        options_legs=options_legs_response,
        dte=req.dte,
        net_premium=signed_premium,
        max_profit=max_profit,
        max_loss=max_loss,
        spread_width=spread_width,
        breakeven_prices=breakeven_prices or None,
        pop=pop,
        payoff_curve=payoff_curve or None,
        strategy_note=strategy_note,
        summary=" ".join(parts),
        data_timestamp=timestamp,
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/api/analyze", response_model=HoldFoldVerdict)
async def analyze(req: AnalyzeRequest):
    symbol = req.symbol.upper().strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol required")

    logger.info("Analyzing %s period=%s strategy=%s dte=%s premium=%s",
                symbol, req.period, req.options_strategy, req.dte, req.net_premium)

    cached = False
    try:
        analysis_raw, trade_raw, fib_raw = await asyncio.gather(
            _cached_or_fetch("analyze_security", symbol, lambda: analyze_security(symbol, period=req.period)),
            _cached_or_fetch("get_trade_plan",   symbol, lambda: get_trade_plan(symbol, period=req.period)),
            _cached_or_fetch("analyze_fibonacci", symbol, lambda: analyze_fibonacci(symbol, period=req.period)),
        )
        cached = bool(analysis_raw.get("cached", False))
    except Exception as e:
        logger.error("Analysis failed for %s: %s", symbol, e)
        raise HTTPException(status_code=503, detail=f"Analysis failed: {e}")

    # options_risk_analysis uses yfinance options chain — best-effort, non-fatal
    opts_raw = None
    if req.options_strategy:
        try:
            opts_raw = await _cached_or_fetch("options_risk_analysis", symbol, lambda: options_risk_analysis(symbol))
        except Exception as e:
            logger.warning("Options chain fetch failed for %s (non-fatal): %s", symbol, e)

    return _build_verdict(
        analysis=analysis_raw, trade=trade_raw,
        fib=fib_raw or {}, opts=opts_raw, req=req, cached=cached,
    )


@app.get("/health")
async def health():
    fs = _get_firestore()
    return {"status": "ok", "version": app.version, "firestore": fs is not None}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
