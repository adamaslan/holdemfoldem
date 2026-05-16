# Debug Log: Scoring and Signals Not Working

**Date:** 2026-05-16  
**Branch:** feat/robustness-roadmap-implementation  
**Reported Issue:** UI shows "Bullish 0 signals · Avg Score 0/100 · Bearish 0 signals" — scoring and signals not working

---

## Root Cause Analysis

### Symptom
- UI verdict card displays: `neutral bias · — · Conviction 50% · Bullish 0 signals · Avg Score 0/100 · Bearish 0 signals`
- Confidence is 50% (default NEUTRAL fallback)
- All signal counts are zero

### Diagnosis Flow

1. **Verified backend API works for common symbols**: Direct `POST /api/analyze` calls for AAPL, TSLA, SPY all return correct `bullish_count`, `bearish_count`, `avg_score`.

2. **Verified Next.js proxy works**: Calls through `localhost:3001/api/analyze` also return correct data.

3. **Traced to empty `ranked_signals`**: When `detect_all_signals()` returns an empty list (no signals detected for a given symbol/period), the `avg_score` defaults to `0` in `server.py`:
   ```python
   avg_score = (
       sum(s.ai_score or 50 for s in ranked_signals) / len(ranked_signals)
       if ranked_signals
       else 0  # BUG: should be 50 (neutral), not 0
   )
   ```
   This `0` is written into the Firestore cache and returned as `summary.avg_score = 0`.

4. **In `main.py` `_build_verdict`**: The `avg_score` is read with a default fallback of `50`, but since `0` is an explicit value (not missing), `float(sig_summary.get("avg_score", 50))` evaluates to `0.0`.

5. **Downstream consequences of `avg_score = 0`**:
   - `risk_level` calculated as "high" (score < 50 adds 2 points)
   - Verdict confidence = `0 * 0.85 = 0%` when displayed
   - UI shows "0/100" avg score chip

### Secondary Issues Found

- **ATR missing from indicators**: `server.py` builds its own `indicators` dict with only `rsi`, `macd`, `adx`, `volume` — does NOT include `atr`. The `main.py` reads `indicators.get("atr")` → `None` → `volatility_regime = "unknown"`. This is cosmetic but should be fixed.

- **Cache key excludes period**: `_cached_or_fetch` in `main.py` uses `symbol` as the cache key but not `period`. A cached result for AAPL with `3mo` period will be returned for any other period (e.g., `1y`) within the 1-hour TTL.

---

## Fixes Applied

### Fix 1: `server.py` — avg_score defaults to 50 when no signals

**File:** `/Users/adamaslan/code/gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp/server.py`  
**Line:** ~702

```python
# Before
avg_score = (
    sum(s.ai_score or 50 for s in ranked_signals) / len(ranked_signals)
    if ranked_signals
    else 0
)

# After
avg_score = (
    sum(s.ai_score or 50 for s in ranked_signals) / len(ranked_signals)
    if ranked_signals
    else 50  # neutral baseline when no signals detected
)
```

### Fix 2: `main.py` — guard against explicit 0 avg_score from cache

**File:** `/Users/adamaslan/code/holdemfoldemapp/backend/main.py`  
**Line:** ~832

```python
# Before
avg_score = float(sig_summary.get("avg_score", 50))

# After
avg_score = float(sig_summary.get("avg_score") or 50)  # 0 → 50 when no signals
```

---

## Actions Taken

1. Investigated backend response via direct curl calls — confirmed backend works for standard symbols.
2. Traced issue to `avg_score = 0` when `ranked_signals` is empty.
3. Applied Fix 1 to `server.py` (MCP finance module).
4. Applied Fix 2 to `backend/main.py` (holdemfoldemapp backend).
5. Restarted backend process (PID 25884 → 44736).
6. Discovered `SignalList.__init__` bug causing `TypeError: list expected at most 1 argument, got 3` on restart.
7. Applied Fix 3 to `signals.py` — added `__init__` to `SignalList`.
8. Restarted backend again (PID 44736 → 44925). Final verification: AAPL returns 25 bullish / 20 bearish / avg_score 62.9 ✓

---

### Fix 3: `signals.py` — SignalList missing `__init__`

**File:** `/Users/adamaslan/code/gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp/signals.py`  
**Line:** ~884

The `SignalList(list)` subclass used `__new__` to initialize but Python still calls `list.__init__` with all 3 args `(signals, degraded, warnings)`, causing `TypeError: list expected at most 1 argument, got 3`.

```python
# Added __init__ to prevent list.__init__ from receiving extra args
def __init__(self, signals: list[MutableSignal], degraded: bool, warnings: list[str]):
    super().__init__(signals)
```

---

## Outstanding Issues

- **Cache key excludes period**: `_cached_or_fetch` in `main.py` uses `symbol` as the Firestore cache key but not `period`. A cached result for AAPL with `3mo` will be returned for any other period within the 1-hour TTL.
- **ATR not included in indicators**: `server.py` builds its own `indicators` dict with only `rsi`, `macd`, `adx`, `volume` — does NOT include `atr`, causing `volatility_regime = "unknown"` in the UI.

---

## How to Reproduce the Bug (Before Fix)

1. Analyze a symbol/period combination that has no technical signals (e.g., very low-volatility instrument, very short period with insufficient data).
2. The response will show `avg_score: 0`, `bullish_count: 0`, `bearish_count: 0`.
3. UI will display "0 signals · 0/100 · 0 signals" with NEUTRAL/50% confidence.

---

## Related Files

- [backend/main.py](../backend/main.py) — `_build_verdict()`, `_cached_or_fetch()`
- [mcp-finance1/src/technical_analysis_mcp/server.py](../../gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp/server.py) — `analyze_security()`
- [mcp-finance1/src/technical_analysis_mcp/signals.py](../../gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp/signals.py) — `detect_all_signals()`, `SignalList`
- [mcp-finance1/src/technical_analysis_mcp/ranking.py](../../gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp/ranking.py) — `rank_signals()`
