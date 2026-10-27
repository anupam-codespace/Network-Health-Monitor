import asyncio
import ssl
import time
from datetime import datetime, timezone
from typing import Any

from netwatch.probes.models import TlsResult


def parse_cert_days_left(cert: dict[str, Any]) -> float | None:
    """Calculates days remaining until TLS certificate expiration from peer certificate metadata."""
    not_after_str = cert.get("notAfter")
    if not not_after_str:
        return None
    try:
        expiry_dt = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=timezone.utc
        )
        now = datetime.now(timezone.utc)
        return round((expiry_dt - now).total_seconds() / 86400.0, 2)
    except Exception:
        return None


async def upgrade_to_tls(
    writer: asyncio.StreamWriter,
    host: str,
    timeout_s: float = 5.0,
    ssl_context: ssl.SSLContext | None = None,
) -> TlsResult:
    """Upgrades an existing TCP stream to TLS with SNI, returning latency in ms and cert expiry."""
    context = ssl_context or ssl.create_default_context()
    start = time.perf_counter()
    try:
        await asyncio.wait_for(
            writer.start_tls(context, server_hostname=host),
            timeout=timeout_s,
        )
        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
        ssl_obj = writer.get_extra_info("ssl_object")
        peer_cert = ssl_obj.getpeercert() if ssl_obj else {}
        days_left = parse_cert_days_left(peer_cert) if peer_cert else None
        return TlsResult(ok=True, tls_ms=elapsed_ms, tls_days_left=days_left)
    except asyncio.TimeoutError:
        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
        return TlsResult(
            ok=False, tls_ms=elapsed_ms, error=f"TLS handshake timed out after {timeout_s}s"
        )
    except ssl.SSLError as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
        return TlsResult(ok=False, tls_ms=elapsed_ms, error=f"TLS handshake failed: {exc}")
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
        return TlsResult(ok=False, tls_ms=elapsed_ms, error=f"Unexpected TLS error: {exc}")


async def probe_tls(
    host: str,
    port: int = 443,
    timeout_s: float = 5.0,
    ssl_context: ssl.SSLContext | None = None,
) -> TlsResult:
    """Standalone TLS probe opening socket and executing handshake with SNI."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout_s,
        )
    except Exception as exc:
        return TlsResult(ok=False, error=f"TCP connect before TLS failed: {exc}")

    try:
        return await upgrade_to_tls(writer, host, timeout_s=timeout_s, ssl_context=ssl_context)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
