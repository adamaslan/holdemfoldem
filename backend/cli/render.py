"""Terminal rendering for verdicts.

Leads with the verdict and never hides degraded/warnings/suppressions — those
fields exist because the pipeline can silently return a weaker answer, and a
CLI that hides them is worse than no CLI.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

_VERDICT_STYLES = {
    "HOLD EM": "bold green",
    "FOLD EM": "bold red",
    "NEUTRAL": "bold yellow",
}

console = Console()


def render_verdict(v: dict[str, Any]) -> None:
    """Print a full verdict as a terminal panel plus supporting detail."""
    style = _VERDICT_STYLES.get(v["verdict"], "bold white")
    header = (
        f"[{style}]{v['verdict']}[/]  {v['confidence']}% confidence\n"
        f"${v['price']:.2f}  ·  {v['bias']}  ·  risk: {v['risk_level']}"
        f"{'  ·  [dim]cached[/]' if v.get('cached') else ''}"
    )
    console.print(Panel(header, title=f"{v['symbol']} ({v['asset_type']})"))

    console.print(
        f"Signals: {v['bullish_count']} bullish / {v['bearish_count']} bearish "
        f"(avg score {v['avg_score']:.0f}/100)"
    )

    if v.get("entry") is not None:
        console.print(
            f"Trade plan: entry ${v['entry']} · stop ${v['stop']} · "
            f"target ${v['target']} · R/R {v['risk_reward']}"
        )

    if v.get("max_profit") is not None:
        console.print(
            f"Options: max profit ${v['max_profit']} · max loss ${v['max_loss']} · "
            f"POP {v.get('pop')}% · breakevens {v.get('breakeven_prices')}"
        )

    if v.get("position_pnl_detail"):
        pnl = v["position_pnl_detail"]
        console.print(
            f"Position: {'+' if pnl['unrealized_pct'] >= 0 else ''}"
            f"{pnl['unrealized_pct']:.1f}% (${pnl['unrealized_dollar']:.2f}), "
            f"cost basis ${pnl['cost_basis_effective']:.2f} [{pnl['cost_basis_method']}]"
        )

    if v.get("degraded"):
        console.print("[yellow]⚠ degraded pipeline — data quality reduced[/]")
    for w in v.get("warnings", []):
        console.print(f"[yellow]⚠ {w}[/]")
    for s in v.get("suppressions", []):
        console.print(f"[dim]suppressed: {s['label']}[/]")

    console.print()
    console.print(v["summary"])
    console.print(f"[dim](disclaimer v{v['disclaimer_version']} — not financial advice)[/]")


def render_table(verdicts: list[dict[str, Any]]) -> None:
    """Print multiple verdicts as a compact table, for `holdfold watch`."""
    table = Table()
    table.add_column("Symbol")
    table.add_column("Verdict")
    table.add_column("Conf %", justify="right")
    table.add_column("Price", justify="right")
    table.add_column("Bias")
    table.add_column("Risk")

    for v in verdicts:
        if "error" in v:
            table.add_row(v["symbol"], f"[red]ERROR: {v['error']}[/]", "", "", "", "")
            continue
        style = _VERDICT_STYLES.get(v["verdict"], "")
        table.add_row(
            v["symbol"],
            f"[{style}]{v['verdict']}[/]",
            f"{v['confidence']}",
            f"${v['price']:.2f}",
            v["bias"],
            v["risk_level"],
        )

    console.print(table)
