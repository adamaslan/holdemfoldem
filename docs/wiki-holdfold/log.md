# Wiki Operations Log

Append-only chronological record of every wiki operation. Parseable with `grep "^## \[" log.md | tail -10`.

---

## [2026-06-01] patch | code audit vs wiki — 8 discrepancies corrected | pages touched: 5

Patched `entity-signal-pipeline.md`, `concept-signal-scoring.md`, `entity-backend-api.md`, `overview.md`, `entity-mcp-finance.md` based on a line-by-line audit of `backend/main.py` and `gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp/`. Changes:

- **entity-signal-pipeline**: Added Stage 3.5 (suppression pipeline — previously undocumented). Replaced vague Stage 4 description with the full 7-path verdict decision tree including 0.85 fallback multiplier, NEUTRAL tie-breaker (confidence = 50.0), bearish strategy flip rule. Added indicator exposure gap note (41 computed internally, 4 exposed in response).
- **concept-signal-scoring**: Expanded confidence formula from 2 paths to 4 (added 0.85 fallback and 50.0 tie-breaker). Added signal collapsing explanation (strength keyword inference, no explicit `is_bullish` flag). Added bearish strategy override documentation.
- **entity-backend-api**: Escalated Cloud Run feature gap from Open Question to Known Failure. Enumerated exactly which `HoldFoldVerdict` fields are null in production (`position_pnl`, `position_aging`, `fib_levels`, all payoff fields). Corrected "needs verification" language to "confirmed".
- **overview**: Fixed `Multi-lot P&L ✅` to `⚠️ Local only`. Strengthened Cloud Run open issue to reflect confirmed production gap.
- **entity-mcp-finance**: Added exact indicator reading counts (15 core + ~26 expanded = ~41 total). Documented the 37-field gap between computed and exposed. Added signal collapsing mechanics.

---

## [2026-05-31] init | initial wiki creation | pages created: 12

Initial scaffolding of `docs/wiki-holdfold/` synthesized from `backend/main.py`, `docs/signal-pipeline.md`, `docs/ai-council-integration.md`, `docs/robustness-roadmap.md`, `README.md`, and the frontend source.

**Pages created:**
- Meta: `SCHEMA.md`, `index.md`, `log.md`, `overview.md`
- Entities: `entity-backend-api`, `entity-signal-pipeline`, `entity-firestore-cache`, `entity-options-payoff`, `entity-frontend-app`, `entity-council-proxy`, `entity-mcp-finance`
- Concepts: `concept-signal-scoring`
- Decisions: `decision-mcp-finance-as-shared-lib`, `decision-council-proxy-not-direct`, `decision-rule-based-ranking-fallback`

**Key findings / open issues surfaced:**
- `backend/cloud-run/main.py` is a simplified v2 that lacks multi-lot P&L, Fibonacci, and options payoff. The deployed Cloud Run backend regresses these features. This is the most important gap to close.
- `sys.path.insert` + `os.chdir` coupling to `gcp-app-w-mcp1` at a hardcoded path is fragile. Needs either vendoring or a published package.
- TypeScript `Verdict` type in `page.tsx` is hand-rolled, not generated from Pydantic. Schema drift risk.
- AI Council feature (`/api/council`) is dev-only — no deployed `COUNCIL_URL` configured for production.
- `docs/` is gitignored in `holdemfoldemapp` — this wiki will not appear in version control unless `.gitignore` is updated to allow `docs/wiki-holdfold/`.

**Schema compliance check:**
- All entity pages have required sections (What it is, Where used, Known failures, Open questions, See also): ✅
- All entity pages have ≥3 cross-links: ✅
- No secrets (GCP project IDs, Cloud Run URLs, API keys all use `{placeholders}`): ✅
- All pages in index.md: ✅

## [2026-08-28] ingest | CLI + MCP server build | pages touched: 5

Built `backend/core.py` (transport-agnostic verdict engine extracted from `backend/main.py`), `backend/cli/` (Typer `holdfold` CLI, hybrid in-process/HTTP transport, exit codes encode verdict), and `backend/mcp_server/` (`holdemfoldem-mcp` stdio MCP server wrapping the HTTP API as 3 tools: `get_verdict`, `evaluate_options_strategy`, `check_health`). Verified: 21 new pytest unit tests pass; full Playwright e2e suite (9 tests) passes unchanged against the refactored backend, confirming the `core.py` extraction preserved the HTTP contract exactly; live smoke tests against real ticker data (AAPL, MSFT, SPY) through both the CLI and the MCP dispatcher.

New pages: `entity-verdict-core.md`, `entity-cli.md`, `entity-mcp-server.md`, `decision-mcp-wraps-http-not-import.md`. Updated: `index.md`.

Also fixed `.gitignore` (`docs/*` blanket-ignored the entire `docs/` tree, including this wiki and `docs/cli-and-mcp-guide.md` — neither was ever actually in version control despite being written). Added explicit `!docs/wiki-holdfold/` and `!docs/cli-and-mcp-guide.md` exceptions; all other loose files under `docs/` remain gitignored as before.
