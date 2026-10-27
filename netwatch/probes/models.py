from dataclasses import dataclass


@dataclass(slots=True)
class DnsResult:
    """Telemetry captured from asynchronous DNS resolution phase."""

    ok: bool
    dns_ms: float | None = None
    resolved_ip: str | None = None
    error: str | None = None


@dataclass(slots=True)
class TcpResult:
    """Telemetry captured from raw TCP socket connection phase."""

    ok: bool
    tcp_ms: float | None = None
    error: str | None = None


@dataclass(slots=True)
class TlsResult:
    """Telemetry captured from TLS handshake and certificate validation phase."""

    ok: bool
    tls_ms: float | None = None
    tls_days_left: float | None = None
    error: str | None = None


@dataclass(slots=True)
class HttpResult:
    """Telemetry captured from minimal HTTP/1.1 request time-to-first-byte phase."""

    ok: bool
    http_ms: float | None = None
    status_code: int | None = None
    error: str | None = None


@dataclass(slots=True)
class ProbeCompositeResult:
    """Aggregated probe metrics across all phases with total latency and failure tracking."""

    host: str
    port: int
    ok: bool
    dns: DnsResult
    tcp: TcpResult
    tls: TlsResult
    http: HttpResult
    total_ms: float | None = None
    first_failing_phase: str | None = None
    dns_ms: float | None = None
    tcp_ms: float | None = None
    tls_ms: float | None = None
    http_ms: float | None = None
    status_code: int | None = None
    tls_days_left: float | None = None
    error: str | None = None
