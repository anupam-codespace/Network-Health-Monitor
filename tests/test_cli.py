from unittest.mock import AsyncMock, patch
from typer.testing import CliRunner

from netwatch.cli import app, format_plain_table
from netwatch.probes.models import (
    DnsResult,
    HttpResult,
    ProbeCompositeResult,
    TcpResult,
    TlsResult,
)

runner = CliRunner()


def test_cli_help() -> None:
    """Verifies CLI help output lists available commands and options."""
    res = runner.invoke(app, ["--help"])
    assert res.exit_code == 0
    assert "probe" in res.stdout


def test_format_plain_table() -> None:
    """Verifies that format_plain_table renders an ASCII table without terminal control characters."""
    sample_rows = [
        ("DNS", "PASS", "12.30", "ip=1.1.1.1"),
        ("TCP", "PASS", "24.50", "port=443"),
    ]
    table = format_plain_table(sample_rows)
    assert "| Phase    | Status   | Latency (ms)   | Details" in table
    assert "DNS" in table
    assert "12.30" in table


def test_cli_probe_success() -> None:
    """Verifies CLI probe formats plain ASCII report table and exits 0 on healthy probe."""
    mock_result = ProbeCompositeResult(
        host="example.com",
        port=443,
        ok=True,
        dns=DnsResult(ok=True, dns_ms=10.0, resolved_ip="93.184.216.34"),
        tcp=TcpResult(ok=True, tcp_ms=20.0),
        tls=TlsResult(ok=True, tls_ms=30.0, tls_days_left=120.0),
        http=HttpResult(ok=True, http_ms=40.0, status_code=200),
        total_ms=100.0,
        dns_ms=10.0,
        tcp_ms=20.0,
        tls_ms=30.0,
        http_ms=40.0,
        status_code=200,
        tls_days_left=120.0,
    )

    with patch("netwatch.cli.run_probes", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = mock_result
        res = runner.invoke(app, ["probe", "example.com"])

    assert res.exit_code == 0
    assert "NetWatch Probe: example.com:443" in res.stdout
    assert "DNS" in res.stdout
    assert "TCP" in res.stdout
    assert "TLS" in res.stdout
    assert "HTTP" in res.stdout
    assert "Total: 100.00 ms | Status: PASSED" in res.stdout


def test_cli_probe_failure() -> None:
    """Verifies CLI probe prints error states and exits with code 1 on failure."""
    mock_result = ProbeCompositeResult(
        host="failing.test",
        port=443,
        ok=False,
        dns=DnsResult(ok=False, dns_ms=15.0, error="NXDOMAIN: host not found"),
        tcp=TcpResult(ok=False, error="Skipped: DNS resolution failed"),
        tls=TlsResult(ok=False, error="Skipped: DNS resolution failed"),
        http=HttpResult(ok=False, error="Skipped: DNS resolution failed"),
        total_ms=15.0,
        dns_ms=15.0,
        first_failing_phase="dns",
        error="NXDOMAIN: host not found",
    )

    with patch("netwatch.cli.run_probes", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = mock_result
        res = runner.invoke(app, ["probe", "failing.test"])

    assert res.exit_code == 1
    assert "FAIL" in res.stdout
    assert "Total: 15.00 ms | Status: FAILED" in res.stdout
