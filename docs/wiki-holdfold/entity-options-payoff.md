---
date: 2026-05-31
type: entity
tags: [options, payoff, greeks, backend]
sources: [../backend/core.py, ../docs/signal-pipeline.md]
---

# Entity: Options Payoff Engine (`backend/core.py`)

Computes per-share P&L at expiry across 61 price points for 14 options strategy types, plus probability-of-profit estimates and key metrics (max profit, max loss, breakevens, spread width). Runs as the final step in `_build_verdict` when `options_strategy` is set in the request.

**As of 2026-08-28** this logic lives in `backend/core.py`, not `backend/main.py` — see [[entity-verdict-core]] for the extraction.

## What it is

Implemented entirely in `backend/core.py`. Three layers:

**1. Greeks extraction** (`_extract_options_greeks`)

Parses `options_risk_analysis` output (from `gcp-app-w-mcp1` mcp server) into `OptionsGreeks`:
```python
iv: float | None           # implied volatility
pcr: float | None          # put/call ratio
delta: float | None
theta: float | None
vega: float | None
```

**2. Payoff curve** (`_strategy_pnl_at_expiry`)

For each of 61 price points (`PAYOFF_POINTS = 60`, iterated `range(PAYOFF_POINTS + 1)`) spanning `[min(strikes+spot) × 0.7, max(strikes+spot) × 1.3]` (or `[spot_low, spot_high]` if the caller supplies both):
- Calls the appropriate payoff formula for the chosen strategy
- Returns a `PayoffPoint(price, pnl)` list

14 strategies have `STRATEGY_NOTES` entries, but only **12** have an expiry payoff branch in `_strategy_pnl_at_expiry` (`backend/core.py:654-721`). `calendar_spread` and `diagonal_spread` fall through and return `None` — a single-expiry payoff-at-expiry model cannot represent a multi-expiry position, so no curve, breakevens, max profit/loss, or PoP are produced for them even though they are accepted strategy names:

| Strategy | Description |
|----------|-------------|
| `long_call` | max(S−K, 0) − premium |
| `long_put` | max(K−S, 0) − premium |
| `covered_call` | stock gain capped at K + premium |
| `cash_secured_put` | put obligation − premium collected |
| `bull_call_spread` | long lower K + short upper K |
| `bear_put_spread` | long upper K + short lower K |
| `call_credit_spread` | short lower + long upper |
| `put_credit_spread` | short upper + long lower |
| `iron_condor` | put spread + call spread |
| `iron_butterfly` | short ATM straddle + wings |
| `straddle` | call + put at same strike |
| `strangle` | OTM put + OTM call |
| `calendar_spread` | listed in `STRATEGY_NOTES`/`NEUTRAL_STRATEGIES`, but **no expiry payoff branch** — see note below |
| `diagonal_spread` | listed in `STRATEGY_NOTES`, but **no expiry payoff branch** — see note below |

**3. Metrics** (`_compute_payoff_metrics`)

From the 61-point curve:
- `max_profit`, `max_loss`
- `spread_width`
- `breakevens` (price points where PnL crosses zero)
- `pop_estimate` — probability of profit: fraction of 61 price points with PnL > 0

**Verdict override**: `_strategy_verdict_bias` maps strategies to bias (bullish/bearish/neutral/volatility). Neutral/volatility strategies override the signal-derived verdict when `avg_score ≥ 55`.

## Where used

- [[entity-verdict-core]] — `core.compute_verdict` calls `_build_verdict` which calls the payoff engine
- [[entity-backend-api]] — the FastAPI adapter exposing it over HTTP
- [[entity-frontend-app]] — renders payoff curve chart, breakevens, max profit/loss
- [[entity-signal-pipeline]] — stage 4 (verdict construction) invokes the payoff engine

## Known failures

1. **`backend/cloud-run/main.py` has no payoff engine** — the *unused* stripped-down entrypoint at that path does not run options analysis. Note that `deploy-backend.sh` does not actually deploy this file; see [[entity-verdict-core]] Known Failures for the packaging gap this PR closed for the *deployed* entrypoint (`backend/main.py` + `backend/core.py`, deployed as Cloud Run's `main.py`).
2. **`straddle` payoff invariant** — per the git history (`c74ca7b`), the straddle payoff formula was incorrect before a code review fix. Confirmed fixed as of that commit; no regression in prod observed.
3. **PoP estimate is a rough proxy** — `pop` is the fraction of the 61 analyzed price points with PnL > 0, assuming a uniform price distribution over the auto-range. This overestimates PoP for OTM strategies (a code comment in `_compute_payoff_metrics`, `backend/core.py`, says a log-normal weighting by IV and DTE would be more correct). `iv` and `dte` are passed into `_compute_payoff_metrics` but are not yet used. The response field is `pop`, not `pop_estimate`.
4. **`calendar_spread` / `diagonal_spread` produce no payoff** — these two strategies have no branch in `_strategy_pnl_at_expiry`, so `payoff_curve`, `breakeven_prices`, `max_profit`, `max_loss`, and `pop` are all null even when the request is otherwise valid. The verdict and `strategy_note` still render. A single-expiry payoff-at-expiry model is structurally unable to price a calendar/diagonal.

## Open questions

- Should the payoff curve span beyond ±30% spot? For long-dated options or high-IV stocks, the range may cut off meaningful payoff regions. (The PoP estimate divides by `len(pnls)` over this fixed window, so a too-narrow window inflates or deflates PoP.)

## See also

- [[entity-backend-api]] — the `AnalyzeRequest.options_strategy` field that triggers this engine
- [[entity-signal-pipeline]] — runs before the payoff engine in `_build_verdict`
- [[entity-frontend-app]] — the UI that renders the payoff output
