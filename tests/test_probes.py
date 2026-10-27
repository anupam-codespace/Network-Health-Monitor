import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import dns.exception
import dns.resolver
import httpx
import pytest

from netwatch.probes.dns import probe_dns
from netwatch.probes.http import probe_http
from netwatch.probes.models import PhaseResult, TargetProbeResult
from netwatch.probes.runner import parse_target, run_all_probes
from netwatch.probes.tcp import probe_tcp
from netwatch.probes.tls import parse_cert_expiry_days, probe_tls

# --- Target Parsing Tests ---


def test_parse_target_variations() -> None:
    """Verifies URI parsing correctly defaults schemes and extracts ports for network health."""
    # Bare host defaults to HTTPS on port 443
    url, host, port, is_tls = parse_target("example.com")
    assert url == "https://example.com"
    assert host == "example.com"
    assert port == 443
    assert is_tls is True

    # Explicit HTTP on port 80
    url, host, port, is_tls = parse_target("http://insecure.internal")
    assert url == "http://insecure.internal"
    assert host == "insecure.internal"
    assert port == 80
    assert is_tls is False

    # Explicit custom port
    url, host, port, is_tls = parse_target("https://api.internal:8443/healthz")
    assert host == "api.internal"
    assert port == 8443
    assert is_tls is True


# --- DNS Probe Tests ---


@pytest.mark.asyncio
async def test_probe_dns_ip_literal() -> None:
    """Verifies IP literals bypass DNS resolution with zero latency."""
    res = await probe_dns("127.0.0.1")
    assert res.success is True
    assert res.phase == "dns"
    assert res.details.get("is_ip_literal") is True
    assert res.details.get("resolved_ips") == ["127.0.0.1"]


