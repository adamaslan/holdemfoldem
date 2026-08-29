"""MCP server exposing Hold Em or Fold Em verdicts.

Wraps the backend's /api/analyze endpoint over HTTP so the verdict logic
(core.compute_verdict) keeps living in exactly one process — see
docs/cli-and-mcp-guide.md §4.1 for why this wraps HTTP rather than importing
core.py directly (that would duplicate the Firestore client and the
os.chdir() side effect main.py/core.py trigger at import time).

Uses the low-level mcp.server.Server API to match the house pattern in
gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp/server.py, rather than
FastMCP.
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
                                "cost_basis": {
                                    "type": "number",
                                    "description": "Per-share, pre-fee",
                                },
                                "acquired_at": {
                                    "type": "string",
                                    "description": "ISO 8601 date",
                                },
                                "side": {
                                    "type": "string",
                                    "enum": ["long", "short"],
                                    "default": "long",
                                },
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
                    "options_strategy": {
                        "type": "string",
                        "enum": _OPTIONS_STRATEGIES,
                    },
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
            description=(
                "Check whether the Hold Em or Fold Em backend and its Firestore "
                "cache are reachable."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


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


async def _get_health() -> dict[str, Any]:
    """GET the backend's /health, tolerating unreachability."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{BACKEND_URL}/health")
            response.raise_for_status()
            return response.json()
    except httpx.RequestError as e:
        return {"status": "unreachable", "backend_url": BACKEND_URL, "error": str(e)}
    except httpx.HTTPStatusError as e:
        return {"status": "error", "backend_url": BACKEND_URL, "http_status": e.response.status_code}


def _extract_detail(response: httpx.Response) -> str:
    """Pull FastAPI's {"detail": "..."} out of an error response, else raw text."""
    try:
        body = response.json()
        return str(body.get("detail", response.text))
    except ValueError:
        return response.text


def _summarize(v: dict[str, Any]) -> str:
    """Render a verdict as compact text for an LLM consumer.

    Never dumps the raw verdict — it has ~50 fields including a full
    payoff_curve, which would burn context on numbers the model won't read.
    Always propagates degraded/warnings/suppressions: a model reading a
    clean-looking verdict has no other way to learn the data was thin.
    """
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
    if v.get("position_pnl_detail"):
        pnl = v["position_pnl_detail"]
        lines.append(
            f"Position P&L: {pnl['unrealized_pct']:+.1f}% "
            f"(${pnl['unrealized_dollar']:.2f}), cost basis ${pnl['cost_basis_effective']:.2f} "
            f"[{pnl['cost_basis_method']}]"
        )
    if v.get("degraded"):
        lines.append("⚠ Pipeline ran in DEGRADED mode — treat with lower confidence.")
    for w in v.get("warnings", []):
        lines.append(f"⚠ {w}")

    lines.append(v["summary"])
    lines.append(f"(disclaimer v{v['disclaimer_version']} — not financial advice)")
    return "\n".join(lines)


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
