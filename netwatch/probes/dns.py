import ipaddress
import time
import dns.asyncresolver
import dns.exception
import dns.resolver

from netwatch.probes.models import DnsResult


async def probe_dns(host: str, timeout_s: float = 5.0) -> DnsResult:
    """Resolves target hostname via asynchronous dnspython query, recording latency in milliseconds."""
    # Fast path for IP literals to bypass network resolution
    try:
        ipaddress.ip_address(host)
        return DnsResult(ok=True, dns_ms=0.0, resolved_ip=host)
    except ValueError:
        pass

    resolver = dns.asyncresolver.Resolver()
    resolver.timeout = timeout_s
    resolver.lifetime = timeout_s

    start = time.perf_counter()
    try:
        try:
            answers = await resolver.resolve(host, "A", lifetime=timeout_s)
        except (dns.resolver.NoAnswer, dns.resolver.NoNameservers):
            answers = await resolver.resolve(host, "AAAA", lifetime=timeout_s)

        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
        resolved_ip = str(answers[0])
        return DnsResult(ok=True, dns_ms=elapsed_ms, resolved_ip=resolved_ip)
    except dns.resolver.NXDOMAIN:
        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
        return DnsResult(
            ok=False, dns_ms=elapsed_ms, error=f"NXDOMAIN: host '{host}' does not exist"
        )
    except (dns.resolver.Timeout, dns.exception.Timeout):
        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
        return DnsResult(
            ok=False, dns_ms=elapsed_ms, error=f"DNS query timed out after {timeout_s}s"
        )
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
        return DnsResult(ok=False, dns_ms=elapsed_ms, error=f"DNS resolution failed: {exc}")
