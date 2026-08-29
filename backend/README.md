# Hold Em or Fold Em Backend

This backend is a FastAPI service that turns market-analysis data from the MCP Finance codebase into a single `HOLD EM`, `FOLD EM`, or `NEUTRAL` verdict. It is designed for the Next.js frontend, but it can also be called directly with HTTP.

The main implementation is [`backend/main.py`](./main.py). It exposes:

- `POST /api/analyze` - analyze a symbol and return a full verdict payload.
- `GET /health` - lightweight health check with app version and Firestore-cache availability.

## Runtime Shape

```text
frontend/src/app/api/analyze/route.ts
        |
        | proxies POST /api/analyze
        v
backend/main.py FastAPI app
        |
        | imports MCP Finance tools
        v
gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp
```

For local development, `backend/main.py` expects the MCP Finance repo to exist as a sibling checkout:

```text
/Users/adamaslan/code/
|-- holdemfoldemapp/
`-- gcp-app-w-mcp1/mcp-finance1/
```

On Cloud Run, the deploy script builds a temporary Docker context and copies the MCP Finance `src/` and `fibonacci/` folders into the image.

## What `/api/analyze` Does

1. Validates the ticker symbol and period.
2. Runs these MCP tools in parallel:
   - `analyze_security(symbol, period=period)`
   - `get_trade_plan(symbol, period=period)`
   - `analyze_fibonacci(symbol, period=period)`
3. Optionally runs `options_risk_analysis(symbol)` when an options strategy is supplied.
4. Reads and writes MCP tool results through Firestore when available.
5. Builds a normalized `HoldFoldVerdict` response for the frontend.

The response combines technical-signal counts, indicator values, trade-plan levels, Fibonacci levels, optional options payoff math, optional position P&L, warnings, and a human-readable summary.

## Local Development

Activate the finance environment, then run the backend:

```bash
source /opt/homebrew/Caskroom/miniforge/base/etc/profile.d/conda.sh
source /opt/homebrew/Caskroom/miniforge/base/etc/profile.d/mamba.sh
mamba activate fin-ai1

cd /Users/adamaslan/code/holdemfoldemapp/backend
uvicorn main:app --reload --port 8080
```

The app also runs directly with:

```bash
python main.py
```

Direct execution uses `PORT` if set, otherwise `8080`.

The frontend proxy defaults to `http://localhost:8080` through `frontend/src/app/api/analyze/route.ts`. If you run the backend on another port, set `BACKEND_URL` in `frontend/.env.local`.

## Environment Variables

- `PORT` - server port when running `python main.py`; defaults to `8080`.
- `ALLOWED_ORIGINS` - comma-separated CORS allowlist; defaults to localhost ports `3000`, `3001`, and `3002`.
- `K_SERVICE` - automatically set on Cloud Run; enables Google Cloud Logging setup.
- `GCP_PROJECT_ID` - used by Cloud Run deployment and Google clients.
- `FINNHUB_API_KEY`, `ALPHA_VANTAGE_KEY`, `GEMINI_API_KEY` - external API keys used by the MCP Finance layer.

For local development, `main.py` also tries to load a `.env` file from the sibling MCP Finance repo:

```text
gcp-app-w-mcp1/mcp-finance1/.env
```

## Request Contract

Minimal request:

```bash
curl -X POST http://localhost:8080/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"symbol":"AAPL","period":"3mo","asset_type":"stock"}'
```

Important request fields:

| Field | Type | Notes |
| --- | --- | --- |
| `symbol` | string | Required. Uppercased and validated as 1-12 letters, numbers, dots, or hyphens. Examples: `AAPL`, `BRK.B`, `BTC-USD`. |
| `period` | string | Defaults to `3mo`. Valid values: `15m`, `1h`, `4h`, `1d`, `5d`, `1mo`, `3mo`, `6mo`, `1y`, `2y`, `5y`, `10y`, `ytd`, `max`. |
| `asset_type` | string | Defaults to `stock`; passed through in the response. |
| `risk_profile` | string | Defaults to `moderate`; currently modeled on the request but not deeply used in verdict math. |
| `options_strategy` | string or null | Enables options metrics and payoff calculations. |
| `options_legs` | array | Optional strategy legs with `role`, `strike`, `expiry`, and `premium`. |
| `dte` | integer or null | Days to expiration for options display/math. |
| `net_premium` | number or null | Per-share premium. Positive means credit if sent signed directly. |
| `premium_sign` | integer or null | When supplied, backend computes `net_premium * premium_sign`; use `1` for credit and `-1` for debit. |
| `spot_low`, `spot_high` | number or null | Optional bounds for payoff-curve generation. |
| `position_entry`, `position_qty`, `position_side` | mixed | Legacy single-lot position fields. |
| `position_lots` | array or null | Preferred multi-lot position model. |
| `cost_basis_method` | string | `fifo`, `lifo`, `average`, or `specific`; defaults to `average`. |
| `include_dividends` | boolean | Present on the model, but dividends are not fetched yet. |
| `adjust_for_splits` | boolean | Present on the model; split adjustment hook exists, but no split data is fetched in this layer yet. |

