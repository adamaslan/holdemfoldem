---
date: 2026-08-28
type: entity
tags: [backend, refactor, verdict, holdfold, shared-core]
sources: [../backend/core.py, ../backend/main.py]
---

# Entity: Verdict Core (`backend/core.py`)

Transport-agnostic extraction of the HOLD EM / FOLD EM verdict engine out of `backend/main.py`, so the FastAPI app, CLI, and MCP server can all call the same logic without importing FastAPI or triggering route registration.

## What it is

`compute_verdict(req: AnalyzeRequest, request_id: str | None = None) -> HoldFoldVerdict` is the entry point — the exact body of the old `POST /api/analyze` route, with HTTP concerns (status codes, `Response` headers) removed. It:

- validates the symbol and period (`validate_symbol`, `validate_period`)
- runs `analyze_security` + `get_trade_plan` + `analyze_fibonacci` in parallel via `asyncio.gather`, Firestore-cached
- runs `options_risk_analysis` best-effort when `options_strategy` is set
- calls `_build_verdict` to assemble the `HoldFoldVerdict`

Errors surface as plain Python exceptions instead of `HTTPException`, so callers map them to their own error surface:

| Exception | Meaning | FastAPI maps to | CLI maps to | MCP maps to |
|---|---|---|---|---|
| `ValueError` | Bad symbol/period | 400 | exit code 3 | error text in tool result |
| `AnalysisUnavailableError` | Upstream MCP Finance pipeline failed | 503 | exit code 3 | error text in tool result |

`main.py` is now a ~50-line thin adapter: it imports `AnalyzeRequest`, `HoldFoldVerdict`, `compute_verdict`, `check_backend_health`, `AnalysisUnavailableError` from `core.py`, and only handles the request-id header and exception→HTTPException translation.

`check_backend_health()` replaces the old inline `/health` handler body — same `{"status", "version", "firestore"}` shape.

## Where used

- `backend/main.py` — FastAPI HTTP adapter (`POST /api/analyze`, `GET /health`)
- `backend/cli/app.py` — `_dispatch()` imports `core.compute_verdict` directly when running in-process; falls back to HTTP via `cli/client.py` when `core.py` can't import (missing mamba env / sibling `mcp-finance1` repo) or when `--remote` is passed
- `backend/mcp_server/server.py` — does **not** import `core.py` directly; wraps the HTTP endpoint instead (see [[decision-mcp-wraps-http-not-import]])

## Known failures

- `core.py` (like the old `main.py`) calls `os.chdir()` at import time to point the process CWD at the sibling `mcp-finance1` repo. Any process that imports it has its working directory changed. The CLI's in-process path must resolve user-supplied paths to absolute *before* importing `core`. If neither the sibling checkout nor `/app` exists, `core.py` now raises `ImportError` explicitly (rather than letting `os.chdir()` raise a bare `FileNotFoundError`), so callers that catch `ImportError` around `import core` — e.g. `cli/app.py`'s HTTP-only fallback — see the failure mode they're built to handle.
- The extraction was verified by re-running the full Playwright e2e suite (`frontend/e2e/app.spec.ts`, 9 tests) against the refactored backend with no changes to the HTTP contract — all passed.
- **Packaging gap (found in review, fixed in the same PR):** the Cloud Run deploy (`deploy-backend.sh` + `backend/cloud-run/Dockerfile`) originally copied only `backend/main.py` into the build context/image, not `backend/core.py`. Since `main.py` now does `from core import ...`, this would have failed at Cloud Run startup with `ModuleNotFoundError: core`. Fixed by copying `core.py` alongside `main.py` in both the deploy script and the Dockerfile `COPY` step.
- **Three live `/api/analyze` data defects (fixed in PR #18, see log):** (1) `fib_levels` carried a duplicate 88.6% level, because the upstream Fibonacci registry emits that ratio under two kinds (RETRACE and HARMONIC); `_extract_fib_levels` now dedupes by ratio name plus near-identical price (RETRACE preferred) *before* the 8-level cap, so the cap no longer spends a slot on a duplicate. (2) `atr` was always null and `volatility_regime` therefore `unknown`, because `analyze_security` never emits `indicators["atr"]`; `_resolve_atr` falls back to the trade plan's `risk_assessment.metrics.atr`, treating zero/NaN (its error placeholder) as missing. (3) Suppression codes leaked as `SuppressionCode.NO_TREND`: the upstream code is a `str` Enum, and `str()` of a member on Python 3.11+ gives the qualified name, so the label lookup in `SUPPRESSION_LABELS` missed and the raw string became its own label. `_suppression_code` unwraps the enum value. Regression tests live in `backend/tests/test_analyze_data_quality.py`.

## Open questions

- ~~Should `backend/cloud-run/main.py` also be migrated onto `core.py`?~~ **Resolved in PR #15:** it was not deployed (this PR's own packaging fix made the deploy ship `main.py` + `core.py`), so it was archived to `file-archive/` rather than migrated. `tests/test_deployed_entrypoint.py` now exercises the shipped app over HTTP.

## See also

- [[entity-backend-api]] — the FastAPI adapter that now wraps this
- [[entity-cli]] — the CLI's in-process consumer
- [[entity-mcp-server]] — the MCP server's HTTP consumer
- [[decision-mcp-wraps-http-not-import]]
