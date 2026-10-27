import asyncio
import time

from netwatch.probes.models import TcpResult


async def connect_tcp(
    ip: str,
    port: int,
    timeout_s: float = 5.0,
) -> tuple[TcpResult, tuple[asyncio.StreamReader, asyncio.StreamWriter] | None]:
    """Establishes raw TCP socket connection, returning latency in ms and live stream pair."""
    start = time.perf_counter()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port),
            timeout=timeout_s,
        )
        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
        return TcpResult(ok=True, tcp_ms=elapsed_ms), (reader, writer)
    except asyncio.TimeoutError:
        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
        err = f"TCP connection timed out after {timeout_s}s"
        return TcpResult(ok=False, tcp_ms=elapsed_ms, error=err), None
    except OSError as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
        return TcpResult(ok=False, tcp_ms=elapsed_ms, error=f"TCP connection failed: {exc}"), None
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
        return TcpResult(ok=False, tcp_ms=elapsed_ms, error=f"Unexpected TCP error: {exc}"), None


async def probe_tcp(ip: str, port: int, timeout_s: float = 5.0) -> TcpResult:
    """Standalone TCP probe establishing and immediately closing socket connection."""
    res, streams = await connect_tcp(ip, port, timeout_s=timeout_s)
    if streams:
        _, writer = streams
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
    return res
