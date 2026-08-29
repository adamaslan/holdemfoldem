---
date: 2026-07-03
type: entity
tags: [cross-repo, nuwrrrld, portal, mobile, mcp-finance, architecture]
sources: [../backend/main.py, ../../nuwrrrld-portal/app/api/holdfold/route.ts, ../../gcp3-mobile/lib/clients/holdfold.ts, ../../gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp/]
---

# Entity: holdemfoldemapp's Actual Structure & Its Fullstack Consumers (NuWrrrld Portal + Mobile)

## Purpose

This page documents (a) holdemfoldemapp's real, current file structure — as opposed to the aspirational shape implied by feature docs — and (b) exactly how its verdict reaches other surfaces in the fullstack. There are **two** consumers, and they connect in opposite ways:

- **`gcp3-mobile`** calls holdemfoldemapp's own backend directly and shares its real response contract — a genuine integration.
- **`nuwrrrld-portal`** does **not** call holdemfoldemapp at all. It calls a separate backend (`gcp3-backend`) and independently reshapes that backend's output into a same-named but differently-typed verdict — convergent naming, not a shared client.

Read [[overview]] first for the system map. The `index.md` Cross-Repo section previously pointed to `gcp3-mobile/docs/wiki-mobile/entity-client-holdfold.md`, which does not exist — the mobile wiki documents this client under `entity-backend-client.md` instead (see below).

## Actual File Structure

```
holdemfoldemapp/
├── backend/
│   ├── main.py               ← real local backend, "v6" (1212 lines)
│   │                            multi-lot P&L, Fibonacci, options payoff, Firestore cache
│   │                            imports gcp-app-w-mcp1/mcp-finance1 via sys.path.insert (main.py:36-40)
│   └── cloud-run/
│       ├── main.py            ← DEPLOYED entrypoint, "v2" — a simplified subset of backend/main.py
│       ├── Dockerfile
│       └── environment.yml
├── frontend/
│   └── src/
│       ├── app/
│       │   ├── page.tsx        ← verdict card, form, Fibonacci, options panel (1128 lines)
│       │   └── api/
│       │       ├── analyze/route.ts   ← proxies to backend /api/analyze
│       │       └── council/route.ts   ← proxies to ai-text-opt-1024 (NOT nuwrrrld)
│       ├── components/
│       │   ├── AiCouncilCommentary.tsx
│       │   ├── DisclaimerModal.tsx
│       │   └── DisclaimerFooter.tsx
│       └── lib/
│           └── disclaimer.ts
└── docs/
    ├── wiki-holdfold/          ← this wiki (index.md, overview.md, entity-*.md, decision-*.md)
    └── archive/
```

