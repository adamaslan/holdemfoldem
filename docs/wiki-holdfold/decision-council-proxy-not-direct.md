---
date: 2026-05-31
type: decision
tags: [ai-council, frontend, proxy, architecture]
sources: [../docs/ai-council-integration.md]
---

# Decision: AI Council as Next.js Proxy, Not New Python Endpoint

## Decision

The AI Council integration for the web frontend is a thin Next.js proxy route (`/api/council`) forwarding to ai-text-opt-1024, not a new FastAPI endpoint on the holdemfoldemapp backend.

## Date

2026-05-31 (council integration: commits `6b3b5f9`, `c748a33`).

## Context

After verdict, the user wants AI commentary grounded in trader notes (RAG corpus). The ai-text-opt-1024 backend already has a working `/api/chat` endpoint with ChromaDB RAG + Gemini. The question was how to connect it to the holdemfoldemapp UI.

## Alternatives considered

| Alternative | Why not |
|-------------|---------|
| Add `/api/council` to FastAPI `backend/main.py` | Would duplicate the RAG + LLM logic that already works in ai-text-opt-1024; unnecessary Python |
| Call ai-text-opt-1024 directly from the browser | Exposes `COUNCIL_URL` to clients; breaks the proxy convention used for `/api/analyze` |
| Store council comments in a new DB table | Verdicts are cached upstream; council commentary is a derived view that should be regenerated on demand, not persisted |

## Consequences

**Enables:**
- Zero new Python code — the entire integration is ~25 lines of TypeScript
- The `trader_filter` parameter can be passed through without any backend changes
- Future streaming support is a change in ai-text-opt-1024 only, not in holdemfoldemapp

**Rules out:**
- Using the web Council feature in production without a deployed ai-text-opt-1024 instance (currently dev-only)
- Server-side prompt caching (each tap fires a new LLM call)

## Validated by

Committed and working in `frontend/src/app/api/council/route.ts` and `AiCouncilCommentary.tsx` as of `c748a33`.

## See also

- [[entity-council-proxy]] — the implementation
- [[entity-frontend-app]] — the UI that hosts the proxy
