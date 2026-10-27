import asyncio
import time

from netwatch.probes.models import PhaseResult


async def probe_tcp(
    host: str,
    port: int = 443,
    ip: str | None = None,
    timeout: float = 5.0,
) -> PhaseResult:
    """Probes raw TCP connectivity to isolate routing and firewall state before TLS handshakes."""
    # Target the pre-resolved IP if provided to avoid redundant DNS lookups during TCP phase
    connect_target = ip if ip is not None else host
    start = time.perf_counter()

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(connect_target, port),
            timeout=timeout,
        )
        duration = time.perf_counter() - start

        # Immediately close socket to avoid lingering ESTABLISHED connections on the probed host
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

        return PhaseResult(
            phase="tcp",
            success=True,
            duration_seconds=duration,
            details={"connected_to": connect_target, "port": port},
        )
    except asyncio.TimeoutError:
        duration = time.perf_counter() - start
        return PhaseResult(
            phase="tcp",
            success=False,
            duration_seconds=duration,
            error=f"TCP connection to {connect_target}:{port} timed out after {timeout}s",
            details={"connected_to": connect_target, "port": port},
        )
    except OSError as exc:
        duration = time.perf_counter() - start
        return PhaseResult(
            phase="tcp",
            success=False,
            duration_seconds=duration,
            error=f"TCP connection failed: {exc}",
            details={"connected_to": connect_target, "port": port},
        )
    except Exception as exc:
        duration = time.perf_counter() - start
        return PhaseResult(
            phase="tcp",
            success=False,
            duration_seconds=duration,
            error=f"Unexpected TCP error: {exc}",
            details={"connected_to": connect_target, "port": port},
        )
