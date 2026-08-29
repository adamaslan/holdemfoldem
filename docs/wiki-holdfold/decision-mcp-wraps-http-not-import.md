---
date: 2026-08-28
type: decision
tags: [mcp, architecture, holdfold]
sources: [../backend/mcp_server/server.py, ../backend/core.py]
---

# Decision: MCP Server Wraps HTTP, Not `core.py` Import

## Decision

`backend/mcp_server/server.py` calls the running FastAPI backend over HTTP (`POST /api/analyze`), rather than importing `core.compute_verdict` directly into the MCP server process.

## Date

2026-08-28.

## Context

Building an MCP server to expose the HOLD EM / FOLD EM verdict, alongside a new CLI, required choosing where `compute_verdict` gets called from. Three surfaces now exist that need the verdict: the FastAPI app, the CLI, and the MCP server.

## Alternatives considered

| Alternative | Why not |
|---|---|
| MCP server imports `core.py` directly | Would spin up a second Firestore client and trigger `core.py`'s `os.chdir()` side effect in a second process — two processes independently managing the same cache/CWD state |
| Extend `technical-analysis-mcp` (the upstream shared library) with a `holdfold_verdict` tool | Couples this app's product logic (verdict thresholds, suppressions, options payoff math) into a library documented as shared infrastructure across `gcp3` and other consumers — contradicts [[decision-mcp-finance-as-shared-lib]] |
| Wrap HTTP ✅ | Keeps `_build_verdict`/`compute_verdict` living in exactly one process (the FastAPI backend); the MCP server is a thin, disposable client like any other |

The CLI, by contrast, *does* import `core.py` directly (with an HTTP fallback) — see [[entity-cli]]. The difference: the CLI is a single ad-hoc process per invocation, so a second Firestore client per invocation is cheap and short-lived. The MCP server is a long-running stdio process, so a second persistent Firestore client would be a standing duplicate resource.

## Consequences

**Enables:**
- Single source of truth for the verdict logic and its Firestore cache stays in the FastAPI process
- The MCP server is a small (~250 line), easily-replaceable adapter with no mamba-env / sibling-repo dependency of its own beyond `httpx` + `mcp`

**Rules out:**
- Using `get_verdict` / `evaluate_options_strategy` when the FastAPI backend isn't running — the MCP server has no local fallback and returns a "Backend unreachable" text result instead

## Validated by

In-process dispatcher tests (`backend/tests/test_mcp_server.py`, mocking `_post_analyze`/`_get_health`) plus a live run against a `uvicorn main:app` instance on `localhost:8001`: `get_verdict` for AAPL returned a correct summarized HOLD EM verdict, `check_health` reported Firestore reachable, and pointing `HOLDFOLD_BACKEND_URL` at an unused port produced the expected "Backend unreachable" text.

## See also

- [[entity-mcp-server]]
- [[entity-verdict-core]]
- [[entity-cli]]
- [[decision-mcp-finance-as-shared-lib]]
