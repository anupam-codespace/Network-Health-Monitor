import asyncio
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from netwatch.probes.runner import run_all_probes

app = typer.Typer(
    name="netwatch",
    help="NetWatch - Network Health Monitor CLI",
    no_args_is_help=True,
)
targets_app = typer.Typer(help="Manage monitored network targets", no_args_is_help=True)
app.add_typer(targets_app, name="targets")
console = Console()


@app.command("status")
def status_command() -> None:
    """Displays active replica role, uptime, and heartbeat status."""
    console.print(
        "[yellow]Replica status endpoint will connect to the API/database in Phase 2 & 4.[/yellow]"
    )


@app.command("probe")
def probe_command(
    host: Annotated[str, typer.Argument(help="Host or URL to probe (e.g. example.com)")],
    timeout: Annotated[
        float, typer.Option("--timeout", "-t", help="Timeout per probe phase in seconds")
    ] = 5.0,
) -> None:
    """Runs a multi-phase health probe against a host and prints the results in a table."""
    with console.status(f"[bold cyan]Probing {host}...[/bold cyan]"):
        result = asyncio.run(run_all_probes(host, phase_timeout=timeout))

    # Construct formatted results table
    table = Table(
        title=f"NetWatch Probe Report: {result.target}",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Phase", style="bold", width=12)
    table.add_column("Status", width=10)
    table.add_column("Latency (ms)", justify="right", width=15)
    table.add_column("Details", style="dim")

    phases = [
        ("DNS", result.dns),
        ("TCP", result.tcp),
        ("TLS", result.tls),
        ("HTTP", result.http),
    ]

    for phase_name, phase_res in phases:
        if phase_res.success:
            status_str = "[bold green]PASS[/bold green]"
        elif phase_res.error and "Skipped" in phase_res.error:
            status_str = "[yellow]SKIP[/yellow]"
        else:
            status_str = "[bold red]FAIL[/bold red]"

        ms = phase_res.duration_ms
        latency_str = f"{ms:.2f} ms" if ms is not None else "-"

        if phase_res.error:
            details_str = f"[red]{phase_res.error}[/red]"
        else:
            details_parts = []
            for k, v in phase_res.details.items():
                if v is not None and k != "is_ip_literal":
                    details_parts.append(f"{k}={v}")
            details_str = ", ".join(details_parts) if details_parts else "OK"

        table.add_row(phase_name, status_str, latency_str, details_str)

    console.print(table)

    # Display TLS certificate expiry metrics
    if result.tls_cert_expiry_days is not None:
        days = result.tls_cert_expiry_days
        console.print(f"TLS Certificate Expiry: [bold cyan]{days:.1f} days remaining[/bold cyan]")

    # Display overall health outcome
    if result.success:
        console.print(Panel("[bold green]ALL PROBE PHASES PASSED[/bold green]", expand=False))
    else:
        console.print(Panel("[bold red]PROBE FAILED[/bold red]", expand=False))
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
