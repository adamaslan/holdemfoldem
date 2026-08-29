"""Hold Em or Fold Em — command line interface.

Hybrid transport: tries the in-process verdict engine (core.compute_verdict)
first, and falls back to a running backend's HTTP API when core.py can't be
imported (missing mamba env / sibling mcp-finance1 repo) or when --remote is
passed explicitly. See docs/cli-and-mcp-guide.md §3 for the design rationale.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Annotated, Any

import typer

from cli.render import render_table, render_verdict

try:
    from core import AnalysisUnavailableError
except ImportError:  # HTTP-only install — core.py's mamba env isn't present
    class AnalysisUnavailableError(Exception):
        """Placeholder used only when the in-process engine can't import."""

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


def _parse_lot(raw: str) -> dict[str, Any]:
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

    lot: dict[str, Any] = {"qty": qty, "cost_basis": cost_basis}
    if len(parts) == 3:
        lot["acquired_at"] = parts[2]
    return lot


def _parse_leg(raw: str) -> dict[str, Any]:
    """Parse a --leg value of the form role:strike[:expiry].

    Args:
        raw: e.g. "sell_put:400" or "buy_call:460:2026-01-16"

    Returns:
        A dict matching OptionsLegRequest.

    Raises:
        ValueError: If the format is malformed or strike doesn't parse.
    """
    parts = raw.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"--leg must be role:strike[:expiry], got {raw!r}")

    role = parts[0]
    try:
        strike = float(parts[1])
    except ValueError as e:
        raise ValueError(f"--leg has non-numeric strike: {raw!r}") from e

    leg: dict[str, Any] = {"role": role, "strike": strike}
    if len(parts) == 3:
        leg["expiry"] = parts[2]
    return leg


def _build_request(
    *,
    symbol: str,
    period: str,
    asset_type: str,
    risk_profile: str,
    strategy: str | None,
    dte: int | None,
    net_premium: float | None,
    legs: list[str],
    lots: list[str],
    cost_basis: str,
) -> dict[str, Any]:
    """Assemble a raw request dict matching AnalyzeRequest from CLI flags.

    Raises:
        ValueError: If any --leg or --lot value is malformed.
    """
    request: dict[str, Any] = {
        "symbol": symbol,
        "period": period,
        "asset_type": asset_type,
        "risk_profile": risk_profile,
        "cost_basis_method": cost_basis,
    }
    if strategy is not None:
        request["options_strategy"] = strategy
    if dte is not None:
        request["dte"] = dte
    if net_premium is not None:
        request["net_premium"] = net_premium
    if legs:
        request["options_legs"] = [_parse_leg(raw) for raw in legs]
    if lots:
        request["position_lots"] = [_parse_lot(raw) for raw in lots]
    return request


async def _dispatch(request: dict[str, Any], remote: str | None) -> dict[str, Any]:
    """Route a request to the local engine or a remote backend.

    Args:
        request: Raw request dict matching AnalyzeRequest.
        remote: Backend base URL. If None, try the in-process engine first,
            falling back to the default backend URL if core.py can't import.

    Returns:
        The verdict as a plain dict.

    Raises:
        ValueError: On invalid input (bad symbol/period/etc).
        ConnectionError: If a remote backend is unreachable.
    """
    if remote is not None:
        from cli.client import post_analyze
        return await post_analyze(remote, request)

    try:
        from core import AnalyzeRequest, compute_verdict
    except ImportError:
        # No local mamba env / sibling mcp-finance1 repo — fall back to HTTP.
        from cli.client import default_backend_url, post_analyze
        return await post_analyze(default_backend_url(), request)

    result = await compute_verdict(AnalyzeRequest(**request))
    return result.model_dump()


