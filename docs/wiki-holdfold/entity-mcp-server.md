---
date: 2026-08-28
type: entity
tags: [mcp, backend, holdfold]
sources: [../backend/mcp_server/server.py]
---

# Entity: MCP Server (`backend/mcp_server/`)

An MCP server (`holdemfoldem-mcp`, stdio transport) that exposes the HOLD EM / FOLD EM verdict to any MCP client (e.g. Claude Code) as three tools. Not to be confused with `technical-analysis-mcp` in `gcp-app-w-mcp1/mcp-finance1` — that server exposes raw signals/indicators; this one exposes the finished verdict.

## What it is

Uses the low-level `mcp.server.Server` API (`@app.list_tools()` / `@app.call_tool()`), matching the house pattern in `gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp/server.py`, rather than FastMCP.

Three tools:

| Tool | Purpose |
|---|---|
| `get_verdict` | Core HOLD/FOLD for a symbol; optional `position_lots` for P&L |
| `evaluate_options_strategy` | Strategy + legs + premium → payoff, POP, breakevens |
| `check_health` | Backend + Firestore reachability |

**Wraps HTTP, does not import `core.py` directly.** `call_tool` POSTs to a running backend's `/api/analyze` / `GET /health` via `httpx`. See [[decision-mcp-wraps-http-not-import]] for why.

**Summarizes, never dumps the raw verdict** (`_summarize`). `HoldFoldVerdict` carries ~50 fields including a full `payoff_curve` (up to 60 points); returning it verbatim would burn the calling model's context on numbers it won't read. The summary always propagates `degraded`, `warnings`, and `suppressions` into the text — a model reading a clean-looking verdict has no other way to learn the data was thin.

Configured via `HOLDFOLD_BACKEND_URL` env var (default `http://localhost:8001`).

## Where used

Registered as an MCP server for local Claude Code sessions working on this repo (`.mcp.json` or `claude mcp add`). Requires the FastAPI backend (`backend/main.py`) running separately — the MCP server has no fallback if it's down; `get_verdict`/`evaluate_options_strategy` return a friendly "Backend unreachable" text result rather than throwing, so the calling model can react in-conversation instead of crashing the tool call.

## Known failures

- stdio MCP servers speak JSON-RPC on stdout; any stray `print()` would corrupt the protocol stream. All logging in `server.py` goes through `logging.basicConfig` (stderr by default) — verified no `print()` calls exist in the module.
- Verified in-process (calling `list_tools()`/`call_tool()` directly, bypassing the stdio transport) against a live backend on `localhost:8001`: `get_verdict` for AAPL, `check_health`, bad-symbol rejection, and backend-unreachable all returned the expected text.
- Not yet verified through the actual stdio JSON-RPC transport (e.g. via `npx @modelcontextprotocol/inspector`) — only the dispatcher functions were exercised directly.

## Open questions

- Should `evaluate_options_strategy` be merged into `get_verdict` (options fields already accepted by `AnalyzeRequest`) now that both wrap the same endpoint? Kept separate to keep each tool's `inputSchema` narrow, per general MCP tool-design guidance — narrow tools call more reliably than one tool with 20 optional parameters.

## See also

- [[entity-verdict-core]] — the engine behind the HTTP endpoint this wraps
- [[entity-backend-api]] — the HTTP endpoint itself
- [[decision-mcp-wraps-http-not-import]]
- [[decision-mcp-finance-as-shared-lib]] — the *other* MCP boundary in this system, at a different layer