**Correction to a naming assumption:** `backend/main.py` is the fuller implementation (multi-lot P&L, Fibonacci, options payoff engine, Firestore cache — see [[entity-backend-api]] and [[overview#open-issues]]), but `backend/cloud-run/main.py` is what's actually deployed and publicly reachable. It is missing multi-lot P&L, Fibonacci, the options payoff engine, and the suppression pipeline. Any verdict returned from production has `position_pnl`, `position_aging`, `fib_levels`, and payoff fields as `null` regardless of what the client sends. This gap is tracked in [[overview#open-issues]] item 3 — it is not new information, just restated here because it directly affects the comparison below (a portal user hitting the equivalent gcp3 backend gets a similarly-shaped but differently-sourced verdict, and neither production surface has the local dev backend's full feature set).

## Relationship to gcp3-mobile (real integration)

`gcp3-mobile/lib/clients/holdfold.ts` is a typed client that calls holdemfoldemapp's backend **directly**:

```
gcp3-mobile/lib/clients/holdfold.ts
   BASE_URL = EXPO_PUBLIC_HOLDFOLD_BACKEND_URL (falls back to http://localhost:8081)
   analyzeHoldFold() → POST {BASE_URL}/api/analyze
   healthHoldFold()  → GET  {BASE_URL}/health
        │
        ▼
holdemfoldemapp/backend (main.py locally, cloud-run/main.py in prod)
```

Its `HoldFoldVerdict` TypeScript interface is hand-copied to match holdemfoldemapp's real Pydantic response — the file's own comment states "matches the contract used by holdemfoldemapp/frontend" — including `position_pnl`, `fib_levels`, and `options_strategy`, none of which the portal's verdict type carries. This is the same [[overview#open-issues]] hand-rolled-type risk applying a second time, once in `page.tsx` and once more in this mobile client; a schema change to `HoldFoldVerdict` in `backend/main.py` must be propagated to both by hand.

Because the mobile client hits `backend/cloud-run/main.py` in production, it inherits the same production gap noted above: `position_pnl`, `fib_levels`, and options fields will be `null` from the deployed URL even though the TypeScript type declares them as present (optional, so this doesn't break typing — it just silently under-delivers).

The mobile wiki's own catalog is at `gcp3-mobile/docs/wiki-mobile/entity-backend-client.md` — **not** `entity-client-holdfold.md` as this wiki's `index.md` previously stated. That link has been corrected.

## Relationship to nuwrrrld-portal (no shared code — convergent naming only)

**There is no code-sharing and no network call between holdemfoldemapp and nuwrrrld-portal.** They are independent products that both happen to consume the same upstream analysis library. The connection is one level of indirection, not a direct integration:

```
gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp/   ← single shared analysis library
        │                                              │
        │ imported via sys.path.insert                 │ deployed as a separate
        │ (in-process, same repo tree)                 │ Cloud Run service ("gcp3-backend")
        ▼                                              ▼
holdemfoldemapp/backend/main.py                nuwrrrld-portal/app/api/holdfold/route.ts
   /api/analyze                                    fetches gcp3-backend's /signals endpoint
   → HoldFoldVerdict                               → reshapes BUY/SELL/HOLD into
     {verdict: "HOLD EM"|"FOLD EM"|"NEUTRAL", ...}     {verdict: "HOLD EM"|"FOLD EM"|"NEUTRAL", ...}
        │                                              │
        ▼                                              ▼
holdemfoldemapp/frontend/src/app/page.tsx      nuwrrrld-portal/app/dashboard/holdfold/
   single-ticker verdict card                     HoldFoldClient.tsx — multi-ticker
                                                    dashboard list + [ticker] detail route
```

### What's actually shared

- **`gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp/`** — the indicator/detector/ranking code. holdemfoldemapp imports it directly into its own process (see [[decision-mcp-finance-as-shared-lib]]). nuwrrrld-portal does not import it at all — it calls a *separately deployed* Cloud Run service (`gcp3-backend`) whose `/signals` route is itself built on this library (confirmed via `gcp-app-w-mcp1/mcp-finance1/automation/functions/daily_analysis/main.py`, which imports `technical_analysis_mcp.analysis.StockAnalyzer`).
- **The "HOLD EM / FOLD EM / NEUTRAL" vocabulary** — both surfaces independently converge on this verdict naming. In holdemfoldemapp it's produced natively by `_build_verdict()` (`backend/main.py:818`). In nuwrrrld-portal it's a client-side remap: `mapVerdict()` in `app/api/holdfold/route.ts` translates the gcp3-backend's `BUY`/`SELL`/`HOLD` actions into the same three labels. This is convergent naming, not a shared type — nuwrrrld-portal defines its own `HoldFoldVerdict` TypeScript interface independently; it is not imported from holdemfoldemapp.

### What's genuinely different

| | holdemfoldemapp | nuwrrrld-portal |
|---|---|---|
| Backend called | Its own FastAPI (`backend/cloud-run/main.py`) | External `gcp3-backend` Cloud Run service |
| Scope | One ticker per request, with lots/options the caller supplies | Batch: `/signals` returns verdicts for a tracked list, portal fans them into a dashboard |
| Depth | Multi-lot P&L, cost basis, options Greeks/payoff (locally; missing in its own Cloud Run deploy) | None of that — RSI/MACD/ADX/signals only, no position or options math at any layer |
| Auth | None | Clerk-gated, part of a subscription product |
| AI commentary | `/api/council` → ai-text-opt-1024 (separate RAG service, unrelated to nuwrrrld) | `/api/council`(portal's own) → OpenRouter multi-seat "Council"; unrelated code despite the same feature name |

### Why this matters for future work

Because the two "HOLD EM/FOLD EM" verdicts come from different code paths, **they can and do disagree** for the same ticker at the same time — one reflects `technical_analysis_mcp` running in-process inside holdemfoldemapp's backend, the other reflects whatever `gcp3-backend` last cached from the same library through a different pipeline (daily_analysis automation vs. on-demand `/api/analyze`). A third surface, `gcp3-mobile`, sidesteps this disagreement entirely by talking to holdemfoldemapp's backend directly rather than to `gcp3-backend` — so the mobile app and the web portal can show different verdicts for the same ticker at the same moment, and neither is wrong given what each is actually calling.

If a future task asks to "unify" or "sync" the verdict systems, this page is the map of what would actually need to change: either point `nuwrrrld-portal`'s `/api/holdfold/route.ts` at holdemfoldemapp's backend the way `gcp3-mobile` already does, or point holdemfoldemapp/mobile at `gcp3-backend` instead, and reconcile the request/response shape (single-ticker + lots/options vs. batch signals-only) either way. No such unification has been done or started as of this writing.

## Full Fullstack Picture

| Consumer | Calls | Shares response contract with holdemfoldemapp? | Auth |
|---|---|---|---|
| `gcp3-mobile` (`lib/clients/holdfold.ts`) | holdemfoldemapp backend directly (`/api/analyze`, `/health`) | Yes — hand-copied `HoldFoldVerdict` type, same fields | None visible in this client |
| `nuwrrrld-portal` (`app/api/holdfold/route.ts`) | `gcp3-backend` Cloud Run service's `/signals` route (different backend entirely) | No — independently typed, remaps `BUY/SELL/HOLD` | Clerk (portal-level) |
| `ai-text-opt-1024` | Consumed *by* holdemfoldemapp's own `/api/council` proxy, not a consumer of the verdict | N/A — separate feature (AI commentary, not verdicts) | N/A |

## See also

- [[decision-mcp-finance-as-shared-lib]] — why the analysis library lives outside holdemfoldemapp
- [[entity-mcp-finance]] — the shared library itself
- [[entity-backend-api]] — holdemfoldemapp's own `/api/analyze`, including the local-vs-Cloud-Run gap referenced above
- [[decision-council-proxy-not-direct]] — holdemfoldemapp's *own* AI Council proxy, unrelated to the portal's Council feature of the same name
- `gcp3-mobile/docs/wiki-mobile/entity-backend-client.md` — the mobile-side documentation of the client described above
- `index.md` Cross-Repo section — do not edit `nuwrrrld-portal`'s or `gcp3-mobile`'s own docs from a holdfold session
