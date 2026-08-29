# Wiki Index — holdemfoldemapp

_Last updated: 2026-08-28 (CLI + MCP server build)_

Catalog organized by page type. Read `index.md` first on any query, then drill in. For schema and conventions see [[SCHEMA]].

---

## Overview

- [[overview]] — system map, stack, data flow, current health

---

## System Entities

One page per named component.

**Backend**
- [[entity-backend-api]] — FastAPI `/api/analyze` + `/health`; `HoldFoldVerdict` shape; local vs Cloud Run gap
- [[entity-verdict-core]] — `backend/core.py`; transport-agnostic `compute_verdict()` extracted from the FastAPI route so the CLI and MCP server share one verdict engine
- [[entity-signal-pipeline]] — 4-stage core: indicators → 18 detectors → ranking → verdict
- [[entity-firestore-cache]] — 1h TTL write-through cache keyed on symbol only (period not in key); stale hits re-fetch synchronously (no background refresh); degrades gracefully without GCP creds
- [[entity-options-payoff]] — 14-strategy payoff engine; 60-point curve; PoP estimate
- [[entity-mcp-finance]] — shared analysis library in `gcp-app-w-mcp1`; imported via sys.path
- [[entity-cli]] — `holdfold` Typer CLI; hybrid in-process/HTTP transport; exit codes encode the verdict
- [[entity-mcp-server]] — `holdemfoldem-mcp` stdio MCP server; wraps the HTTP API as 3 tools
- [[entity-nuwrrrld-portal-relationship]] — actual repo file structure; the real gcp3-mobile client integration vs. the unrelated, convergently-named nuwrrrld-portal HOLD/FOLD feature

**Frontend**
- [[entity-frontend-app]] — Next.js `page.tsx`; verdict card; disclaimer; Fibonacci; options panel
- [[entity-council-proxy]] — `/api/council` proxy + `AiCouncilCommentary.tsx`; tap-to-ask AI Council

---

## Concepts

- [[concept-signal-scoring]] — keyword → score mapping; avg_score gates; risk level matrix

---

## Decisions

- [[decision-mcp-finance-as-shared-lib]] — signal analysis lives in gcp-app-w-mcp1, imported at runtime
- [[decision-council-proxy-not-direct]] — AI Council is a thin Next.js proxy, not new Python
- [[decision-rule-based-ranking-fallback]] — Gemini ranking is opt-in; rule-based is always the floor
- [[decision-mcp-wraps-http-not-import]] — the new MCP server calls the FastAPI backend over HTTP rather than importing `core.py` into its own process

---

## Incidents

_None recorded yet._

---

## Sources (raw/)

Immutable source documents. LLM reads; never modifies.

The `raw/` directory is empty as of 2026-05-31. The wiki was synthesized from:

| File | What it is | Lives at |
|------|------------|----------|
| `README.md` | App overview + local dev + deploy instructions | `/` |
| `docs/signal-pipeline.md` | Full pipeline architecture with stage diagrams | `docs/` |
| `docs/ai-council-integration.md` | AI Council design + proxy spec | `docs/` |
| `docs/robustness-roadmap.md` | P0–P2 robustness improvements (multi-lot, disclaimer, resilience) | `docs/` |
| `backend/main.py` | Full local backend (feature "v6"; `app.version="5.0"`) — AnalyzeRequest, HoldFoldVerdict, all helper functions | `backend/` |
| `backend/cloud-run/main.py` | Simplified Cloud Run entrypoint (feature "v2"; `app.version="1.0"` — missing multi-lot, Fibonacci, payoff, suppressions, Firestore) | `backend/cloud-run/` |
| `frontend/src/app/page.tsx` | Next.js UI | `frontend/src/app/` |
| `frontend/src/app/api/analyze/route.ts` | Analyze proxy | `frontend/src/app/api/analyze/` |
| `frontend/src/app/api/council/route.ts` | Council proxy | `frontend/src/app/api/council/` |
| `frontend/src/components/AiCouncilCommentary.tsx` | AI Council UI component | `frontend/src/components/` |

---

## Cross-Repo

- Mobile app consuming this backend directly (real shared contract): `gcp3-mobile/lib/clients/holdfold.ts`, documented at `gcp3-mobile/docs/wiki-mobile/entity-backend-client.md` (correction: not `entity-client-holdfold.md`, which does not exist)
- Signal analysis source: `gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp/`
- AI Council RAG backend: `ai-text-opt-1024/backend/`
- NuWrrrld portal's own (unrelated, independently-coded) HOLD/FOLD feature: `nuwrrrld-portal/app/api/holdfold/route.ts` — see [[entity-nuwrrrld-portal-relationship]] for the full picture of what is and isn't actually shared across all three consumers

Do not edit those repos' wikis from a holdfold session.

---

## Meta

- [[SCHEMA]] — wiki conventions, page types, required sections
- [[log]] — append-only operations log
