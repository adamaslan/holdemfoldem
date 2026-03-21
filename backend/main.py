"""
Hold Em or Fold Em — Backend v3
Evaluates existing and potential trades against live market data + technical signals.
Pulls from Firestore cache when available; falls back to live analysis.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ── Load .env from sibling mcp-finance1 ──────────────────────────────────────
_env_path = Path(__file__).parent.parent.parent / "gcp-app-w-mcp1" / "mcp-finance1" / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

# ── Add mcp-finance1 to path ──────────────────────────────────────────────────
_mcp_path = Path(__file__).parent.parent.parent / "gcp-app-w-mcp1" / "mcp-finance1"
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

app = FastAPI(title="Hold Em or Fold Em", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Firestore cache (optional — degrades gracefully) ─────────────────────────
_firestore: MCPFirestoreCache | None | bool = None  # False = tried and failed


def _get_firestore() -> MCPFirestoreCache | None:
    global _firestore
    if _firestore is None:
        try:
            _firestore = MCPFirestoreCache()
        except Exception as e:
            logger.warning("Firestore unavailable: %s", e)
            _firestore = False
    return _firestore if _firestore is not False else None


async def _cached_or_fetch(tool_name: str, cache_key: str, fetch_coro):
    """Try Firestore cache first; on miss run fetch_coro and write result back."""
    fs = _get_firestore()
    if fs:
        doc = fs.read_tool_result(tool_name, cache_key)
        if doc and doc.get("result"):
            logger.info("Firestore cache HIT: %s/%s", tool_name, cache_key)
            return doc["result"]
    result = await fetch_coro
    if fs and result:
        fs.write_tool_result(tool_name, cache_key, result)
    return result


# ── Thresholds ────────────────────────────────────────────────────────────────
HOLD_THRESHOLD = 60
NEUTRAL_THRESHOLD = 55
MAX_CONF = 95.0
KELLY_HALF = 0.5

SUPPRESSION_LABELS = {
    "STOP_TOO_WIDE": "Stop too wide (>3 ATR)",
    "STOP_TOO_TIGHT": "Stop too tight (<0.5 ATR)",
    "RR_UNFAVORABLE": "R:R below 1.5:1",
    "NO_CLEAR_INVALIDATION": "No clear invalidation level",
    "VOLATILITY_TOO_HIGH": "Volatility too high (ATR >3%)",
    "VOLATILITY_TOO_LOW": "Volatility too low (ATR <1.5%)",
    "NO_TREND": "No trend (ADX <20)",
    "CONFLICTING_SIGNALS": "Too many conflicting signals",
    "INSUFFICIENT_DATA": "Insufficient price history",
}

STRATEGY_NOTES = {
    "long_call": "Long call profits from a bullish move; defined risk = premium paid.",
    "long_put": "Long put profits from a bearish move; defined risk = premium paid.",
    "covered_call": "Covered call generates income; capped upside above strike.",
    "cash_secured_put": "Earn premium or acquire shares at a discount.",
    "bull_call_spread": "Buy lower call / sell higher call — cheaper bullish exposure.",
    "bear_put_spread": "Buy higher put / sell lower put — defined bearish play.",
    "call_credit_spread": "Collect premium betting price stays below sold strike.",
    "put_credit_spread": "Collect premium betting price stays above sold strike.",
    "iron_condor": "Neutral — profit in a range; sell OTM call & put spreads.",
    "straddle": "Profit from a large move either direction (earnings play).",
}


# ── Request / Response models ─────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    symbol: str
    period: str = "3mo"
    asset_type: str = "stock"           # stock | etf | options | crypto
    risk_profile: str = "moderate"      # conservative | moderate | aggressive
    options_strategy: str | None = None
    # Existing-position fields (all optional — user may or may not have a position)
    position_qty: float | None = Field(default=None, description="Shares / contracts held")
    position_entry: float | None = Field(default=None, description="Your average cost basis per share")
    position_side: str = Field(default="long", description="long | short")


class SuppressionInfo(BaseModel):
    code: str
    label: str


class FibLevel(BaseModel):
    name: str
    price: float
    distance_pct: float
    strength: str
    type: str  # RETRACEMENT | EXTENSION


class OptionsGreeks(BaseModel):
    iv: float | None
    pcr: float | None          # put/call ratio
    delta_atm: float | None
    theta_atm: float | None
    vega_atm: float | None


class HoldFoldVerdict(BaseModel):
    # ── Core ──────────────────────────────────────────────────────────────────
    symbol: str
    asset_type: str
    verdict: str                 # HOLD EM | FOLD EM | NEUTRAL
    confidence: float
    price: float
    bias: str
    risk_level: str              # low | medium | high | extreme
    cached: bool                 # True if result came from Firestore

    # ── Signal stats ──────────────────────────────────────────────────────────
    bullish_count: int
    bearish_count: int
    avg_score: float
    top_signals: list[dict]

    # ── Market indicators (raw) ───────────────────────────────────────────────
    rsi: float | None
    macd: float | None
    adx: float | None
    atr: float | None
    volatility_regime: str       # low | normal | elevated | extreme
    volume_spike: str | None     # e.g. "2.3x average"

    # ── Suppression reasons (why no clean trade plan) ─────────────────────────
    suppressions: list[SuppressionInfo]

    # ── Best trade plan from backend ─────────────────────────────────────────
    trade_timeframe: str | None  # swing | day | scalp
    entry: float | None
    stop: float | None
    target: float | None
    risk_reward: float | None
    stop_pct: float | None
    upside_pct: float | None
    vehicle: str | None          # stock | option_call | option_put | option_spread
    vehicle_notes: str | None
    primary_signal: str | None
    supporting_signals: list[str]

    # ── Your position P&L (only if user supplied entry) ───────────────────────
    position_qty: float | None
    position_entry: float | None
    position_side: str
    position_pnl_pct: float | None    # unrealised % gain/loss
    position_pnl_dollar: float | None # unrealised $ per share
    position_vs_stop: str | None      # "Above stop ✓" | "BELOW STOP ✗"
    position_vs_target: str | None    # "Below target" | "AT/ABOVE TARGET"

    # ── Fibonacci key levels ──────────────────────────────────────────────────
    fib_levels: list[FibLevel]
    fib_confluence_zones: list[dict]
    nearest_fib_support: float | None
    nearest_fib_resistance: float | None

    # ── Options metrics (when asset_type == options) ──────────────────────────
    options_greeks: OptionsGreeks | None
    options_strategy: str | None

    # ── Summary ───────────────────────────────────────────────────────────────
    summary: str
    data_timestamp: str | None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _volatility_regime(atr: float | None, price: float) -> str:
    if not atr or price == 0:
        return "unknown"
    pct = (atr / price) * 100
    if pct < 1.0:
        return "low"
    if pct < 2.5:
        return "normal"
    if pct < 5.0:
        return "elevated"
    return "extreme"


def _risk_level(avg_score: float, rr: float | None, atr_pct: float | None) -> str:
    score = 0
    if avg_score < 50:
        score += 2
    elif avg_score < 60:
        score += 1
    if rr is not None and rr < 1.5:
        score += 1
    if atr_pct is not None and atr_pct > 3.0:
        score += 1
    if atr_pct is not None and atr_pct > 5.0:
        score += 1
    return ["low", "medium", "high", "extreme"][min(score, 3)]


def _position_eval(
    price: float,
    entry: float | None,
    stop: float | None,
    target: float | None,
    qty: float | None,
    side: str,
) -> tuple[float | None, float | None, str | None, str | None]:
    """Return (pnl_pct, pnl_dollar, vs_stop_label, vs_target_label)."""
    if not entry:
        return None, None, None, None

    mult = 1 if side == "long" else -1
    pnl_pct = ((price - entry) / entry) * 100 * mult
    pnl_dollar = (price - entry) * mult

    vs_stop = None
    if stop:
        if side == "long":
            vs_stop = "Above stop ✓" if price > stop else "BELOW STOP ✗"
        else:
            vs_stop = "Below stop ✓" if price < stop else "ABOVE STOP ✗"

    vs_target = None
    if target:
        if side == "long":
            vs_target = "AT/ABOVE TARGET ✓" if price >= target else f"${target - price:.2f} to target"
        else:
            vs_target = "AT/BELOW TARGET ✓" if price <= target else f"${price - target:.2f} to target"

    return round(pnl_pct, 2), round(pnl_dollar, 4), vs_stop, vs_target


def _extract_fib_levels(fib_data: dict, current_price: float) -> tuple[list[FibLevel], list[dict], float | None, float | None]:
    """Pull top Fibonacci levels and confluence zones from analyze_fibonacci output."""
    levels_raw = fib_data.get("levels", [])
    zones_raw = fib_data.get("confluenceZones", [])

    levels = []
    for lv in levels_raw[:8]:  # top 8 nearest levels
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

    # Nearest support (below price) and resistance (above price)
    below = [lv for lv in levels if lv.price < current_price]
    above = [lv for lv in levels if lv.price > current_price]
    nearest_support = max((lv.price for lv in below), default=None)
    nearest_resistance = min((lv.price for lv in above), default=None)

    # Top 3 confluence zones
    top_zones = []
    for z in zones_raw[:3]:
        top_zones.append({
            "price": round(z.get("price", 0), 4),
            "strength": z.get("strength", ""),
            "signal_count": z.get("signalCount", 0),
            "confluence_score": round(z.get("confluenceScore", 0), 2),
        })

    return levels, top_zones, nearest_support, nearest_resistance


def _extract_options_greeks(options_data: dict) -> OptionsGreeks | None:
    if not options_data:
        return None
    metrics = options_data.get("metrics", options_data)
    iv = metrics.get("implied_volatility") or metrics.get("iv") or metrics.get("avg_iv")
    pcr = metrics.get("put_call_ratio") or metrics.get("pcr")
    delta = metrics.get("delta_atm") or metrics.get("delta")
    theta = metrics.get("theta_atm") or metrics.get("theta")
    vega = metrics.get("vega_atm") or metrics.get("vega")
    return OptionsGreeks(
        iv=round(iv, 4) if iv else None,
        pcr=round(pcr, 3) if pcr else None,
        delta_atm=round(delta, 4) if delta else None,
        theta_atm=round(theta, 4) if theta else None,
        vega_atm=round(vega, 4) if vega else None,
    )


def _build_verdict(
    analysis: dict,
    trade: dict,
    fib: dict,
    opts: dict | None,
    req: AnalyzeRequest,
    cached: bool,
) -> HoldFoldVerdict:
    symbol = analysis.get("symbol", req.symbol)
    price = float(analysis.get("price", 0.0))
    timestamp = analysis.get("timestamp")

    sig_summary = analysis.get("summary", {})
    bullish = int(sig_summary.get("bullish", 0))
    bearish = int(sig_summary.get("bearish", 0))
    avg_score = float(sig_summary.get("avg_score", 50))

    # Raw indicators
    indicators = analysis.get("indicators", {})
    rsi = indicators.get("rsi")
    macd_val = indicators.get("macd")
    adx = indicators.get("adx")
    atr = indicators.get("atr")
    atr_pct = ((atr / price) * 100) if atr and price else None

    # Volume spike description
    signals_raw: list[dict] = analysis.get("signals", [])
    volume_spike = None
    for s in signals_raw:
        if "VOLUME" in s.get("signal", ""):
            volume_spike = s.get("description", s["signal"])
            break

    # Trade plan
    plans: list[dict] = trade.get("trade_plans", [])
    plan = plans[0] if plans else {}
    has_trades = bool(trade.get("has_trades", False))

    entry = plan.get("entry_price")
    stop = plan.get("stop_price")
    target = plan.get("target_price")
    rr = plan.get("risk_reward_ratio")
    bias = plan.get("bias", "neutral")
    vehicle = plan.get("vehicle")
    vehicle_notes = plan.get("vehicle_notes")
    primary_signal = plan.get("primary_signal")
    supporting = plan.get("supporting_signals", [])
    trade_timeframe = plan.get("timeframe")

    stop_pct = round(abs((entry - stop) / entry) * 100, 2) if entry and stop else None
    upside_pct = round(abs((target - entry) / entry) * 100, 2) if entry and target else None

    # Suppressions
    suppression_codes = [
        str(s.get("code", s)) if isinstance(s, dict) else str(s)
        for s in trade.get("all_suppressions", [])
    ]
    suppressions = [
        SuppressionInfo(code=c, label=SUPPRESSION_LABELS.get(c, c))
        for c in suppression_codes
    ]

    # Derive trade plan direction from prices when bias is neutral but a plan exists.
    # This prevents a bearish plan (target < entry) from producing a HOLD EM verdict.
    effective_bias = bias
    if has_trades and effective_bias == "neutral" and entry and target:
        effective_bias = "bullish" if target > entry else "bearish"

    # Verdict logic
    if has_trades and effective_bias == "bullish" and avg_score >= HOLD_THRESHOLD:
        verdict = "HOLD EM"
        confidence = min(avg_score * 1.05, MAX_CONF)
    elif has_trades and effective_bias == "bearish" and avg_score >= HOLD_THRESHOLD:
        verdict = "FOLD EM"
        confidence = min(avg_score * 1.05, MAX_CONF)
    elif bullish > bearish and avg_score >= NEUTRAL_THRESHOLD:
        verdict = "HOLD EM"
        confidence = avg_score
    elif bearish > bullish and avg_score >= NEUTRAL_THRESHOLD:
        verdict = "FOLD EM"
        confidence = avg_score
    elif bullish > bearish:
        verdict = "HOLD EM"
        confidence = avg_score * 0.85
    elif bearish > bullish:
        verdict = "FOLD EM"
        confidence = avg_score * 0.85
    else:
        verdict = "NEUTRAL"
        confidence = 50.0

    vol_regime = _volatility_regime(atr, price)
    risk_lvl = _risk_level(avg_score, rr, atr_pct)

    # Position P&L vs market plan levels
    pnl_pct, pnl_dollar, vs_stop, vs_target = _position_eval(
        price, req.position_entry, stop, target, req.position_qty, req.position_side
    )

    # Fibonacci
    fib_levels, fib_zones, nearest_support, nearest_resistance = _extract_fib_levels(fib, price)

    # Options
    options_greeks = _extract_options_greeks(opts) if opts else None

    # Summary
    parts = [f"{bullish} bullish / {bearish} bearish signals. Avg score {avg_score:.0f}/100."]
    if vol_regime not in ("unknown", "normal"):
        parts.append(f"{vol_regime.capitalize()} volatility environment.")
    if has_trades and all([entry, stop, target, rr]):
        parts.append(f"Plan: entry ${entry:.2f} → target ${target:.2f}, stop ${stop:.2f} ({rr:.2f}x R/R).")
    elif suppressions:
        parts.append(f"No trade plan: {suppressions[0].label}.")
    if req.position_entry:
        parts.append(
            f"Your position: entered at ${req.position_entry:.2f}, "
            f"currently {'+' if (pnl_pct or 0) >= 0 else ''}{pnl_pct:.1f}%."
        )
    if nearest_support:
        parts.append(f"Nearest Fib support ${nearest_support:.2f}.")
    if nearest_resistance:
        parts.append(f"Nearest Fib resistance ${nearest_resistance:.2f}.")
    if req.options_strategy and req.options_strategy in STRATEGY_NOTES:
        parts.append(f"Strategy: {STRATEGY_NOTES[req.options_strategy]}")

    return HoldFoldVerdict(
        symbol=symbol,
        asset_type=req.asset_type,
        verdict=verdict,
        confidence=round(confidence, 1),
        price=price,
        bias=bias,
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
        entry=entry,
        stop=stop,
        target=target,
        risk_reward=rr,
        stop_pct=stop_pct,
        upside_pct=upside_pct,
        vehicle=vehicle,
        vehicle_notes=vehicle_notes,
        primary_signal=primary_signal,
        supporting_signals=supporting,
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
        options_strategy=req.options_strategy,
        summary=" ".join(parts),
        data_timestamp=timestamp,
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/api/analyze", response_model=HoldFoldVerdict)
async def analyze(req: AnalyzeRequest):
    symbol = req.symbol.upper().strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol required")

    logger.info("Analyzing %s (%s) period=%s risk=%s", symbol, req.asset_type, req.period, req.risk_profile)

    cached = False
    try:
        # Run analyze_security + get_trade_plan in parallel; also run Fibonacci.
        # Options analysis only when asset_type == options.
        fib_coro = _cached_or_fetch(
            "analyze_fibonacci", symbol,
            analyze_fibonacci(symbol, period=req.period)
        )
        opts_coro = (
            _cached_or_fetch("options_risk_analysis", symbol, options_risk_analysis(symbol))
            if req.asset_type == "options"
            else asyncio.sleep(0, result=None)
        )

        analysis_raw, trade_raw, fib_raw, opts_raw = await asyncio.gather(
            _cached_or_fetch("analyze_security", symbol, analyze_security(symbol, period=req.period)),
            _cached_or_fetch("get_trade_plan", symbol, get_trade_plan(symbol, period=req.period)),
            fib_coro,
            opts_coro,
        )

        # Detect if all data came from cache
        cached = bool(analysis_raw.get("cached", False))

    except Exception as e:
        logger.error("Analysis failed for %s: %s", symbol, e)
        raise HTTPException(status_code=503, detail=f"Analysis failed: {e}")

    return _build_verdict(
        analysis=analysis_raw,
        trade=trade_raw,
        fib=fib_raw or {},
        opts=opts_raw,
        req=req,
        cached=cached,
    )


@app.get("/health")
async def health():
    fs = _get_firestore()
    return {
        "status": "ok",
        "version": app.version,
        "firestore": fs is not None,
    }
