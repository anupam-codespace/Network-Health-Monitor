import asyncio
import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import dns.exception
import dns.resolver
import pytest

from netwatch.probes.dns import probe_dns
from netwatch.probes.http import probe_http
from netwatch.probes.models import DnsResult, HttpResult, TcpResult, TlsResult
from netwatch.probes.runner import run_probes
from netwatch.probes.tcp import probe_tcp
from netwatch.probes.tls import parse_cert_days_left, probe_tls

# --- DNS Probe Tests ---


@pytest.mark.asyncio
async def test_probe_dns_ip_literal() -> None:
    """Verifies that IP literals bypass DNS network queries with 0 latency."""
    res = await probe_dns("127.0.0.1")
    assert res.ok is True
    assert res.resolved_ip == "127.0.0.1"
    assert res.dns_ms == 0.0


@pytest.mark.asyncio
async def test_probe_dns_success() -> None:
    """Verifies DNS query returns resolved IP and measures latency in milliseconds."""
    mock_answer = MagicMock()
    mock_answer.__str__.return_value = "93.184.216.34"

    with patch("dns.asyncresolver.Resolver.resolve", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.return_value = [mock_answer]
        res = await probe_dns("example.com")

    assert res.ok is True
    assert res.resolved_ip == "93.184.216.34"
    assert res.dns_ms is not None
    assert res.dns_ms >= 0.0


@pytest.mark.asyncio
async def test_probe_dns_nxdomain() -> None:
    """Verifies NXDOMAIN response is captured as structured failure data."""
    with patch("dns.asyncresolver.Resolver.resolve", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.side_effect = dns.resolver.NXDOMAIN()
        res = await probe_dns("nonexistent.invalid")

    assert res.ok is False
    assert "NXDOMAIN" in str(res.error)


@pytest.mark.asyncio
async def test_probe_dns_timeout() -> None:
    """Verifies DNS timeout is captured as structured failure data."""
    with patch("dns.asyncresolver.Resolver.resolve", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.side_effect = dns.exception.Timeout()
        res = await probe_dns("slow.dns.server", timeout_s=0.1)

    assert res.ok is False
    assert "timed out" in str(res.error)


# --- TCP Probe Tests with Local Server ---


@pytest.mark.asyncio
async def test_probe_tcp_local_server() -> None:
    """Verifies TCP probe succeeds against a real local socket server."""

    async def echo_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(echo_handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    async with server:
        res = await probe_tcp("127.0.0.1", port=port, timeout_s=2.0)

    assert res.ok is True
    assert res.tcp_ms is not None
    assert res.tcp_ms >= 0.0


@pytest.mark.asyncio
async def test_probe_tcp_connection_refused() -> None:
    """Verifies TCP probe reports failure when connecting to closed port."""
    res = await probe_tcp("127.0.0.1", port=1, timeout_s=1.0)
    assert res.ok is False
    assert "TCP connection failed" in str(res.error)


# --- TLS Probe Tests with Local TLS Server ---


@pytest.mark.asyncio
async def test_probe_tls_local_server(
    server_ssl_context: ssl.SSLContext, client_ssl_context: ssl.SSLContext
) -> None:
    """Verifies TLS handshake latency and certificate days-to-expiry against a local TLS server."""

    async def tls_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(tls_handler, "127.0.0.1", 0, ssl=server_ssl_context)
    port = server.sockets[0].getsockname()[1]

    async with server:
        res = await probe_tls(
            "localhost",
            port=port,
            timeout_s=2.0,
            ssl_context=client_ssl_context,
        )

    assert res.ok is True
    assert res.tls_ms is not None
    assert res.tls_ms >= 0.0
    assert res.tls_days_left is not None
    assert 25 <= res.tls_days_left <= 31


def test_parse_cert_days_left() -> None:
    """Verifies cert days left calculation with valid and invalid metadata."""
    cert = {"notAfter": "Jan 01 00:00:00 2030 GMT"}
    days = parse_cert_days_left(cert)
    assert days is not None
    assert days > 0

    assert parse_cert_days_left({}) is None
    assert parse_cert_days_left({"notAfter": "malformed date"}) is None


# --- HTTP Probe Tests with Local HTTP Server ---


@pytest.mark.asyncio
async def test_probe_http_local_server() -> None:
    """Verifies HTTP probe measures Time-To-First-Byte against a local HTTP server."""

    async def http_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        # Drain remaining headers
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(http_handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    async with server:
        res = await probe_http("127.0.0.1", port=port, is_tls=False, timeout_s=2.0)

    assert res.ok is True
    assert res.status_code == 200
    assert res.http_ms is not None
    assert res.http_ms >= 0.0


# --- Pipeline Runner Tests ---


@pytest.mark.asyncio
async def test_run_probes_full_success() -> None:
    """Verifies pipeline coordinator composes all 4 phases and calculates total latency."""
    with (
        patch("netwatch.probes.runner.probe_dns", new_callable=AsyncMock) as mock_dns,
        patch("netwatch.probes.runner.connect_tcp", new_callable=AsyncMock) as mock_tcp,
        patch("netwatch.probes.runner.upgrade_to_tls", new_callable=AsyncMock) as mock_tls,
        patch("netwatch.probes.runner.send_http_request", new_callable=AsyncMock) as mock_http,
    ):
        mock_writer = MagicMock()
        mock_writer.wait_closed = AsyncMock(return_value=None)

        mock_dns.return_value = DnsResult(ok=True, dns_ms=10.0, resolved_ip="1.1.1.1")
        mock_tcp.return_value = (TcpResult(ok=True, tcp_ms=20.0), (MagicMock(), mock_writer))
        mock_tls.return_value = TlsResult(ok=True, tls_ms=30.0, tls_days_left=90.0)
        mock_http.return_value = HttpResult(ok=True, http_ms=40.0, status_code=200)

        result = await run_probes("example.com", port=443)

    assert result.ok is True
    assert result.total_ms == 100.0
    assert result.first_failing_phase is None
    assert result.tls_days_left == 90.0
    assert result.status_code == 200


@pytest.mark.asyncio
async def test_run_probes_dns_failure_identifies_first_failing() -> None:
    """Verifies pipeline halts immediately and identifies 'dns' as first failing phase."""
    with patch("netwatch.probes.runner.probe_dns", new_callable=AsyncMock) as mock_dns:
        mock_dns.return_value = DnsResult(ok=False, dns_ms=15.0, error="NXDOMAIN")
        result = await run_probes("invalid.test")

    assert result.ok is False
    assert result.first_failing_phase == "dns"
    assert result.tcp.ok is False
    assert result.tls.ok is False
    assert result.http.ok is False
