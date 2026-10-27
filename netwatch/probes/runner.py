from datetime import datetime, timezone
from urllib.parse import urlparse

from netwatch.probes.dns import probe_dns
from netwatch.probes.http import probe_http
from netwatch.probes.models import PhaseResult, TargetProbeResult
from netwatch.probes.tcp import probe_tcp
from netwatch.probes.tls import probe_tls


def parse_target(target: str) -> tuple[str, str, int, bool]:
    """Normalizes input targets into structured parameters (url, host, port, is_tls)."""
    raw = target.strip()
    if not (raw.startswith("http://") or raw.startswith("https://")):
        # Default bare hostnames to secure HTTPS for standard web endpoint health checks
        raw = f"https://{raw}"

    parsed = urlparse(raw)
    host = parsed.hostname or raw
    is_tls = parsed.scheme == "https"
    default_port = 443 if is_tls else 80
    port = parsed.port or default_port

    return raw, host, port, is_tls


async def run_all_probes(
    target: str,
    phase_timeout: float = 5.0,
) -> TargetProbeResult:
    """Orchestrates multi-phase probes against a target, recording metrics even on failure."""
    url, host, port, is_tls = parse_target(target)
    timestamp = datetime.now(timezone.utc)

    # 1. DNS Phase
    dns_res = await probe_dns(host, timeout=phase_timeout)
    resolved_ip: str | None = None
    if dns_res.success and dns_res.details.get("resolved_ips"):
        resolved_ip = dns_res.details["resolved_ips"][0]

    # 2. TCP Phase
    if dns_res.success:
        tcp_res = await probe_tcp(host, port=port, ip=resolved_ip, timeout=phase_timeout)
    else:
        tcp_res = PhaseResult(
            phase="tcp",
            success=False,
            duration_seconds=None,
            error="Skipped: DNS resolution failed",
        )

    # 3. TLS Phase
    tls_cert_expiry_days: float | None = None
    if is_tls:
        if tcp_res.success:
            tls_res = await probe_tls(host, port=port, timeout=phase_timeout)
            tls_cert_expiry_days = tls_res.details.get("days_to_expiry")
        else:
            tls_res = PhaseResult(
                phase="tls",
                success=False,
                duration_seconds=None,
                error="Skipped: TCP connection failed",
            )
    else:
        tls_res = PhaseResult(
            phase="tls",
            success=True,
            duration_seconds=0.0,
            details={"skipped": True, "reason": "Non-TLS target"},
        )

    # 4. HTTP Phase
    if tcp_res.success and (not is_tls or tls_res.success):
        http_res = await probe_http(url, timeout=phase_timeout)
    else:
        http_res = PhaseResult(
            phase="http",
            success=False,
            duration_seconds=None,
            error="Skipped: Prior transport phase failed",
        )

    overall_success = dns_res.success and tcp_res.success and tls_res.success and http_res.success

    return TargetProbeResult(
        target=target,
        url=url,
        host=host,
        port=port,
        timestamp=timestamp,
        dns=dns_res,
        tcp=tcp_res,
        tls=tls_res,
        http=http_res,
        tls_cert_expiry_days=tls_cert_expiry_days,
        success=overall_success,
    )
