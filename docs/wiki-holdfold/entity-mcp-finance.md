---
date: 2026-05-31
type: entity
tags: [mcp, signals, shared-library, cross-repo]
sources: [../../gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp/server.py, ../backend/main.py]
---

# Entity: MCP Finance Library (`gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp/`)

The shared Python library that implements stages 1–3 of the [[entity-signal-pipeline]]. Lives in the `gcp-app-w-mcp1` repo, not in `holdemfoldemapp`. The backend imports it at runtime via a `sys.path.insert` pointing to `~/code/gcp-app-w-mcp1/mcp-finance1` locally, or to `/app` when running in the Cloud Run image (where `deploy-backend.sh` copies the source into the build context).

## What it is

The four exported functions the holdemfoldemapp backend calls:

```python
from src.technical_analysis_mcp.server import (
    analyze_security,    # stages 1-3: fetch + indicators + detectors + ranking
    get_trade_plan,      # entry / stop / target / R/R ratio
    analyze_fibonacci,   # Fibonacci retracement levels + confluence zones
    options_risk_analysis,  # Greeks: IV, PCR, delta, theta, vega
)
from src.technical_analysis_mcp.cache.firestore_cache import MCPFirestoreCache
```

**`analyze_security(symbol, period, use_ai=False)`**
- Fetches OHLCV via yfinance (Alpha Vantage fallback)
- Runs `calculate_all_indicators` → **15 core indicator readings**: `rsi`, `macd`, `macd_signal`, `macd_histogram`, `adx`, `plus_di`, `minus_di`, `stoch_k`, `stoch_d`, `bb_upper`, `bb_middle`, `bb_lower`, `atr`, `volume`, `volume_ma_20`
- Runs `calculate_expanded_indicators` → **~26 additional indicator readings**: multi-period RSI (5/10/20/30), 3 extra MACD param sets, Ichimoku Cloud (Tenkan/Kijun/Senkou A&B), CMF, 16 Bollinger Band variants (4 periods × 4σ), 10 rolling high/low windows, extended MA distances, OBV, vol ratio
- Total internal indicator readings: **~41**. Of these, **only 4 are returned in `HoldFoldVerdict`**: `rsi`, `macd`, `adx`, `atr`. The other 37 are consumed by signal detectors and then discarded.
- Runs `detect_all_signals` (18 detectors) → 150+ `Signal` objects, each with `signal` (name), `strength` (e.g. `STRONG_BULLISH`), `category`, `ai_score`, `description`
- Signal collapsing: `bullish_count` = count of Signal objects where `strength` contains `BULLISH`; `bearish_count` = count where `strength` contains `BEARISH`. No explicit `is_bullish` flag exists — directionality is inferred from the strength keyword. Neutral-strength signals (e.g. `SIGNIFICANT_RANGE`) affect `avg_score` but contribute to neither count.
- Runs `rank_signals` (rule-based or Gemini) → each Signal gets a score 1–100; `avg_score` = mean across all ranked signals
- Returns a dict with `signals` (list), `summary` (`bullish_count`, `bearish_count`, `avg_score`, `total_signals`), `indicators` (the 4-field subset)

**`get_trade_plan(symbol, period)`**
- Computes entry (current price), stop (ATR-based), target (R/R = 2:1 default), and vehicle recommendation

**`analyze_fibonacci(symbol, period)`**
- Identifies swing high/low over the period
- Returns retracement levels (23.6%, 38.2%, 50%, 61.8%, 78.6%) + confluence zones

**`options_risk_analysis(symbol)`**
- Fetches options chain from yfinance
- Returns Greeks (IV, PCR, delta, theta, vega) for the nearest ATM contract

The Cloud Run Dockerfile (`backend/cloud-run/`) copies `mcp-finance1/src/` + `mcp-finance1/fibonacci/` into the image at build time:
```
COPY src/technical_analysis_mcp/ /app/src/technical_analysis_mcp/
```

**Import-path divergence between the two backends.** The local `backend/main.py` imports `from src.technical_analysis_mcp.server import ...` (`main.py:42`), while the Cloud Run `backend/cloud-run/main.py` imports `from technical_analysis_mcp.server import ...` (`cloud-run/main.py:18`) — note the missing `src.` prefix. The two entrypoints therefore assume different on-disk layouts (`/app/src/...` for local-style vs `/app/technical_analysis_mcp/...` for Cloud Run), and the Cloud Run variant imports only `analyze_security` and `get_trade_plan` — not `analyze_fibonacci` or `options_risk_analysis`.

## Where used

- [[entity-signal-pipeline]] — calls these four functions
- [[entity-backend-api]] — `asyncio.gather(analyze_security, get_trade_plan, analyze_fibonacci, options_risk_analysis?)` is the core of `/api/analyze`
- [[entity-firestore-cache]] — `MCPFirestoreCache` from this library wraps `analyze_security` results

## Known failures

1. **Cross-repo path coupling** — local dev requires `gcp-app-w-mcp1` to be checked out at `~/code/gcp-app-w-mcp1`. If the path differs, `sys.path.insert` silently fails and the import crashes at startup.
2. **`os.chdir(str(_mcp_path))`** — the backend changes working directory to the mcp source root on import. This is needed for relative file references inside the mcp library but means the process's CWD is `mcp-finance1/` at runtime, not `holdemfoldemapp/backend/`. Any relative-path file access in the backend itself will break.
3. **No pinned version** — the backend always imports from whatever is on disk at `~/code/gcp-app-w-mcp1`. There is no lockfile or version pin. A breaking change in `mcp-finance1` will silently affect holdemfoldemapp.

## Open questions

- Should `mcp-finance1` be vendored (copied into `holdemfoldemapp/backend/`) or published as a private package to give holdemfoldemapp a stable, versioned dependency?
- The `os.chdir` side effect is fragile. Can the mcp library be refactored to use `Path(__file__).parent`-relative paths instead?

## See also

- [[entity-signal-pipeline]] — the consumer of this library
- [[entity-backend-api]] — the FastAPI layer that imports and orchestrates these functions
- [[decision-mcp-finance-as-shared-lib]] — why the analysis code lives in gcp-app-w-mcp1