Example request with a position and options strategy:

```json
{
  "symbol": "AAPL",
  "period": "3mo",
  "asset_type": "stock",
  "position_lots": [
    {
      "lot_id": "lot-1",
      "qty": 10,
      "cost_basis": 175.25,
      "acquired_at": "2025-01-15",
      "side": "long",
      "fees_total": 1.25,
      "account_type": "taxable"
    }
  ],
  "cost_basis_method": "average",
  "options_strategy": "long_call",
  "options_legs": [
    { "role": "long_call", "strike": 210, "expiry": "2026-06-19" }
  ],
  "dte": 32,
  "net_premium": 4.5,
  "premium_sign": -1
}
```

## Response Shape

The response model is `HoldFoldVerdict`. Key groups:

- Verdict: `symbol`, `asset_type`, `verdict`, `confidence`, `price`, `bias`, `risk_level`, `cached`.
- Signals: `bullish_count`, `bearish_count`, `avg_score`, `top_signals`.
- Indicators: `rsi`, `macd`, `adx`, `atr`, `volatility_regime`, `volume_spike`.
- Trade plan: `entry`, `stop`, `target`, `risk_reward`, `stop_pct`, `upside_pct`, `vehicle`, `primary_signal`, `supporting_signals`.
- Position: legacy flat P&L fields plus `position_aging` and `position_pnl_detail`.
- Fibonacci: `fib_levels`, `fib_confluence_zones`, `nearest_fib_support`, `nearest_fib_resistance`.
- Options: `options_greeks`, `max_profit`, `max_loss`, `breakeven_prices`, `pop`, `payoff_curve`, `strategy_note`.
- Robustness metadata: `degraded`, `warnings`, `request_id`, `disclaimer_version`, `data_timestamp`.

Every successful analysis also returns an `X-Request-Id` response header, and the same value appears in the JSON body as `request_id`.

## Verdict Logic

The backend derives a verdict from signal counts, average score, trade-plan availability, and directional bias:

- Strong bullish setup with a usable trade plan becomes `HOLD EM`.
- Strong bearish setup with a usable trade plan becomes `FOLD EM`.
- When no clean plan exists, signal imbalance can still produce a lower-confidence verdict.
- Otherwise the result is `NEUTRAL`.

Options strategies can adjust the interpretation:

- Neutral or volatility strategies can still produce `HOLD EM` when signal quality is high.
- Bearish options strategies such as `long_put` and `bear_put_spread` convert a bullish-style hold verdict into `FOLD EM`.

Confidence is clamped between `0` and `95`.

## Options Support

Supported strategy names include:

```text
long_call
long_put
covered_call
cash_secured_put
bull_call_spread
bear_put_spread
call_credit_spread
put_credit_spread
iron_condor
iron_butterfly
straddle
strangle
calendar_spread
diagonal_spread
```

For supported payoff strategies, the backend computes per-share max profit, max loss, spread width, approximate breakevens, a rough probability-of-profit estimate, and a 61-point payoff curve.

The probability-of-profit value is intentionally rough: it is the percentage of generated payoff points above zero, not a proper IV-weighted distribution model.

## Position P&L Support

The backend accepts either legacy single-position fields or the preferred `position_lots` array.

For lots, it computes:

- Effective cost basis including fees.
- Weighted-average cost basis.
- Unrealized dollar and percent P&L.
- Optional per-lot breakdown when more than one lot is supplied.
- Earliest acquisition date, weighted average holding age, long-term percentage, and short-term percentage.

Current limitations:

- Mixed long/short lot groups are not fully modeled for aggregate P&L.
- Realized P&L is only a placeholder for dividends until lot-sale tracking exists.
- Split-adjustment logic exists, but this layer currently passes no split events into it.

## Cache and Degraded Mode

Firestore cache is optional and lazy:

- `_get_firestore()` tries to create `MCPFirestoreCache`.
- If unavailable, the backend logs a warning and continues without cache.
- Cached tool results are treated as fresh for one hour.
- `/health` reports whether Firestore is available.

If the MCP layer returns data-quality warnings or `degraded=true`, those are surfaced in the response as `warnings` and `degraded`.

## Error Behavior

- Empty symbol: `400`.
- Invalid symbol format: `400`.
- Invalid period: `400`.
- MCP pipeline failure: `503`.
- Options-chain failure: non-fatal; response includes `warnings: ["options_chain_unavailable"]`.

## Deployment

Use the root deploy script:

```bash
cd /Users/adamaslan/code/holdemfoldemapp
bash deploy-backend.sh
```

The script creates a temporary build context, copies in:

- `backend/main.py` as the Cloud Run `main.py`
- `backend/cloud-run/Dockerfile`
- `backend/cloud-run/environment.yml`
- MCP Finance `src/`
- MCP Finance `fibonacci/`

Then it deploys the service as `holdemfoldem-api` with required secrets from Google Secret Manager.

Note: [`backend/cloud-run/main.py`](./cloud-run/main.py) is an older, simpler Cloud Run entry point. The current deploy script uses [`backend/main.py`](./main.py) for Cloud Run.
