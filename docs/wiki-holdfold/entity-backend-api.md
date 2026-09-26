---
date: 2026-05-31
type: entity
tags: [fastapi, backend, api, verdict, holdfold]
sources: [../backend/main.py, ../backend/core.py, ../deploy-backend.sh, ../backend/tests/test_deployed_entrypoint.py]
---

# Entity: Backend API (`backend/main.py`)

FastAPI v6 application that receives an `AnalyzeRequest` and returns a `HoldFoldVerdict`. The single source of truth for the `HoldFoldVerdict` JSON contract used by both the Next.js frontend and the gcp3-mobile app.

**As of 2026-08-28**, `backend/main.py` is a thin HTTP adapter — the verdict pipeline itself was extracted into `backend/core.py` (see [[entity-verdict-core]]). `main.py` imports `core` at module load, so any deployment (including Cloud Run) that ships `main.py` must ship `core.py` alongside it; `deploy-backend.sh` and `backend/cloud-run/Dockerfile` both copy `core.py` into the build context/image for this reason.

## What it is

Two routes:

| Route | Method | Purpose |
|-------|--------|---------|
| `/api/analyze` | POST | Run (or cache-hit) the full signal pipeline; return `HoldFoldVerdict` |
| `/health` | GET | Returns `{"status": "ok"}` for Cloud Run health probes |

**`AnalyzeRequest`** (all fields except `symbol` are optional):

```python
symbol:          str                    # e.g. "AAPL", "SPY", "BRK.B"
period:          str = "1mo"            # "1mo"|"3mo"|"6mo"|"1y"|"2y"|"5y"|"max"
options_strategy: str | None = None    # 14 strategies: "long_call", "iron_condor", etc.
options_legs:    list[OptionsLegRequest] | None = None
position_lots:   list[PositionLot] | None = None   # multi-lot P&L (see below)
# Legacy single-lot (still supported):
position_qty:    float | None = None
position_entry:  float | None = None
position_side:   "long" | "short" = "long"
```

**`PositionLot`** (multi-lot, dated, fee-aware):

```python
qty:           float           # shares or contracts
cost_basis:    float           # per-share, post-fee
acquired_at:   str | None      # ISO 8601 date; enables tax-lot aging
side:          "long"|"short" = "long"
fees_total:    float | None    # commissions + regulatory, absolute $
account_type:  "taxable"|"ira"|"roth"|"401k"|"margin"|"cash" | None
```

**`HoldFoldVerdict`** (the contract mobile + web depend on):

```python
symbol:          str
verdict:         "HOLD EM" | "FOLD EM" | "NEUTRAL"
confidence:      float          # 0–95 (hard-clamped)
bias:            str            # "bullish" | "bearish" | "neutral"
risk_level:      str            # "low" | "medium" | "high" | "extreme"
volatility_regime: str          # "low" | "normal" | "elevated" | "extreme" | "unknown" (by ATR%: <1% low, <2.5% normal, <5% elevated, else extreme)
top_signals:     list[dict]     # up to 5 ranked signals {signal, strength, category, score}
rsi:             float | None
macd:            float | None
adx:             float | None
atr:             float | None
primary_signal:  str | None
supporting_signals: list[str]
current_price:   float | None
fib_levels:      list[FibLevel] | None
options_strategy: str | None
options_greeks:  OptionsGreeks | None
payoff_points:   list[PayoffPoint] | None  # 60-point curve
payoff_max_profit: float | None
payoff_max_loss:  float | None
payoff_breakevens: list[float] | None
pop_estimate:    float | None   # probability of profit
position_pnl:    PositionPnL | None
position_aging:  PositionAging | None
cached:          bool
reasoning:       str | None     # Gemini ranking reasoning if AI mode
cache_age_seconds: int | None
warnings:        list[str]      # degraded indicators, stale data, etc.
```

> The block above is the conceptual contract. For exact Pydantic field names see `HoldFoldVerdict` in `backend/main.py:305-387`. Notable differences from the names above: the price field is `price` (not `current_price`); rich position fields are `position_pnl_detail` / `position_aging` (not `position_pnl`); PoP is `pop` (not `pop_estimate`); the payoff curve is `payoff_curve` (not `payoff_points`); options Greeks use `delta_atm` / `theta_atm` / `vega_atm`. The model also carries a `request_id` field echoed in the `X-Request-Id` response header. The deployed `app.version` string is `"5.0"` (local) / `"1.0"` (Cloud Run), despite the "v6" feature label.

