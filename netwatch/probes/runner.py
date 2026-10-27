import ssl

from netwatch.probes.dns import probe_dns
from netwatch.probes.http import send_http_request
from netwatch.probes.models import (
    HttpResult,
    ProbeCompositeResult,
    TcpResult,
    TlsResult,
)
from netwatch.probes.tcp import connect_tcp
from netwatch.probes.tls import upgrade_to_tls


async def run_probes(
    host: str,
    port: int = 443,
    is_tls: bool | None = None,
    timeout_s: float = 5.0,
    ssl_context: ssl.SSLContext | None = None,
) -> ProbeCompositeResult:
    """Coordinates the 4-phase probe pipeline across a single connection."""
    effective_tls = is_tls if is_tls is not None else (port == 443)
    dns_res = await probe_dns(host, timeout_s=timeout_s)

    # If DNS resolution fails, downstream transport phases cannot execute
    if not dns_res.ok or not dns_res.resolved_ip:
        return ProbeCompositeResult(
            host=host,
            port=port,
            ok=False,
            dns=dns_res,
            tcp=TcpResult(ok=False, error="Skipped: DNS resolution failed"),
            tls=TlsResult(ok=False, error="Skipped: DNS resolution failed"),
            http=HttpResult(ok=False, error="Skipped: DNS resolution failed"),
            total_ms=dns_res.dns_ms,
            first_failing_phase="dns",
            dns_ms=dns_res.dns_ms,
            error=dns_res.error,
        )

    tcp_res, streams = await connect_tcp(dns_res.resolved_ip, port, timeout_s=timeout_s)
    if not tcp_res.ok or not streams:
        return ProbeCompositeResult(
            host=host,
            port=port,
            ok=False,
            dns=dns_res,
            tcp=tcp_res,
            tls=TlsResult(ok=False, error="Skipped: TCP connection failed"),
            http=HttpResult(ok=False, error="Skipped: TCP connection failed"),
            total_ms=round((dns_res.dns_ms or 0.0) + (tcp_res.tcp_ms or 0.0), 2),
            first_failing_phase="tcp",
            dns_ms=dns_res.dns_ms,
            tcp_ms=tcp_res.tcp_ms,
            error=tcp_res.error,
        )

    reader, writer = streams
    try:
        # 3. TLS Phase
        if effective_tls:
            tls_res = await upgrade_to_tls(
                writer, host, timeout_s=timeout_s, ssl_context=ssl_context
            )
            if not tls_res.ok:
                return ProbeCompositeResult(
                    host=host,
                    port=port,
                    ok=False,
                    dns=dns_res,
                    tcp=tcp_res,
                    tls=tls_res,
                    http=HttpResult(ok=False, error="Skipped: TLS handshake failed"),
                    total_ms=round(
                        (dns_res.dns_ms or 0.0) + (tcp_res.tcp_ms or 0.0) + (tls_res.tls_ms or 0.0),
                        2,
                    ),
                    first_failing_phase="tls",
                    dns_ms=dns_res.dns_ms,
                    tcp_ms=tcp_res.tcp_ms,
                    tls_ms=tls_res.tls_ms,
                    error=tls_res.error,
                )
        else:
            tls_res = TlsResult(ok=True, tls_ms=0.0, tls_days_left=None)

        # 4. HTTP Phase
        http_res = await send_http_request(reader, writer, host, timeout_s=timeout_s)
        first_fail = None if http_res.ok else "http"
        total_ms = round(
            (dns_res.dns_ms or 0.0)
            + (tcp_res.tcp_ms or 0.0)
            + (tls_res.tls_ms or 0.0)
            + (http_res.http_ms or 0.0),
            2,
        )

        return ProbeCompositeResult(
            host=host,
            port=port,
            ok=http_res.ok,
            dns=dns_res,
            tcp=tcp_res,
            tls=tls_res,
            http=http_res,
            total_ms=total_ms,
            first_failing_phase=first_fail,
            dns_ms=dns_res.dns_ms,
            tcp_ms=tcp_res.tcp_ms,
            tls_ms=tls_res.tls_ms,
            http_ms=http_res.http_ms,
            status_code=http_res.status_code,
            tls_days_left=tls_res.tls_days_left,
            error=http_res.error,
        )
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
