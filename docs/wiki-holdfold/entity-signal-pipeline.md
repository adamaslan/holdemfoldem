---
date: 2026-05-31
type: entity
tags: [signals, pipeline, indicators, detectors, ranking, verdict]
sources: [../docs/signal-pipeline.md, ../backend/main.py, ../../gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp/]
---

# Entity: Signal Pipeline

The 4-stage technical analysis core that transforms raw OHLCV price data into a `HoldFoldVerdict`. Lives in `gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp/` — shared code, not owned by holdemfoldemapp. The backend calls it via `asyncio.gather(analyze_security, get_trade_plan, analyze_fibonacci)`.

## What it is

**Stage 1 — Indicator Calculation** (`indicators.py`)

`calculate_all_indicators()` produces 80+ DataFrame columns across 11 functions:

| Group | Key outputs |
|-------|-------------|
| Moving averages | `SMA_5/10/20/50/100/200`, `EMA_5/10/20/50/100/200` |
| Momentum | `RSI` (14), `MACD`/`Signal`/`Hist` (12/26/9), `Stoch_K/D` (14/3) |
| Volatility | `BB_Upper/Middle/Lower/Width` (20, 2σ), `ATR` (14) |
| Trend | `ADX`, `Plus_DI`, `Minus_DI` (14) |
| Volume | `Volume_MA_20/50`, `OBV` |
| Derived | `Price_Change`, `Volatility`, `Dist_SMA_10/20/50/200` |

`calculate_expanded_indicators()` adds ~40 more columns: multi-period RSI (5/10/20/30), 3 extra MACD param sets, Ichimoku Cloud (9/26/52), CMF, 16 Bollinger Band variants (4 periods × 4 σ), 10 rolling high/low windows, extended MA distances.

**Stage 2 — Signal Detection** (`signals.py`)

`detect_all_signals()` runs 18 `SignalDetector` classes in sequence. Each detector is pure (no I/O, no shared state) and wrapped in try/except — a single failure doesn't crash the pipeline.

| Category | Detectors | Signal count |
|----------|-----------|--------------|
| `MA_CROSS` / `MA_TREND` | MovingAverage, ExpandedMACross | Golden/Death Cross + 11 MA pairs |
| `RSI` | RSI, MultiRSI | 5 periods × 3 threshold pairs + 50-line crosses |
| `MACD` | MACD, MultiMACD | Signal/zero/histogram crosses × 4 param sets |
| `BOLLINGER` / `BB_BREAKOUT` | BollingerBand, BBExpansion | Standard band touch + 4×4 breakout variants |
| `STOCHASTIC` | Stochastic, StochasticCross | OS/OB levels + K/D cross in extreme zones |
| `VOLUME` | Volume, VolumeDivergence | 2X/3X spikes + 10-bar divergence |
| `TREND` | Trend | ADX > 25 up/downtrend |
| `PRICE_ACTION` | PriceAction | ±5% daily moves |
| `ICHIMOKU` | Ichimoku | TK cross, kumo position/color |
| `OBV_CMF` | OBVCMF | OBV divergence/EMA cross, CMF level/zero-cross |
| `RANGE` | HLProximity | Within 1%/2%/5% of 5 rolling high/low windows |
| `MA_DISTANCE` | MADistanceExpanded | >5%/10%/15%/20% from 6 SMA periods |

**Stage 3 — Ranking** (`ranking.py`)

`rank_signals()` assigns a score 1–100 to each signal. Two implementations, one always-available:

- `RuleBasedRanking` — keyword scoring: EXTREME=85, STRONG=75, SIGNIFICANT=65, BULLISH/BEARISH=55, default=50. Category bonus +10 for `MA_CROSS`, `MACD`, `VOLUME`. Max score: 95.
- `GeminiRanking` — batch JSON prompt to Gemini API; protected by circuit breaker (opens after 5 failures in 60s; fallback to rule-based). Malformed JSON response also falls back.

**Stage 3.5 — Suppression Filtering** (`backend/main.py` → `_build_verdict`)

Before verdict logic runs, a suppression pipeline (inside `get_trade_plan`) evaluates whether a tradeable plan can be emitted, attaching coded reasons when it cannot. Each suppression has a machine code and a human-readable label. Suppression governs **trade-plan emission only** — it does *not* remove signals from `avg_score` or the `bullish`/`bearish` counts, which are computed earlier in `analyze_security` over all ranked signals. The `HoldFoldVerdict` includes a `suppressions` field (`list[SuppressionInfo]`, each `{code, label}`) listing all active suppression codes + labels. This stage is not configurable by the caller — it runs unconditionally.

The complete suppression-code set is the `SUPPRESSION_LABELS` dict in `backend/main.py:131-141` (9 codes). The codes originate upstream: `_build_verdict` reads `trade["all_suppressions"]` from the `get_trade_plan` result and maps each code through `SUPPRESSION_LABELS` (an unknown code falls back to using the raw code as its own label).

| Code | Label / trigger |
|------|-----------------|
| `STOP_TOO_WIDE` | Stop too wide (>3 ATR) |
| `STOP_TOO_TIGHT` | Stop too tight (<0.5 ATR) |
| `RR_UNFAVORABLE` | R:R below 1.5:1 |
| `NO_CLEAR_INVALIDATION` | No clear invalidation level |
| `VOLATILITY_TOO_HIGH` | Volatility too high (ATR >3%) |
| `VOLATILITY_TOO_LOW` | Volatility too low (ATR <1.5%) |
| `NO_TREND` | No trend (ADX <20) |
| `CONFLICTING_SIGNALS` | Too many conflicting signals |
| `INSUFFICIENT_DATA` | Insufficient price history |