### Local vs Cloud Run

There is one entrypoint. `backend/main.py` + `backend/core.py` run locally, and `deploy-backend.sh` ships the same pair as Cloud Run's `main.py` (true since PR #11). The old stripped-down `backend/cloud-run/main.py` was never deployed after #11 and was archived in PR #15. *Earlier revisions of this section said the deploy used the stub. That was wrong.*

### CORS

Configurable via `ALLOWED_ORIGINS` env var. Defaults to `localhost:3000,3001,3002`. Production must set this to the Vercel/frontend domain.

### Rate Limiting

**Not implemented in `backend/main.py`.** The only middleware registered is `CORSMiddleware` (line 69). There is no per-IP rate limiter, no 429 path, and no `Retry-After` header in the code. The endpoint's only protection is CORS (browser-only) — any non-browser client can call it freely. Earlier wiki revisions and the overview status table claimed a 30 req/min limiter; that is aspirational, not present.

## Where used

- `frontend/src/app/api/analyze/route.ts` — Next.js proxy that forwards POST to this backend
- `gcp3-mobile/docs/wiki-mobile/entity-client-holdfold.md` — mobile client that calls `/api/analyze` directly

## Known failures

1. **Production is missing v6 features — because the revision is stale, not because of the entrypoint.** Corrected 2026-09-24: the gap is **stale deployment, not missing code**. Since PR #11, `deploy-backend.sh` ships `backend/main.py` + `backend/core.py` as the image's `main.py`, so a fresh deploy serves the full verdict. The running revision (`holdemfoldem-api-00003`, 2026-03-24) predates #11, so production stays degraded until someone redeploys. The dead stub was archived to `file-archive/backend-cloud-run-main.py` in PR #15, and `tests/test_deployed_entrypoint.py` now pins lots → `position_pnl_detail` and `fib_levels` on the shipped app. *Original (incorrect) diagnosis, kept for the record:* `backend/cloud-run/main.py` is the Cloud Run entrypoint. It lacks: multi-lot P&L (`position_lots` field silently ignored), Fibonacci analysis (`fib_levels` always null), options payoff engine (`payoff_points`, `payoff_max_profit`, `payoff_max_loss`, `payoff_breakevens`, `pop_estimate` all null), suppression pipeline. The `overview.md` status table marks multi-lot P&L as ✅ — that reflects local dev only. **In production, `HoldFoldVerdict` returns a structurally valid but functionally degraded response for any request that depends on those fields.** Mobile clients receive null for `position_pnl`, `position_aging`, `fib_levels`, and all payoff fields regardless of request payload.
2. **No auth and no rate limiting** — the endpoint is open to anyone who knows the Cloud Run URL. Despite earlier wiki claims, no rate limiter is implemented (only CORS middleware is registered). There is no API-key, session, or per-IP throttle.
3. **ALLOWED_ORIGINS not set at deploy** — `deploy-backend.sh` does not pass `ALLOWED_ORIGINS`. Production frontend origin must be set manually post-deploy.

## Open questions

- ~~Should `backend/cloud-run/main.py` be brought in sync with `backend/main.py`?~~ Moot: it was archived in PR #15, and the deploy already used `main.py` + `core.py`. The remaining action is a redeploy. *Original question:* The full suppression pipeline, multi-lot, Fibonacci, and options payoff would need to be ported. This is the single most impactful production gap. Note that the Cloud Run verdict logic is also simpler: it has no sub-55 fallback path — a directional-but-weak symbol returns `NEUTRAL` on Cloud Run but `HOLD EM`/`FOLD EM` (confidence × 0.85) on the local backend.

## See also

- [[entity-signal-pipeline]] — what runs inside `/api/analyze`
- [[entity-firestore-cache]] — the Firestore layer `_cached_or_fetch` wraps around the pipeline
- [[entity-options-payoff]] — the payoff engine called from `_build_verdict`
- [[entity-frontend-app]] — the Next.js consumer of this API
- [[overview]] — the full data flow diagram
