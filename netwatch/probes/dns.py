import ipaddress
import time

import dns.asyncresolver
import dns.exception
import dns.resolver

from netwatch.probes.models import PhaseResult


async def probe_dns(host: str, timeout: float = 5.0) -> PhaseResult:
    """Isolates DNS resolution as a phase to reveal resolver issues before socket connection."""
    # Check if host is already an IP literal to avoid redundant network round-trips
    try:
        ipaddress.ip_address(host)
        return PhaseResult(
            phase="dns",
            success=True,
            duration_seconds=0.0,
            details={"resolved_ips": [host], "is_ip_literal": True},
        )
    except ValueError:
        pass

    resolver = dns.asyncresolver.Resolver()
    resolver.timeout = timeout
    resolver.lifetime = timeout

    start = time.perf_counter()
    try:
        # Query A records first; if absent, fallback to AAAA
        try:
            answers = await resolver.resolve(host, "A", lifetime=timeout)
        except (dns.resolver.NoAnswer, dns.resolver.NoNameservers):
            answers = await resolver.resolve(host, "AAAA", lifetime=timeout)

        duration = time.perf_counter() - start
        resolved_ips = [str(rdata) for rdata in answers]
        return PhaseResult(
            phase="dns",
            success=True,
            duration_seconds=duration,
            details={"resolved_ips": resolved_ips},
        )
    except dns.resolver.NXDOMAIN:
        duration = time.perf_counter() - start
        return PhaseResult(
            phase="dns",
            success=False,
            duration_seconds=duration,
            error=f"NXDOMAIN: host '{host}' does not exist",
        )
    except (dns.resolver.Timeout, dns.exception.Timeout):
        duration = time.perf_counter() - start
        return PhaseResult(
            phase="dns",
            success=False,
            duration_seconds=duration,
            error=f"DNS query timed out after {timeout}s",
        )
    except Exception as exc:
        duration = time.perf_counter() - start
        return PhaseResult(
            phase="dns",
            success=False,
            duration_seconds=duration,
            error=f"DNS resolution failed: {exc}",
        )
