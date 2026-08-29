---
date: 2026-08-28
type: entity
tags: [cli, backend, holdfold, typer]
sources: [../backend/cli/app.py, ../backend/cli/client.py, ../backend/cli/render.py]
---

# Entity: CLI (`backend/cli/`)

`holdfold` — a Typer-based terminal client for the verdict engine, installed via `[project.scripts]` in `backend/pyproject.toml`.

## What it is

Three commands:

| Command | Purpose |
|---|---|
| `holdfold verdict SYMBOL [flags]` | Core question — HOLD EM / FOLD EM / NEUTRAL for one symbol |
| `holdfold watch SYM1 SYM2 ...` | Batch verdicts as a Rich table |
| `holdfold health` | Backend + Firestore reachability |

**Hybrid transport** (`cli/app.py::_dispatch`): tries `from core import compute_verdict` first (in-process, no server needed); falls back to `cli/client.py::post_analyze` (HTTP) on `ImportError`, or always uses HTTP when `--remote URL` is passed. This makes the CLI work both offline (with the `fin-ai1` mamba env + sibling `mcp-finance1` repo on disk) and against any reachable backend, including Cloud Run.

**Exit codes encode the verdict** — the single most important design choice, making the tool scriptable:

```
0 = HOLD EM
1 = FOLD EM
2 = NEUTRAL
3 = error (bad input, backend unreachable)
```

**Compound flag parsing** (`cli/app.py::_parse_lot`, `_parse_leg`):
- `--lot qty@cost[@YYYY-MM-DD]` → `PositionLot`, repeatable
- `--leg role:strike[:expiry]` → `OptionsLegRequest`, repeatable

Both raise `ValueError` on malformed input, which `verdict()` catches and turns into exit code 3 — date-format validation is deliberately left to `PositionLot.validate_acquired_at` in `core.py` rather than re-implemented here.

**Rendering** (`cli/render.py`) always surfaces `degraded`, `warnings`, and `suppressions` alongside the headline verdict — these fields exist because the pipeline can silently return a weaker answer, and hiding them defeats the point of a terminal client.

## Where used

Local dev / scripting entry point. Not deployed anywhere — runs on the developer's machine via the `fin-ai1` mamba env.

## Known failures

- `python -m cli` (rather than the installed `holdfold` script) requires running from `backend/` so `cli` and `core` are importable — no `pip install -e` step was run as part of this build; see [[decision-mcp-wraps-http-not-import]] sibling note in pyproject.toml for the packaging shape.
- In-process mode logs INFO-level Firestore/gcloud auth warnings to stderr; `--json` output on stdout stays clean (verified: piping stdout alone yields valid JSON).

## Open questions

- No `holdfold verdict --watch-interval` (polling) — `watch` is a one-shot batch, not a live loop.

## See also

- [[entity-verdict-core]] — what `_dispatch()` calls in-process
- [[entity-mcp-server]] — the sibling HTTP-wrapping surface
- [[decision-mcp-wraps-http-not-import]]
