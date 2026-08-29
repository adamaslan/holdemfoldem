---
date: 2026-05-31
type: overview
tags: [architecture, system-map, holdfold]
sources: [../backend/main.py, ../frontend/src/app/page.tsx, ../docs/signal-pipeline.md, ../docs/ai-council-integration.md, ../README.md]
---

# System Overview — holdemfoldemapp

A fullstack web app that delivers an instant **HOLD EM / FOLD EM / NEUTRAL** verdict for any US stock, ETF, or options ticker. A Python FastAPI backend runs 150+ technical signals through an 18-detector pipeline, then applies verdict logic with an optional options payoff engine. A Next.js frontend renders the verdict card with trade plan, Fibonacci levels, and AI Council commentary.

## Stack

| Layer | Tech | Deployed To |
|-------|------|-------------|
| Backend | FastAPI v6 (Python 3.11) + Pydantic | Cloud Run (`{holdfold-backend-url}`) |
| Data | yfinance (primary) · Alpha Vantage (fallback) | n/a |
| Signal analysis | `gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp/` | vendored into Cloud Run image |
| Caching | Firestore (1h TTL; stale hits re-fetch synchronously, no background refresh) | Firestore in `{gcp-project-id}` |
| AI ranking | Gemini API (optional; rule-based fallback always available) | Gemini via gcp-app-w-mcp1 |
| Frontend | Next.js 16 + TypeScript | Vercel (or local :3000) |
| AI Council | Proxy → ai-text-opt-1024 `/api/chat` (RAG + Gemini) | local :3001 in dev |
| Deploy | `deploy-backend.sh` → `gcloud run deploy` | Cloud Build + Cloud Run |

## Data Flow

```
Browser (Next.js :3000)
   │  POST /api/analyze  {symbol, period, options_strategy, position_lots}
   ▼
frontend/src/app/api/analyze/route.ts  (Next.js proxy)
   │
   ▼
backend/main.py  FastAPI /api/analyze
   ├─ Firestore cache check (key = symbol only — see [[entity-firestore-cache]]; period not in key)
   │    fresh hit → return cached HoldFoldVerdict; stale hit (>1h) → synchronous re-fetch
   │    miss ↓
   ├─ asyncio.gather(analyze_security, get_trade_plan, analyze_fibonacci, options_risk_analysis?)
   │     └─ analyze_security: yfinance → calculate_all_indicators → detect_all_signals → rank_signals
   ├─ _build_verdict(signals, trade_plan, options_data, request)
   ├─ Write result to Firestore
   └─ Return HoldFoldVerdict JSON
   │
   ▼
frontend page.tsx renders:
  Verdict card · Confidence % · Bias · Risk level · Volatility regime
  Top 5 signals · Primary signal · Supporting signals
  RSI · MACD · ADX · ATR
  Trade plan (entry · stop · target · R/R)
  Fibonacci levels (if available)
  Options payoff curve + Greeks (if options_strategy set)
  AiCouncilCommentary  (tap-to-ask → /api/council → ai-text-opt-1024 RAG)
```

## Entity Map

**Backend pipeline**
- [[entity-signal-pipeline]] — the 4-stage core: indicators → detectors → ranking → verdict
- [[entity-backend-api]] — FastAPI `/api/analyze` and `/health`; `HoldFoldVerdict` shape
- [[entity-firestore-cache]] — 1h TTL cache keyed on symbol only (period/schema not in key — known collision)
- [[entity-options-payoff]] — 14-strategy payoff engine with 60-point curve + PoP

**Frontend**
- [[entity-frontend-app]] — Next.js page.tsx: form, verdict card, Fibonacci, options panel
- [[entity-council-proxy]] — `/api/council` proxy route + `AiCouncilCommentary.tsx` component

**Shared code (cross-repo, read-only)**
- [[entity-mcp-finance]] — `gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp/`; the actual analysis code

## Current System Health (2026-05-31)

| Component | Status | Notes |
|-----------|--------|-------|
| Backend API | ✅ Deployed | Cloud Run; `/api/analyze` + `/health` |
| Signal pipeline | ✅ 18 detectors | All implemented; Gemini ranking optional |
| Firestore cache | ✅ Active | 1h TTL; key = symbol only (no period); stale hits re-fetch synchronously |
| Options payoff | ✅ 14 strategies | Per-share P&L curve, PoP estimate |
| Multi-lot P&L | ⚠️ Local only | FIFO/LIFO/avg cost basis, dated lots, fee-aware — **not on Cloud Run**; `position_pnl` and `position_aging` are null in production |
| AI Council (web) | ✅ Wired | `/api/council` proxy → ai-text-opt-1024; requires local :3001 in dev |
| Disclaimer system | ✅ Implemented | Modal + footer; localStorage ack. Backend stamps `disclaimer_version` on each verdict (no separate audit-log endpoint) |
| Mobile client | ✅ Wired in gcp3-mobile | See `gcp3-mobile/docs/wiki-mobile/entity-client-holdfold.md` |
| Alpha Vantage fallback | ✅ Implemented | Activates on yfinance failure; requires `{alphavantage-api-key}` |
| Gemini ranking | ⚠️ Optional | Circuit-breaker protects pipeline; rule-based fallback always available |
| Type generation | ❌ Manual | `HoldFoldVerdict` TypeScript type in `page.tsx` is hand-rolled; not generated from Pydantic |

## Open Issues

1. **Hand-rolled TypeScript types** — `HoldFoldVerdict` interface in `page.tsx` was not generated from Pydantic. Schema drift risk if backend adds fields.
2. **AI Council requires ai-text-opt-1024 running locally** — no fallback in the web frontend if the RAG server isn't up. Produces a 503 error on the "Ask the Council" button.
3. **Cloud Run and local backends differ — confirmed production gap.** `backend/cloud-run/main.py` (the actual deployed entrypoint) is missing: multi-lot P&L, Fibonacci analysis, options payoff engine, and the suppression pipeline. Any `HoldFoldVerdict` returned from the production URL will have `position_pnl`, `position_aging`, `fib_levels`, and all payoff fields as `null` regardless of what the caller sends. See [[entity-backend-api#known-failures]] for the full field list.
4. **No auth or rate limiting on `/api/analyze`** — the backend is publicly callable. The only middleware in `backend/main.py` is CORS; there is no rate limiter, API key, or session requirement. See [[entity-backend-api#rate-limiting]].

## Key Design Decisions

- [[decision-mcp-finance-as-shared-lib]] — signal analysis lives in `gcp-app-w-mcp1`, not holdemfoldemapp
- [[decision-council-proxy-not-direct]] — AI Council is a thin Next.js proxy, not a new Python endpoint
- [[decision-rule-based-ranking-fallback]] — Gemini ranking is optional; rule-based is always the floor

## See Also

All pages cataloged in [[index]].
