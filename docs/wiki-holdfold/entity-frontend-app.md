---
date: 2026-05-31
type: entity
tags: [frontend, nextjs, ui, verdict]
sources: [../frontend/src/app/page.tsx, ../frontend/src/app/api/analyze/route.ts, ../frontend/src/components/DisclaimerModal.tsx, ../frontend/src/components/DisclaimerFooter.tsx]
---

# Entity: Frontend App (`frontend/src/app/`)

Next.js 16 single-page app that presents the HOLD EM / FOLD EM form, calls the analyze proxy, and renders the full verdict card. Runs on port 3000 locally; deployed to Vercel (or the same Next.js process as ai-text-opt-1024 if co-located).

## What it is

**`page.tsx`** — the entire UI in one file:
- Ticker + period form with validation
- Calls `POST /api/analyze` (Next.js proxy → FastAPI backend)
- Renders on success: verdict badge (HOLD EM green / FOLD EM red / NEUTRAL gray), confidence %, bias, risk level, volatility regime, current price
- Top 5 signals table with strength badges
- RSI / MACD / ADX / ATR indicators
- Trade plan: entry, stop, target, R/R ratio
- Fibonacci levels panel (when backend returns them)
- Options payoff curve + Greeks panel (when `options_strategy` is set)
- Position P&L summary (when `position_lots` is provided)
- `<AiCouncilCommentary>` — tap-to-ask AI Council button

**`api/analyze/route.ts`** — thin proxy:
```ts
POST /api/analyze  →  BACKEND_URL/api/analyze
```
Forwards the full request body; passes through status codes and errors.

**`api/council/route.ts`** — AI Council proxy:
```ts
POST /api/council  →  COUNCIL_URL/api/chat
```
See [[entity-council-proxy]].

**Components:**
- `DisclaimerModal.tsx` — shown on first load; acknowledgement stored in localStorage. (No backend audit-log call is present in the component, and there is no disclaimer endpoint in `backend/main.py`; the backend only stamps a `disclaimer_version` field on each `HoldFoldVerdict`.)
- `DisclaimerFooter.tsx` — persistent "not financial advice" footer
- `AiCouncilCommentary.tsx` — see [[entity-council-proxy]]

**Env vars** (`.env.local`):
```
BACKEND_URL=http://localhost:8080          # → FastAPI
COUNCIL_URL=http://localhost:3001          # → ai-text-opt-1024
```

## Where used

- End-user browser — the primary interface
- `gcp3-mobile` references `HoldFoldVerdict` shape from this frontend for mobile parity (see `gcp3-mobile/docs/wiki-mobile/entity-client-holdfold.md`)

## Known failures

1. **`HoldFoldVerdict` TypeScript type is hand-rolled** — the `Verdict` interface in `page.tsx` was written by hand, not generated from the Pydantic model. If the backend adds fields (e.g. `warnings`, `position_aging`), the frontend silently ignores them until manually updated.
2. **No loading skeleton on re-analyze** — while a new request is in-flight, the previous verdict card remains visible with no clear "loading" state on the card itself. The submit button disables but the card doesn't visually indicate refresh.
3. **Disclaimer modal localStorage key** — if the key is cleared (private browsing, storage clear), the disclaimer re-shows. This is intentional but may surprise users who cleared storage for unrelated reasons.

## Open questions

- Should the TypeScript `Verdict` type be generated from the backend OpenAPI schema (`/openapi.json`) via `openapi-typescript`? This would prevent silent drift.
- The Fibonacci panel is only rendered when the backend returns `fib_levels`. When the Cloud Run backend is used (which omits Fibonacci), the panel disappears silently. Should there be a degraded-mode indicator?

## See also

- [[entity-backend-api]] — the FastAPI endpoint this frontend calls
- [[entity-council-proxy]] — the AI Council UI component + proxy route
- [[entity-signal-pipeline]] — what produces the data this page renders
- [[entity-options-payoff]] — the payoff panel this page renders
