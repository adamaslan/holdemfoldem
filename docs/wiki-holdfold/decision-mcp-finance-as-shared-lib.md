---
date: 2026-05-31
type: decision
tags: [architecture, mcp, shared-library, cross-repo]
sources: [../README.md, ../backend/main.py]
---

# Decision: MCP Finance as Shared Library

## Decision

The technical analysis code (indicator calculation, signal detection, ranking) lives in `gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp/`, not in `holdemfoldemapp/backend/`. The holdemfoldemapp backend imports it via `sys.path.insert` at runtime.

## Date

Original structure; documented 2026-05-31.

## Context

The signal analysis pipeline (18 detectors, 80+ indicators, Gemini ranking) is a substantial body of code that is also used by the `gcp3` backend via the MCP server protocol. Duplicating it into `holdemfoldemapp` would create two codebases to maintain.

## Alternatives considered

| Alternative | Why not |
|-------------|---------|
| Copy/vendor into `holdemfoldemapp/backend/` | Two copies to maintain; changes to signals must be applied twice |
| Publish as a private Python package | Requires packaging infrastructure (PyPI private registry or VCS dependency); more overhead than the current direct-path approach |
| Call `gcp3` backend as a service for signals | Network latency + availability dependency; would make holdemfoldemapp dependent on gcp3 being up |

## Consequences

**Enables:**
- Single source of truth for all signal logic across gcp3, holdemfoldemapp, and future consumers
- Changes to detectors or scoring instantly reflected in both backends

**Rules out:**
- Independent deployment without `gcp-app-w-mcp1` being present at build time (the Cloud Run Dockerfile works around this by copying the source at build time)
- Version-pinning: holdemfoldemapp always runs whatever is on disk in `mcp-finance1` — no lockfile

## Validated by

The Cloud Run deploy script (`deploy-backend.sh`) successfully builds and deploys with this pattern. Local dev works via `sys.path.insert` (`backend/main.py:36-40`), which also issues an `os.chdir(_mcp_path)` so the process CWD becomes the mcp source root at runtime. The two entrypoints import the library under different module paths (`src.technical_analysis_mcp` locally vs `technical_analysis_mcp` on Cloud Run) — see [[entity-mcp-finance]] for the divergence.

## See also

- [[entity-mcp-finance]] — the shared library
- [[entity-backend-api]] — the consumer
- [[entity-signal-pipeline]] — what the library implements
