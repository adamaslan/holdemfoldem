# Building a CLI and an MCP Server for Hold Em or Fold Em

How to expose the existing `/api/analyze` verdict engine as (a) a terminal CLI
and (b) an MCP server, without duplicating the scoring logic.

---

## 0. What already exists (read this first)

The important architectural fact: **this app is already an MCP client.**

```
yfinance / Finnhub
        │
        ▼
technical-analysis-mcp          ← gcp-app-w-mcp1/mcp-finance1/src/
  (mcp.server.Server, stdio)      analyze_security, get_trade_plan,
        │                         analyze_fibonacci, options_risk_analysis
        │  imported as a library (NOT over MCP protocol)
        ▼
backend/main.py                 ← FastAPI, port 8001/8080
  POST /api/analyze               _build_verdict() = the HOLD/FOLD logic
  GET  /health
        │
        ▼
frontend/src/app/api/analyze/route.ts   ← Next.js proxy
        │
        ▼
frontend/src/app/page.tsx
```

Two things follow from this:

1. **`_build_verdict()` in [backend/main.py](../backend/main.py) is the crown
   jewel.** It is ~300 lines of HOLD EM / FOLD EM logic, suppressions, multi-lot
   P&L, Fibonacci confluence, and options payoff math. The CLI and the MCP
   server must both call it — never reimplement it.
2. **There is already a decision on record** —
   [decision-mcp-finance-as-shared-lib.md](wiki-holdfold/decision-mcp-finance-as-shared-lib.md)
   — that `mcp-finance1` is consumed as a *library import*, not over the MCP
   wire. Your new MCP server sits at a different layer: it exposes the
   **verdict**, not the raw signals. Don't confuse the two.

### The two request/response shapes

