from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from netwatch.cli import app
from netwatch.probes.models import PhaseResult, TargetProbeResult

runner = CliRunner()


def test_cli_help() -> None:
    """Verifies CLI help output lists available commands and options."""
    res = runner.invoke(app, ["--help"])
    assert res.exit_code == 0
    assert "probe" in res.stdout


def test_cli_probe_success() -> None:
    """Verifies CLI probe formats report table and exits 0 on healthy probe."""
    mock_result = TargetProbeResult(
        target="example.com",
        url="https://example.com",
        host="example.com",
        port=443,
        dns=PhaseResult(
            phase="dns",
            success=True,
            duration_seconds=0.01,
            details={"resolved_ips": ["93.184.216.34"]},
        ),
        tcp=PhaseResult(phase="tcp", success=True, duration_seconds=0.02, details={"port": 443}),
        tls=PhaseResult(
            phase="tls",
            success=True,
            duration_seconds=0.03,
            details={"tls_version": "TLSv1.3", "days_to_expiry": 120.0},
        ),
        http=PhaseResult(
            phase="http", success=True, duration_seconds=0.05, details={"status_code": 200}
        ),
        tls_cert_expiry_days=120.0,
        success=True,
    )

    with patch("netwatch.cli.run_all_probes", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = mock_result
        res = runner.invoke(app, ["probe", "example.com"])

    assert res.exit_code == 0
    assert "NetWatch Probe Report" in res.stdout
    assert "DNS" in res.stdout
    assert "TCP" in res.stdout
    assert "TLS" in res.stdout
    assert "HTTP" in res.stdout
    assert "120.0 days remaining" in res.stdout
    assert "ALL PROBE PHASES PASSED" in res.stdout


def test_cli_probe_failure() -> None:
    """Verifies CLI probe prints error states and exits with code 1 on failure."""
    mock_result = TargetProbeResult(
        target="failing.test",
        url="https://failing.test",
        host="failing.test",
        port=443,
        dns=PhaseResult(phase="dns", success=False, error="NXDOMAIN: host not found"),
        tcp=PhaseResult(phase="tcp", success=False, error="Skipped: DNS resolution failed"),
        tls=PhaseResult(phase="tls", success=False, error="Skipped: TCP connection failed"),
        http=PhaseResult(
            phase="http", success=False, error="Skipped: Prior transport phase failed"
        ),
        tls_cert_expiry_days=None,
        success=False,
    )

    with patch("netwatch.cli.run_all_probes", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = mock_result
        res = runner.invoke(app, ["probe", "failing.test"])

    assert res.exit_code == 1
    assert "FAIL" in res.stdout
    assert "PROBE FAILED" in res.stdout


def test_cli_status() -> None:
    """Verifies CLI status command reports phase notice."""
    res = runner.invoke(app, ["status"])
    assert res.exit_code == 0
    assert "Replica status" in res.stdout
