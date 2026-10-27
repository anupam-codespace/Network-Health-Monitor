import asyncio
import ssl
import time
from datetime import datetime, timezone
from typing import Any

from netwatch.probes.models import PhaseResult


def parse_cert_expiry_days(cert: dict[str, Any]) -> float | None:
    """Computes days remaining until TLS certificate expiration from peer certificate metadata."""
    not_after_str = cert.get("notAfter")
    if not not_after_str:
        return None

    try:
        # Standard OpenSSL string representation: 'Mon DD HH:MM:SS YYYY GMT'
        expiry_dt = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=timezone.utc
        )
        now = datetime.now(timezone.utc)
        delta_seconds = (expiry_dt - now).total_seconds()
        return round(delta_seconds / 86400.0, 2)
    except Exception:
        return None


async def probe_tls(
    host: str,
    port: int = 443,
    server_hostname: str | None = None,
    timeout: float = 5.0,
    ssl_context: ssl.SSLContext | None = None,
) -> PhaseResult:
    """Measures TLS handshake latency and certificate expiry independently from raw TCP."""
    effective_hostname = server_hostname or host
    context = ssl_context or ssl.create_default_context()

    try:
        # Establish raw TCP connection prior to timing the TLS handshake
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
    except Exception as exc:
        return PhaseResult(
            phase="tls",
            success=False,
            duration_seconds=None,
            error=f"Underlying TCP connection failed before TLS handshake: {exc}",
            details={"host": host, "port": port},
        )

    start = time.perf_counter()
    try:
        await asyncio.wait_for(
            writer.start_tls(context, server_hostname=effective_hostname),
            timeout=timeout,
        )
        duration = time.perf_counter() - start

        ssl_obj = writer.get_extra_info("ssl_object")
        peer_cert = ssl_obj.getpeercert() if ssl_obj else {}
        days_to_expiry = parse_cert_expiry_days(peer_cert) if peer_cert else None
        cipher = ssl_obj.cipher() if ssl_obj else None
        tls_version = ssl_obj.version() if ssl_obj else None

        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

        return PhaseResult(
            phase="tls",
            success=True,
            duration_seconds=duration,
            details={
                "tls_version": tls_version,
                "cipher": cipher[0] if cipher else None,
                "days_to_expiry": days_to_expiry,
                "subject": peer_cert.get("subject"),
            },
        )
    except asyncio.TimeoutError:
        duration = time.perf_counter() - start
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return PhaseResult(
            phase="tls",
            success=False,
            duration_seconds=duration,
            error=f"TLS handshake with {host}:{port} timed out after {timeout}s",
        )
    except ssl.SSLError as exc:
        duration = time.perf_counter() - start
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return PhaseResult(
            phase="tls",
            success=False,
            duration_seconds=duration,
            error=f"TLS handshake failed: {exc}",
        )
    except Exception as exc:
        duration = time.perf_counter() - start
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return PhaseResult(
            phase="tls",
            success=False,
            duration_seconds=duration,
            error=f"Unexpected TLS error: {exc}",
        )