@pytest.mark.asyncio
async def test_probe_dns_success() -> None:
    """Verifies successful DNS resolution returns resolved IPs and captures latency."""
    mock_answer = MagicMock()
    mock_answer.__str__.return_value = "93.184.216.34"

    with patch("dns.asyncresolver.Resolver.resolve", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.return_value = [mock_answer]
        res = await probe_dns("example.com")

    assert res.success is True
    assert res.phase == "dns"
    assert res.error is None
    assert res.details.get("resolved_ips") == ["93.184.216.34"]
    assert res.duration_seconds is not None
    assert res.duration_seconds >= 0.0


@pytest.mark.asyncio
async def test_probe_dns_nxdomain() -> None:
    """Verifies NXDOMAIN is cleanly converted into structured failure data."""
    with patch("dns.asyncresolver.Resolver.resolve", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.side_effect = dns.resolver.NXDOMAIN()
        res = await probe_dns("nonexistent.invalid")

    assert res.success is False
    assert "NXDOMAIN" in str(res.error)


@pytest.mark.asyncio
async def test_probe_dns_timeout() -> None:
    """Verifies DNS timeouts return structured failure data."""
    with patch("dns.asyncresolver.Resolver.resolve", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.side_effect = dns.exception.Timeout()
        res = await probe_dns("slow.dns.server", timeout=0.1)

    assert res.success is False
    assert "timed out" in str(res.error)


# --- TCP Probe Tests ---


@pytest.mark.asyncio
async def test_probe_tcp_success_local_server() -> None:
    """Verifies TCP probe succeeds against a real local socket server."""

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    async with server:
        res = await probe_tcp("127.0.0.1", port=port, timeout=2.0)

    assert res.success is True
    assert res.phase == "tcp"
    assert res.error is None
    assert res.duration_seconds is not None
    assert res.details["port"] == port


@pytest.mark.asyncio
async def test_probe_tcp_connection_refused() -> None:
    """Verifies TCP probe reports failure when connection is refused."""
    # Port 1 is reserved and typically closed on local loopback
    res = await probe_tcp("127.0.0.1", port=1, timeout=1.0)
    assert res.success is False
    assert "TCP connection failed" in str(res.error)


@pytest.mark.asyncio
async def test_probe_tcp_timeout() -> None:
    """Verifies TCP probe handles timeout cleanly."""
    with patch("asyncio.open_connection", side_effect=asyncio.TimeoutError()):
        res = await probe_tcp("192.0.2.1", port=443, timeout=0.01)

    assert res.success is False
    assert "timed out" in str(res.error)


# --- TLS Probe Tests ---


def test_parse_cert_expiry_days() -> None:
    """Verifies certificate expiry days calculation handles valid and invalid metadata."""
    # Future certificate
    cert_future = {"notAfter": "Jan 01 00:00:00 2030 GMT"}
    days = parse_cert_expiry_days(cert_future)
    assert days is not None
    assert days > 0

    # Missing notAfter field
    assert parse_cert_expiry_days({}) is None

    # Malformed date string
    assert parse_cert_expiry_days({"notAfter": "invalid date format"}) is None


@pytest.mark.asyncio
async def test_probe_tls_success() -> None:
    """Verifies TLS handshake latency measurement and certificate property extraction."""
    mock_writer = MagicMock()
    mock_writer.start_tls = AsyncMock(return_value=None)
    mock_writer.wait_closed = AsyncMock(return_value=None)

    mock_ssl_obj = MagicMock()
    mock_ssl_obj.getpeercert.return_value = {
        "notAfter": "Jan 01 00:00:00 2030 GMT",
        "subject": ((("commonName", "example.com"),),),
    }
    mock_ssl_obj.cipher.return_value = ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256)
    mock_ssl_obj.version.return_value = "TLSv1.3"
    mock_writer.get_extra_info.return_value = mock_ssl_obj

    with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
        mock_open.return_value = (MagicMock(), mock_writer)
        res = await probe_tls("example.com", port=443)

    assert res.success is True
    assert res.phase == "tls"
    assert res.details.get("tls_version") == "TLSv1.3"
    assert res.details.get("cipher") == "TLS_AES_256_GCM_SHA384"
    assert res.details.get("days_to_expiry") is not None
    assert res.details["days_to_expiry"] > 0


@pytest.mark.asyncio
async def test_probe_tls_tcp_failure() -> None:
    """Verifies TLS probe fails gracefully when underlying TCP cannot connect."""
    with patch("asyncio.open_connection", side_effect=OSError("Connection refused")):
        res = await probe_tls("example.com", port=443)

    assert res.success is False
    assert "Underlying TCP connection failed" in str(res.error)


@pytest.mark.asyncio
async def test_probe_tls_handshake_timeout() -> None:
    """Verifies TLS probe records timeout during handshake negotiation."""
    mock_writer = MagicMock()
    mock_writer.start_tls = AsyncMock(side_effect=asyncio.TimeoutError())
    mock_writer.wait_closed = AsyncMock(return_value=None)

    with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
        mock_open.return_value = (MagicMock(), mock_writer)
        res = await probe_tls("example.com", port=443, timeout=0.1)

    assert res.success is False
    assert "timed out" in str(res.error)


# --- HTTP Probe Tests ---


@pytest.mark.asyncio
async def test_probe_http_success() -> None:
    """Verifies HTTP probe measures TTFB using mock transport without real internet."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b'{"status":"ok"}',
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        res = await probe_http("https://example.com/healthz", client=client)

    assert res.success is True
    assert res.phase == "http"
    assert res.details.get("status_code") == 200
    assert res.duration_seconds is not None


@pytest.mark.asyncio
async def test_probe_http_server_error() -> None:
    """Verifies HTTP 5xx responses are marked as failed probes."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"Service Unavailable")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        res = await probe_http("https://example.com/unhealthy", client=client)

    assert res.success is False
    assert "HTTP 503" in str(res.error)
    assert res.details.get("status_code") == 503


@pytest.mark.asyncio
async def test_probe_http_timeout() -> None:
    """Verifies HTTP probe captures network timeouts."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Read timed out")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        res = await probe_http("https://example.com/slow", client=client)

    assert res.success is False
    assert "timed out" in str(res.error)


# --- Runner Integration Tests ---


@pytest.mark.asyncio
async def test_run_all_probes_full_success() -> None:
    """Verifies coordinator passes all phases and combines metrics into TargetProbeResult."""
    with (
        patch("netwatch.probes.runner.probe_dns", new_callable=AsyncMock) as mock_dns,
        patch("netwatch.probes.runner.probe_tcp", new_callable=AsyncMock) as mock_tcp,
        patch("netwatch.probes.runner.probe_tls", new_callable=AsyncMock) as mock_tls,
        patch("netwatch.probes.runner.probe_http", new_callable=AsyncMock) as mock_http,
    ):
        mock_dns.return_value = PhaseResult(
            phase="dns", success=True, duration_seconds=0.01, details={"resolved_ips": ["1.1.1.1"]}
        )
        mock_tcp.return_value = PhaseResult(phase="tcp", success=True, duration_seconds=0.02)
        mock_tls.return_value = PhaseResult(
            phase="tls", success=True, duration_seconds=0.03, details={"days_to_expiry": 45.2}
        )
        mock_http.return_value = PhaseResult(
            phase="http", success=True, duration_seconds=0.05, details={"status_code": 200}
        )

        result: TargetProbeResult = await run_all_probes("example.com")

    assert result.success is True
    assert result.tls_cert_expiry_days == 45.2
    assert result.dns.success is True
    assert result.tcp.success is True
    assert result.tls.success is True
    assert result.http.success is True


@pytest.mark.asyncio
async def test_run_all_probes_dns_failure_skips_downstream() -> None:
    """Verifies downstream phases are gracefully skipped when DNS resolution fails."""
    with patch("netwatch.probes.runner.probe_dns", new_callable=AsyncMock) as mock_dns:
        mock_dns.return_value = PhaseResult(phase="dns", success=False, error="NXDOMAIN")
        result: TargetProbeResult = await run_all_probes("bad-host.test")

    assert result.success is False
    assert result.dns.success is False
    assert "Skipped" in str(result.tcp.error)
    assert "Skipped" in str(result.tls.error)
    assert "Skipped" in str(result.http.error)


@pytest.mark.asyncio
async def test_run_all_probes_http_target_skips_tls() -> None:
    """Verifies non-TLS targets record skipped TLS phase and probe HTTP over plain port 80."""
    with (
        patch("netwatch.probes.runner.probe_dns", new_callable=AsyncMock) as mock_dns,
        patch("netwatch.probes.runner.probe_tcp", new_callable=AsyncMock) as mock_tcp,
        patch("netwatch.probes.runner.probe_http", new_callable=AsyncMock) as mock_http,
    ):
        mock_dns.return_value = PhaseResult(
            phase="dns",
            success=True,
            duration_seconds=0.01,
            details={"resolved_ips": ["192.168.1.1"]},
        )
        mock_tcp.return_value = PhaseResult(phase="tcp", success=True, duration_seconds=0.02)
        mock_http.return_value = PhaseResult(
            phase="http", success=True, duration_seconds=0.04, details={"status_code": 200}
        )

        result = await run_all_probes("http://plain-web.internal")

    assert result.success is True
    assert result.tls.details.get("skipped") is True
    assert result.tls_cert_expiry_days is None


@pytest.mark.asyncio
async def test_probe_dns_aaaa_fallback() -> None:
    """Verifies DNS probe falls back to AAAA record when A record query raises NoAnswer."""
    mock_answer = MagicMock()
    mock_answer.__str__.return_value = "2606:2800:220:1:248:1893:25c8:1946"

    with patch("dns.asyncresolver.Resolver.resolve", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.side_effect = [dns.resolver.NoAnswer(), [mock_answer]]
        res = await probe_dns("ipv6.example.com")

    assert res.success is True
    assert res.details.get("resolved_ips") == ["2606:2800:220:1:248:1893:25c8:1946"]


@pytest.mark.asyncio
async def test_probe_dns_generic_exception() -> None:
    """Verifies unexpected DNS exceptions are caught and reported cleanly."""
    with patch("dns.asyncresolver.Resolver.resolve", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.side_effect = RuntimeError("Socket read interrupted")
        res = await probe_dns("error.test")

    assert res.success is False
    assert "DNS resolution failed" in str(res.error)


@pytest.mark.asyncio
async def test_probe_tcp_unexpected_exception() -> None:
    """Verifies unexpected exceptions during TCP connection are handled safely."""
    with patch("asyncio.open_connection", side_effect=RuntimeError("System socket limit")):
        res = await probe_tcp("example.com", port=443)

    assert res.success is False
    assert "Unexpected TCP error" in str(res.error)


@pytest.mark.asyncio
async def test_probe_tls_ssl_error() -> None:
    """Verifies SSL verification and handshake errors are captured as failure data."""
    import ssl

    mock_writer = MagicMock()
    mock_writer.start_tls = AsyncMock(side_effect=ssl.SSLError("CERTIFICATE_VERIFY_FAILED"))
    mock_writer.wait_closed = AsyncMock(return_value=None)

    with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
        mock_open.return_value = (MagicMock(), mock_writer)
        res = await probe_tls("self-signed.badssl.com", port=443)

    assert res.success is False
    assert "TLS handshake failed" in str(res.error)


@pytest.mark.asyncio
async def test_probe_tls_unexpected_exception() -> None:
    """Verifies unexpected TLS exceptions are captured cleanly."""
    mock_writer = MagicMock()
    mock_writer.start_tls = AsyncMock(side_effect=RuntimeError("Crypto backend failure"))
    mock_writer.wait_closed = AsyncMock(return_value=None)

    with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
        mock_open.return_value = (MagicMock(), mock_writer)
        res = await probe_tls("broken.example.com", port=443)

    assert res.success is False
    assert "Unexpected TLS error" in str(res.error)


@pytest.mark.asyncio
async def test_probe_http_request_error() -> None:
    """Verifies httpx RequestError is captured as structured failure data."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Network is unreachable")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        res = await probe_http("https://example.com/unreachable", client=client)

    assert res.success is False
    assert "HTTP request failed" in str(res.error)


@pytest.mark.asyncio
async def test_probe_http_default_client() -> None:
    """Verifies probe_http constructs and manages its own client when none is injected."""
    with patch("httpx.AsyncClient.stream") as mock_stream:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.http_version = "HTTP/1.1"
        mock_resp.headers = {"content-type": "text/html"}

        # Async context manager mock for client.stream
        mock_stream.return_value.__aenter__.return_value = mock_resp
        mock_stream.return_value.__aexit__.return_value = None

        res = await probe_http("https://example.com")

    assert res.success is True
    assert res.phase == "http"
    assert res.details.get("status_code") == 200
