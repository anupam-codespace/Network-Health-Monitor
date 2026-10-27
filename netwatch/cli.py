import asyncio
import sys
from typing import Annotated
import typer

from netwatch.probes.runner import run_probes

app = typer.Typer(
    name="netwatch",
    help="NetWatch Network Health Monitor CLI",
    no_args_is_help=True,
)


def format_plain_table(rows: list[tuple[str, str, str, str]]) -> str:
    """Formats a border-aligned plain text table without third-party terminal dependencies."""
    col_widths = [8, 8, 14, 40]
    sep = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
    headers = ["Phase", "Status", "Latency (ms)", "Details"]
    header = (
        "|"
        + "|".join(f" {t.ljust(w)} " for t, w in zip(headers, col_widths, strict=False))
        + "|"
    )

    lines = [sep, header, sep]
    for row in rows:
        formatted_cells = [
            f" {cell[:w].ljust(w)} " for cell, w in zip(row, col_widths, strict=False)
        ]
        lines.append("|" + "|".join(formatted_cells) + "|")
    lines.append(sep)
    return "\n".join(lines)


@app.command("status")
def status_command() -> None:
    """Displays active replica role and health status."""
    print("NetWatch CLI status: OK")


@app.command("probe")
def probe_command(
    host: Annotated[str, typer.Argument(help="Target host or IP to probe (e.g. example.com)")],
    port: Annotated[int, typer.Option("--port", "-p", help="Target TCP port")] = 443,
    timeout: Annotated[
        float, typer.Option("--timeout", "-t", help="Timeout per phase in seconds")
    ] = 5.0,
) -> None:
    """Runs a 4-phase network health probe and outputs a plain-text results table."""
    res = asyncio.run(run_probes(host=host, port=port, timeout_s=timeout))

    rows = [
        (
            "DNS",
            "PASS" if res.dns.ok else "FAIL",
            f"{res.dns_ms:.2f}" if res.dns_ms is not None else "-",
            f"ip={res.dns.resolved_ip}" if res.dns.ok else (res.dns.error or "Error"),
        ),
        (
            "TCP",
            "PASS" if res.tcp.ok else "FAIL",
            f"{res.tcp_ms:.2f}" if res.tcp_ms is not None else "-",
            f"port={port}" if res.tcp.ok else (res.tcp.error or "Error"),
        ),
        (
            "TLS",
            "PASS" if res.tls.ok else "FAIL",
            f"{res.tls_ms:.2f}" if res.tls_ms is not None else "-",
            (
                f"days_left={res.tls_days_left}"
                if res.tls.ok and res.tls_days_left is not None
                else (res.tls.error or "-")
            ),
        ),
        (
            "HTTP",
            "PASS" if res.http.ok else "FAIL",
            f"{res.http_ms:.2f}" if res.http_ms is not None else "-",
            f"status={res.status_code}" if res.http.ok else (res.http.error or "Error"),
        ),
    ]

    print(f"\nNetWatch Probe: {host}:{port}")
    print(format_plain_table(rows))

    total = f"{res.total_ms:.2f} ms" if res.total_ms is not None else "-"
    status_label = "PASSED" if res.ok else "FAILED"
    print(f"Total: {total} | Status: {status_label}\n")

    if not res.ok:
        sys.exit(1)


if __name__ == "__main__":
    app()