**Stage 4 — Verdict Construction** (`backend/main.py` → `_build_verdict`)

Combines ranked signals + trade plan + options data + request into `HoldFoldVerdict`. Full decision tree (all 7 paths, in evaluation order):

```
1. Options strategy is NEUTRAL or VOLATILITY strategy?
   └─ avg_score ≥ 60  → HOLD EM,  confidence = min(avg_score × 1.05, 95)
   └─ avg_score ≥ 55  → HOLD EM,  confidence = avg_score
   └─ else            → NEUTRAL,  confidence = 50.0
   (then sets effective_bias = strategy bias; skips paths 2–6)

2. Trade plan present AND effective_bias == "bullish" AND avg_score ≥ 60?
   └─ HOLD EM, confidence = min(avg_score × 1.05, 95)

3. Trade plan present AND effective_bias == "bearish" AND avg_score ≥ 60?
   └─ FOLD EM, confidence = min(avg_score × 1.05, 95)

4. No trade plan AND bullish_count > bearish_count AND avg_score ≥ 55?
   └─ HOLD EM, confidence = avg_score

5. No trade plan AND bearish_count > bullish_count AND avg_score ≥ 55?
   └─ FOLD EM, confidence = avg_score

6. Fallback — below 55 threshold but directional dominance exists:
   └─ bullish_count > bearish_count → HOLD EM, confidence = avg_score × 0.85
   └─ bearish_count > bullish_count → FOLD EM, confidence = avg_score × 0.85
   └─ tied                          → NEUTRAL,  confidence = 50.0

7. Bearish strategy override (applied after paths 1–6):
   └─ If options_strategy ∈ BEARING_STRATEGIES AND verdict == HOLD EM → flip to FOLD EM
```

Constants: `HOLD_THRESHOLD = 60`, `NEUTRAL_THRESHOLD = 55`, `MAX_CONF = 95`.

After verdict:
- Clamps confidence to [0, 95]
- Computes `risk_level` from avg_score, R/R ratio, and ATR%
- Adds position P&L (multi-lot FIFO/LIFO/avg) if `position_lots` provided — **local only, not on Cloud Run**
- Runs options payoff engine if `options_strategy` set — **local only, not on Cloud Run**

**Indicator exposure gap**: Stage 1 computes ~41 indicator readings internally (`calculate_all_indicators` = 15 core + `calculate_expanded_indicators` ≈ 26 more: Stochastic K/D, OBV, CMF, all Bollinger variants, 10 rolling high/low windows, extended MA distances, vol ratio, etc.). The `HoldFoldVerdict` exposes only 4 of these: `rsi`, `macd`, `adx`, `atr`. The other 37 are used inside signal detection but are not returned to the caller.

## Where used

- [[entity-backend-api]] — calls `analyze_security`, `get_trade_plan`, `analyze_fibonacci` via `asyncio.gather`
- [[entity-options-payoff]] — runs as a final step after verdict logic if `options_strategy` is set
- [[entity-mcp-finance]] — the shared library that implements stages 1–3
- `gcp3-mobile/docs/wiki-mobile/entity-client-holdfold.md` — mobile client that consumes the `HoldFoldVerdict` output

## Known failures

1. **Detector failure budget** — governed by `MAX_DETECTOR_FAILURES = 4` (`config.py:200`): if more than 4 of the 18 detectors fail, `verdict.degraded=True` is set. Each detector also has a `DETECTOR_TIMEOUT_MS = 500` wall-clock budget. The UI shows a degraded badge. This has not been triggered in production but is a documented threshold.
2. **Gemini ranking circuit breaker** — opens after 5 API failures in 60s; stays open 5 min. During open state, all verdicts use rule-based ranking. Users see no difference but scoring depth is reduced.
3. **Insufficient history** — symbols with fewer than `MIN_BARS_BY_PERIOD[period]` bars raise `InsufficientDataError` in the mcp `data.py` validation gate (`data.py:231-237`; e.g. 60 bars for `3mo`, 200 for `1y`). In the holdfold backend this is **not** surfaced as a typed 422 — `analyze()` wraps the whole `asyncio.gather` in a bare `except Exception` and returns **503 `Analysis failed: ...`** (`backend/main.py:1179-1181`). Affects newer listings and low-volume symbols on long periods.

## Open questions

- Should `calculate_expanded_indicators` be gated behind a request parameter (e.g. `depth="full"`) to reduce latency for simple use cases?
- The `shouldRetry` heuristic in yfinance error handling checks if the error message contains `'4'` — fragile string match; should be replaced with typed `YFRateLimitError` / status-code check.

## See also

- [[entity-backend-api]] — the FastAPI layer that orchestrates the pipeline
- [[entity-firestore-cache]] — caches `analyze_security` results to avoid re-running the pipeline
- [[entity-mcp-finance]] — the shared library that owns stages 1–3
- [[entity-options-payoff]] — the payoff engine called from stage 4
- [[concept-signal-scoring]] — the scoring and ranking rules in detail
- [[decision-rule-based-ranking-fallback]] — why Gemini is optional, not required