`AnalyzeRequest` ([backend/main.py:218](../backend/main.py#L218)) is large.
The fields that matter for a CLI:

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol` | str | — | required; `^[A-Z0-9][A-Z0-9.\-]{0,11}$` |
| `period` | str | `3mo` | must be in `VALID_PERIODS` |
| `asset_type` | str | `stock` | |
| `risk_profile` | str | `moderate` | |
| `options_strategy` | str? | None | see strategy list below |
| `options_legs` | list | None | `{role, strike, expiry, premium}` |
| `dte` | int? | None | days to expiration |
| `net_premium` | float? | None | **+ = credit, − = debit** |
| `position_lots` | list | None | multi-lot; preferred over legacy flat fields |
| `cost_basis_method` | enum | `average` | `fifo`\|`lifo`\|`average`\|`specific` |
| `adjust_for_splits` | bool | `true` | |

`VALID_PERIODS` ([backend/main.py:126](../backend/main.py#L126)):
`15m 1h 4h 1d 5d 1mo 3mo 6mo 1y 2y 5y 10y ytd max`

Options strategies recognized by the payoff engine
([backend/main.py:661+](../backend/main.py#L661)):
`covered_call`, `bull_call_spread`, `bear_put_spread`, `call_credit_spread`,
`put_credit_spread`, `iron_condor`, `iron_butterfly`, `straddle`, `strangle`,
`long_call`, `long_put`.

`HoldFoldVerdict` ([backend/main.py:305](../backend/main.py#L305)) returns ~50
fields across core / signals / indicators / suppressions / trade plan /
position P&L / Fibonacci / options / summary / robustness.

---

## 1. Decide the architecture before writing code

There are three ways to build each surface. Pick deliberately.

### CLI options

| Approach | How | Pro | Con |
|---|---|---|---|
| **A. HTTP client** | CLI POSTs to a running backend | Trivial; works against Cloud Run | Requires a server running |
| **B. Direct import** | CLI imports `_build_verdict` + MCP tools | No server, no network | Needs the full mamba env + sibling repo on disk |
| **C. Hybrid** ✅ | Try local import, fall back to HTTP (`--remote`) | Works both ways | Slightly more code |

**Recommendation: C.** The import path is what makes the CLI genuinely useful
offline; the HTTP path is what makes it work from any machine against Cloud Run.

### MCP options

| Approach | How | Pro | Con |
|---|---|---|---|
| **A. Wrap HTTP** ✅ | MCP tool → `POST /api/analyze` | Single source of truth; backend already validates | Needs backend reachable |
| **B. Re-import verdict logic** | MCP server imports `_build_verdict` | No HTTP hop | Two processes duplicating env setup + Firestore clients |
| **C. Extend upstream MCP** | Add a `holdfold_verdict` tool to `technical-analysis-mcp` | One server to configure | Couples this app's product logic into a shared library — contradicts the existing decision doc |

**Recommendation: A.** Wrapping HTTP keeps `_build_verdict` in exactly one
process, which matters because it holds the Firestore cache client and the
`os.chdir()` side effect at
[backend/main.py:39](../backend/main.py#L39).

> ⚠️ Note that `backend/main.py` calls `os.chdir()` at import time. Any process
> that imports it has its working directory changed out from under it. The CLI's
> import path must account for this (resolve all user paths to absolute
> **before** importing).

---

## 2. Refactor first: extract a shared core

Both surfaces need the verdict without the HTTP layer. Do this before writing
either one.

Create `backend/core.py`:

```python
"""Transport-agnostic verdict engine.

Extracted from main.py so the FastAPI app, the CLI, and the MCP server can all
call the same logic without importing FastAPI or triggering route registration.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

logger = logging.getLogger(__name__)


async def compute_verdict(req: "AnalyzeRequest") -> "HoldFoldVerdict":
    """Run the full analyze pipeline and build a verdict.

    This is the body of the /api/analyze route with the HTTP concerns
    (Response headers, HTTPException) removed.

    Args:
        req: A validated AnalyzeRequest.

    Returns:
        The assembled HoldFoldVerdict.

    Raises:
        ValueError: If the symbol or period fails validation.
        AnalysisUnavailableError: If the upstream data pipeline fails.
    """
    ...
```

The mechanical move:

1. Move `AnalyzeRequest`, `HoldFoldVerdict`, and every `_helper` out of
   `main.py` into `core.py`.
2. Move the body of the `analyze()` route into `compute_verdict()`, replacing
   `raise HTTPException(400, ...)` with `raise ValueError(...)` and
   `HTTPException(503, ...)` with a custom `AnalysisUnavailableError`.
3. Leave `main.py` as a thin adapter:

```python
from .core import AnalyzeRequest, HoldFoldVerdict, compute_verdict, AnalysisUnavailableError


@app.post("/api/analyze", response_model=HoldFoldVerdict)
async def analyze(req: AnalyzeRequest, response: Response) -> HoldFoldVerdict:
    request_id = str(uuid.uuid4())
    response.headers["X-Request-Id"] = request_id
    try:
        return await compute_verdict(req, request_id=request_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except AnalysisUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
```

This is a pure refactor — the HTTP contract does not change, so the existing
Playwright e2e tests in [frontend/e2e/](../frontend/e2e/) are your regression
check. Run them before and after.

---

## 3. Build the CLI

### 3.1 Layout

```
backend/
├── core.py              # shared verdict engine (step 2)
├── main.py              # FastAPI adapter
└── cli/
    ├── __init__.py
    ├── __main__.py      # enables `python -m cli`
    ├── app.py           # argument parsing + command dispatch
    ├── client.py        # HTTP transport (--remote)
    └── render.py        # terminal formatting
```

### 3.2 Choose the argument parser

`argparse` is stdlib and adds zero dependencies. `typer` gives you type-hint
derived flags, shell completion, and colored help for one dependency. Given the
size of `AnalyzeRequest` (multi-lot positions, options legs), **use `typer`** —
hand-rolling `argparse` for nested structures is where CLIs rot.

```bash
mamba activate fin-ai1
mamba install -c conda-forge typer rich
```

`rich` is what makes a verdict readable in a terminal; it is worth the dep.

### 3.3 The command surface

Design the commands around what a user actually asks, not around the API shape:

```
holdfold verdict AAPL                      # the core question
holdfold verdict AAPL --period 1y --json
holdfold verdict SPY --strategy iron_condor --dte 30 --net-premium 2.10 \
                     --leg sell_put:400 --leg buy_put:390 \
                     --leg sell_call:450 --leg buy_call:460
holdfold verdict NVDA --lot 100@85.50@2024-03-01 --lot 50@120@2025-01-15 \
                      --cost-basis fifo
holdfold watch AAPL MSFT NVDA              # batch, one row each
holdfold health                            # backend + Firestore status
```

### 3.4 Implementation

`backend/cli/app.py`:

```python
"""Hold Em or Fold Em — command line interface."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Annotated

import typer

from .render import render_verdict, render_table

app = typer.Typer(
    name="holdfold",
    help="Instant HOLD EM / FOLD EM verdict for any US stock, ETF, or option.",
    no_args_is_help=True,
)

EXIT_HOLD = 0
EXIT_FOLD = 1
EXIT_NEUTRAL = 2
EXIT_ERROR = 3

_VERDICT_EXIT_CODES = {
    "HOLD EM": EXIT_HOLD,
    "FOLD EM": EXIT_FOLD,
    "NEUTRAL": EXIT_NEUTRAL,
}


@app.command()
def verdict(
    symbol: Annotated[str, typer.Argument(help="Ticker, e.g. AAPL or BTC-USD")],
    period: Annotated[str, typer.Option("--period", "-p")] = "3mo",
    asset_type: Annotated[str, typer.Option("--asset-type")] = "stock",
    risk_profile: Annotated[str, typer.Option("--risk")] = "moderate",
    strategy: Annotated[str | None, typer.Option("--strategy")] = None,
    dte: Annotated[int | None, typer.Option("--dte")] = None,
    net_premium: Annotated[float | None, typer.Option("--net-premium")] = None,
    leg: Annotated[list[str] | None, typer.Option("--leg", help="role:strike[:expiry]")] = None,
    lot: Annotated[list[str] | None, typer.Option("--lot", help="qty@cost[@YYYY-MM-DD]")] = None,
    cost_basis: Annotated[str, typer.Option("--cost-basis")] = "average",
    as_json: Annotated[bool, typer.Option("--json")] = False,
    remote: Annotated[str | None, typer.Option("--remote", help="Backend URL")] = None,
) -> None:
    """Get a HOLD EM / FOLD EM verdict for SYMBOL.

    Exit code encodes the verdict: 0 HOLD EM, 1 FOLD EM, 2 NEUTRAL, 3 error.
    """
    request = _build_request(
        symbol=symbol, period=period, asset_type=asset_type,
        risk_profile=risk_profile, strategy=strategy, dte=dte,
        net_premium=net_premium, legs=leg or [], lots=lot or [],
        cost_basis=cost_basis,
    )

    try:
        result = asyncio.run(_dispatch(request, remote))
    except ValueError as e:
        typer.secho(f"Invalid input: {e}", fg="red", err=True)
        raise typer.Exit(EXIT_ERROR) from e
    except ConnectionError as e:
        typer.secho(f"Backend unreachable: {e}", fg="red", err=True)
        raise typer.Exit(EXIT_ERROR) from e

    if as_json:
        json.dump(result, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        render_verdict(result)

    raise typer.Exit(_VERDICT_EXIT_CODES.get(result["verdict"], EXIT_ERROR))
```

The dispatch is where the hybrid transport lives:

```python
async def _dispatch(request: dict, remote: str | None) -> dict:
    """Route to the local engine or a remote backend.

    Args:
        request: Raw request dict matching AnalyzeRequest.
        remote: Backend base URL. If None, try the in-process engine first.

    Returns:
        The verdict as a plain dict.
    """
    if remote is not None:
        from .client import post_analyze
        return await post_analyze(remote, request)

    try:
        from ..core import AnalyzeRequest, compute_verdict
    except ImportError:
        # No local env — fall back to the configured backend.
        from .client import post_analyze
        return await post_analyze(_default_backend_url(), request)

    verdict = await compute_verdict(AnalyzeRequest(**request))
    return verdict.model_dump()
```

**Exit codes carry the verdict.** This is the single most valuable CLI design
choice here — it makes the tool scriptable:

```bash
holdfold verdict AAPL --json >/dev/null && echo "hold" || echo "not hold"
```

### 3.5 Parsing the compound flags

```python
def _parse_lot(raw: str) -> dict:
    """Parse a --lot value of the form qty@cost_basis[@acquired_at].

    Args:
        raw: e.g. "100@85.50@2024-03-01"

    Returns:
        A dict matching PositionLot.

    Raises:
        ValueError: If the format is malformed or the numbers don't parse.
    """
    parts = raw.split("@")
    if len(parts) not in (2, 3):
        raise ValueError(f"--lot must be qty@cost[@YYYY-MM-DD], got {raw!r}")

    try:
        qty, cost_basis = float(parts[0]), float(parts[1])
    except ValueError as e:
        raise ValueError(f"--lot has non-numeric qty or cost: {raw!r}") from e

    lot = {"qty": qty, "cost_basis": cost_basis}
    if len(parts) == 3:
        lot["acquired_at"] = parts[2]
    return lot
```

Note the backend already validates `acquired_at` via
`PositionLot.validate_acquired_at` — let it, and surface the pydantic error
rather than re-validating the date format here.

### 3.6 Rendering

`render.py` should lead with the verdict and degrade gracefully:

```python
from rich.console import Console
from rich.panel import Panel

_VERDICT_STYLES = {"HOLD EM": "bold green", "FOLD EM": "bold red", "NEUTRAL": "bold yellow"}

console = Console()


def render_verdict(v: dict) -> None:
    """Print a verdict as a terminal panel."""
    style = _VERDICT_STYLES.get(v["verdict"], "bold white")
    console.print(Panel(
        f"[{style}]{v['verdict']}[/]  {v['confidence']}% confidence\n"
        f"${v['price']:.2f}  ·  {v['bias']}  ·  risk: {v['risk_level']}",
        title=f"{v['symbol']} ({v['asset_type']})",
    ))

    if v.get("degraded"):
        console.print("[yellow]⚠ degraded pipeline[/]")
    for w in v.get("warnings", []):
        console.print(f"[yellow]⚠ {w}[/]")
    for s in v.get("suppressions", []):
        console.print(f"[dim]suppressed: {s['label']}[/]")
```

Surfacing `degraded`, `warnings`, and `suppressions` is not optional polish —
those fields exist because the pipeline can silently return a weaker answer, and
a CLI that hides them is worse than no CLI.

### 3.7 Install it

Add to a `backend/pyproject.toml`:

```toml
[project.scripts]
holdfold = "cli.app:app"
```

```bash
mamba activate fin-ai1
pip install -e /Users/adamaslan/code/holdemfoldemapp/backend   # inside the env, per mamba rules
holdfold verdict AAPL
```

---

## 4. Build the MCP server

### 4.1 Match the house pattern

The existing `technical-analysis-mcp` uses the **low-level
`mcp.server.Server`** API with `@app.list_tools()` and `@app.call_tool()` — not
`FastMCP` ([server.py:36](../../gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp/server.py#L36)).
Match it, so both servers read the same way.

### 4.2 Layout

```
backend/mcp_server/
├── __init__.py
├── __main__.py
└── server.py
```

### 4.3 The tool surface

Do **not** expose one giant `analyze` tool with 20 optional parameters. Models
call narrow tools more reliably. Three tools:

| Tool | Purpose |
|---|---|
| `get_verdict` | Core HOLD/FOLD for a symbol (+ optional position lots) |
| `evaluate_options_strategy` | Strategy + legs + premium → payoff, POP, breakevens |
| `check_health` | Backend + Firestore reachability |

### 4.4 Implementation

`backend/mcp_server/server.py`:

```python
"""MCP server exposing Hold Em or Fold Em verdicts.

Wraps the backend's /api/analyze endpoint so the verdict logic lives in exactly
one process. See docs/cli-and-mcp-guide.md for why HTTP rather than a direct
import.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import httpx
from mcp.server import Server
from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)

app = Server("holdemfoldem-mcp")

BACKEND_URL = os.getenv("HOLDFOLD_BACKEND_URL", "http://localhost:8001")
REQUEST_TIMEOUT_SECONDS = 60.0

_VALID_PERIODS = [
    "15m", "1h", "4h", "1d", "5d",
    "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max",
]

_OPTIONS_STRATEGIES = [
    "covered_call", "bull_call_spread", "bear_put_spread",
    "call_credit_spread", "put_credit_spread", "iron_condor",
    "iron_butterfly", "straddle", "strangle", "long_call", "long_put",
]


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available MCP tools."""
    return [
        Tool(
            name="get_verdict",
            description=(
                "Get a HOLD EM / FOLD EM / NEUTRAL verdict for a US stock or ETF, "
                "combining 150+ technical signals with a risk-sized trade plan. "
                "Optionally include held tax lots to get unrealized P&L and aging."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Ticker symbol, e.g. AAPL, SPY, BTC-USD",
                    },
                    "period": {
                        "type": "string",
                        "enum": _VALID_PERIODS,
                        "default": "3mo",
                        "description": "Lookback window. 3mo suits swing-trade horizons.",
                    },
                    "risk_profile": {
                        "type": "string",
                        "default": "moderate",
                        "description": "Risk tolerance driving stop/target sizing.",
                    },
                    "position_lots": {
                        "type": "array",
                        "description": "Tax lots currently held, for P&L and aging.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "qty": {"type": "number"},
                                "cost_basis": {"type": "number", "description": "Per-share, pre-fee"},
                                "acquired_at": {"type": "string", "description": "ISO 8601 date"},
                                "side": {"type": "string", "enum": ["long", "short"], "default": "long"},
                            },
                            "required": ["qty", "cost_basis"],
                        },
                    },
                    "cost_basis_method": {
                        "type": "string",
                        "enum": ["fifo", "lifo", "average", "specific"],
                        "default": "average",
                    },
                },
                "required": ["symbol"],
            },
        ),
        Tool(
            name="evaluate_options_strategy",
            description=(
                "Evaluate a multi-leg options strategy on a symbol: payoff curve, "
                "max profit/loss, breakevens, probability of profit, and Greeks."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "options_strategy": {"type": "string", "enum": _OPTIONS_STRATEGIES},
                    "options_legs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "role": {
                                    "type": "string",
                                    "description": "e.g. buy_call, sell_put",
                                },
                                "strike": {"type": "number"},
                                "expiry": {"type": "string", "description": "ISO 8601 date"},
                            },
                            "required": ["role"],
                        },
                    },
                    "dte": {"type": "integer", "description": "Days to expiration"},
                    "net_premium": {
                        "type": "number",
                        "description": "Per share. Positive = credit received, negative = debit paid.",
                    },
                    "period": {"type": "string", "enum": _VALID_PERIODS, "default": "3mo"},
                },
                "required": ["symbol", "options_strategy"],
            },
        ),
        Tool(
            name="check_health",
            description="Check whether the Hold Em or Fold Em backend and its Firestore cache are reachable.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]
```

The dispatcher:

```python
@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Route an MCP tool call to the backend."""
    if name == "check_health":
        return [TextContent(type="text", text=json.dumps(await _get_health(), indent=2))]

    if name in ("get_verdict", "evaluate_options_strategy"):
        payload = {k: v for k, v in arguments.items() if v is not None}
        try:
            verdict = await _post_analyze(payload)
        except httpx.HTTPStatusError as e:
            detail = _extract_detail(e.response)
            logger.warning("Backend rejected %s: %s", name, detail)
            return [TextContent(type="text", text=f"Analysis failed: {detail}")]
        except httpx.RequestError as e:
            logger.error("Backend unreachable: %s", e)
            return [TextContent(
                type="text",
                text=f"Backend unreachable at {BACKEND_URL}. Is the FastAPI server running?",
            )]
        return [TextContent(type="text", text=_summarize(verdict))]

    raise ValueError(f"Unknown tool: {name}")


async def _post_analyze(payload: dict[str, Any]) -> dict[str, Any]:
    """POST to the backend's analyze endpoint.

    Raises:
        httpx.HTTPStatusError: On a non-2xx response.
        httpx.RequestError: If the backend is unreachable.
    """
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(f"{BACKEND_URL}/api/analyze", json=payload)
        response.raise_for_status()
        return response.json()
```

### 4.5 Summarize — do not dump the raw verdict

`HoldFoldVerdict` has ~50 fields including a full `payoff_curve`. Returning it
verbatim burns the model's context on numbers it will not read. Return prose
plus the fields that drive a decision, and let the model ask for more:

```python
def _summarize(v: dict[str, Any]) -> str:
    """Render a verdict as compact text for an LLM consumer."""
    lines = [
        f"{v['symbol']} ({v['asset_type']}): {v['verdict']} "
        f"at {v['confidence']}% confidence.",
        f"Price ${v['price']:.2f} · bias {v['bias']} · risk {v['risk_level']}"
        f"{' · cached' if v.get('cached') else ''}",
        f"Signals: {v['bullish_count']} bullish / {v['bearish_count']} bearish "
        f"(avg score {v['avg_score']:.0f}/100)",
    ]

    if v.get("entry") is not None:
        lines.append(
            f"Trade plan: entry ${v['entry']} · stop ${v['stop']} · "
            f"target ${v['target']} · R/R {v['risk_reward']}"
        )
    if v.get("suppressions"):
        lines.append("Suppressed: " + ", ".join(s["label"] for s in v["suppressions"]))
    if v.get("max_profit") is not None:
        lines.append(
            f"Options: max profit ${v['max_profit']} · max loss ${v['max_loss']} · "
            f"POP {v.get('pop')}% · breakevens {v.get('breakeven_prices')}"
        )
    if v.get("degraded"):
        lines.append("⚠ Pipeline ran in DEGRADED mode — treat with lower confidence.")
    for w in v.get("warnings", []):
        lines.append(f"⚠ {w}")

    lines.append(v["summary"])
    lines.append(f"(disclaimer v{v['disclaimer_version']} — not financial advice)")
    return "\n".join(lines)
```

Propagating `degraded`, `warnings`, and `suppressions` into the text matters
more here than in the CLI: a model reading a clean-looking verdict has no other
way to learn the data was thin.

### 4.6 Entry point

```python
def main() -> None:
    """Run the MCP server over stdio."""
    from mcp.server.stdio import stdio_server

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    async def run_server() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

    asyncio.run(run_server())


if __name__ == "__main__":
    main()
```

> Logging to **stderr only**. stdio MCP servers speak JSON-RPC on stdout — a
> stray `print()` corrupts the protocol stream. `logging.basicConfig` defaults
> to stderr, which is why the upstream server uses it.

### 4.7 Register it

```bash
claude mcp add holdemfoldem \
  --env HOLDFOLD_BACKEND_URL=http://localhost:8001 \
  -- /opt/homebrew/Caskroom/miniforge/base/envs/fin-ai1/bin/python \
     -m mcp_server
```

Or in `.mcp.json`:

```json
{
  "mcpServers": {
    "holdemfoldem": {
      "command": "/opt/homebrew/Caskroom/miniforge/base/envs/fin-ai1/bin/python",
      "args": ["-m", "mcp_server"],
      "cwd": "/Users/adamaslan/code/holdemfoldemapp/backend",
      "env": { "HOLDFOLD_BACKEND_URL": "http://localhost:8001" }
    }
  }
}
```

Use the **absolute interpreter path** from the `fin-ai1` env. An MCP server is
launched by the client, not by your shell, so `mamba activate` has not run and
a bare `python` will be the wrong one.

---

## 5. Testing

### CLI

```python
from typer.testing import CliRunner
from cli.app import app

runner = CliRunner()


def test_verdict_exit_code_encodes_hold(monkeypatch):
    monkeypatch.setattr("cli.app._dispatch", _fake_dispatch(verdict="HOLD EM"))
    result = runner.invoke(app, ["verdict", "AAPL"])
    assert result.exit_code == 0


def test_invalid_symbol_exits_error():
    result = runner.invoke(app, ["verdict", "NOT_A_REAL_TICKER_AT_ALL"])
    assert result.exit_code == 3
```

### MCP

Test the dispatcher directly — no protocol harness needed:

```python
import pytest
from mcp_server.server import call_tool


@pytest.mark.asyncio
async def test_unknown_tool_raises():
    with pytest.raises(ValueError, match="Unknown tool"):
        await call_tool("nope", {})


@pytest.mark.asyncio
async def test_backend_down_returns_message(monkeypatch):
    monkeypatch.setattr("mcp_server.server._post_analyze", _raise(httpx.ConnectError("down")))
    [content] = await call_tool("get_verdict", {"symbol": "AAPL"})
    assert "unreachable" in content.text
```

Then verify the wire protocol interactively:

```bash
npx @modelcontextprotocol/inspector \
  /opt/homebrew/Caskroom/miniforge/base/envs/fin-ai1/bin/python -m mcp_server
```

---

## 6. Suggested build order

1. **Extract `backend/core.py`** — pure refactor, e2e tests are the check.
2. **CLI, HTTP-only** (`--remote` path). Smallest thing that works end to end.
3. **CLI local-import path.** Watch the `os.chdir()` side effect.
4. **MCP `get_verdict`** — one tool, wrapping HTTP.
5. **MCP `evaluate_options_strategy` + `check_health`.**
6. **Package both** via `[project.scripts]`.

Steps 1–2 give a usable tool; each later step is independently shippable.

---

## 7. Conventions to respect in this repo

- **Env:** `fin-ai1` for this app (per the README's local-dev block). Never
  `pip install` outside a mamba env.
- **Branching:** the current branch `feat/ai-council-commentary` has an open PR
  — per `no-conflicts1`, cut a new branch from `origin/main` for this work:
  `git fetch origin main && git checkout -b feat/cli-and-mcp origin/main`
- **Wiki:** this repo has [docs/wiki-holdfold/](wiki-holdfold/). When you open
  the PR, follow its `SCHEMA.md` — likely a new `entity-cli.md`, an
  `entity-mcp-server.md`, a `decision-mcp-wraps-http-not-import.md`, plus
  `index.md` and a `log.md` line.
- **Archiving:** docs are archived to `docs/archive/`, never deleted.
- **Disclaimer:** every surface must carry it. `disclaimer_version` is already
  in the verdict payload — the CLI and MCP summary should both print it, as the
  frontend does via [DisclaimerFooter.tsx](../frontend/src/components/DisclaimerFooter.tsx).