@app.command()
def verdict(
    symbol: Annotated[str, typer.Argument(help="Ticker, e.g. AAPL or BTC-USD")],
    period: Annotated[str, typer.Option("--period", "-p")] = "3mo",
    asset_type: Annotated[str, typer.Option("--asset-type")] = "stock",
    risk_profile: Annotated[str, typer.Option("--risk")] = "moderate",
    strategy: Annotated[
        str | None, typer.Option("--strategy", help="e.g. iron_condor, covered_call")
    ] = None,
    dte: Annotated[int | None, typer.Option("--dte", help="Days to expiration")] = None,
    net_premium: Annotated[
        float | None,
        typer.Option("--net-premium", help="Per share; + = credit, - = debit"),
    ] = None,
    leg: Annotated[
        list[str] | None,
        typer.Option("--leg", help="Options leg: role:strike[:expiry]. Repeatable."),
    ] = None,
    lot: Annotated[
        list[str] | None,
        typer.Option("--lot", help="Tax lot: qty@cost[@YYYY-MM-DD]. Repeatable."),
    ] = None,
    cost_basis: Annotated[str, typer.Option("--cost-basis")] = "average",
    as_json: Annotated[bool, typer.Option("--json", help="Print raw JSON instead of a panel")] = False,
    remote: Annotated[
        str | None, typer.Option("--remote", help="Backend URL, e.g. http://localhost:8001")
    ] = None,
) -> None:
    """Get a HOLD EM / FOLD EM verdict for SYMBOL.

    Exit code encodes the verdict: 0 HOLD EM, 1 FOLD EM, 2 NEUTRAL, 3 error.
    """
    try:
        request = _build_request(
            symbol=symbol, period=period, asset_type=asset_type,
            risk_profile=risk_profile, strategy=strategy, dte=dte,
            net_premium=net_premium, legs=leg or [], lots=lot or [],
            cost_basis=cost_basis,
        )
        result = asyncio.run(_dispatch(request, remote))
    except ValueError as e:
        typer.secho(f"Invalid input: {e}", fg="red", err=True)
        raise typer.Exit(EXIT_ERROR) from e
    except ConnectionError as e:
        typer.secho(f"Backend unreachable: {e}", fg="red", err=True)
        raise typer.Exit(EXIT_ERROR) from e
    except AnalysisUnavailableError as e:
        typer.secho(f"Analysis unavailable: {e}", fg="red", err=True)
        raise typer.Exit(EXIT_ERROR) from e

    if as_json:
        json.dump(result, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        render_verdict(result)

    raise typer.Exit(_VERDICT_EXIT_CODES.get(result["verdict"], EXIT_ERROR))


@app.command()
def watch(
    symbols: Annotated[list[str], typer.Argument(help="Tickers to check, e.g. AAPL MSFT NVDA")],
    period: Annotated[str, typer.Option("--period", "-p")] = "3mo",
    remote: Annotated[str | None, typer.Option("--remote")] = None,
) -> None:
    """Get verdicts for multiple symbols as a single table."""
    async def _run() -> list[dict[str, Any]]:
        results = []
        for sym in symbols:
            request = _build_request(
                symbol=sym, period=period, asset_type="stock", risk_profile="moderate",
                strategy=None, dte=None, net_premium=None, legs=[], lots=[],
                cost_basis="average",
            )
            try:
                results.append(await _dispatch(request, remote))
            except (ValueError, ConnectionError, AnalysisUnavailableError) as e:
                results.append({"symbol": sym.upper(), "error": str(e)})
        return results

    results = asyncio.run(_run())
    render_table(results)

    if any("error" in r for r in results):
        raise typer.Exit(EXIT_ERROR)


@app.command()
def health(
    remote: Annotated[
        str | None, typer.Option("--remote", help="Backend URL to check")
    ] = None,
) -> None:
    """Check backend + Firestore cache reachability."""
    async def _run() -> dict[str, Any]:
        if remote is not None:
            from cli.client import get_health
            return await get_health(remote)
        try:
            from core import check_backend_health
        except ImportError:
            from cli.client import default_backend_url, get_health
            return await get_health(default_backend_url())
        return await check_backend_health()

    try:
        result = asyncio.run(_run())
    except ConnectionError as e:
        typer.secho(f"Backend unreachable: {e}", fg="red", err=True)
        raise typer.Exit(EXIT_ERROR) from e
    except AnalysisUnavailableError as e:
        typer.secho(f"Analysis unavailable: {e}", fg="red", err=True)
        raise typer.Exit(EXIT_ERROR) from e

    typer.echo(json.dumps(result, indent=2))
    if not result.get("status") == "ok":
        raise typer.Exit(EXIT_ERROR)


if __name__ == "__main__":
    app()
