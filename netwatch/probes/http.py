import asyncio
import ssl
import time
from netwatch.probes.models import HttpResult


async def send_http_request(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    host: str,
    timeout_s: float = 5.0,
) -> HttpResult:
    """Sends minimal HTTP/1.1 GET over open stream to measure true Time-To-First-Byte in milliseconds."""
    req = f"GET / HTTP/1.1\r\nHost: {host}\r\nUser-Agent: NetWatch/0.1\r\nConnection: close\r\n\r\n".encode()
    start = time.perf_counter()
    try:
        writer.write(req)
        await writer.drain()

        # Read first status line to capture TTFB before large response body chunks arrive
        line = await asyncio.wait_for(reader.readline(), timeout=timeout_s)
        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)

        raw_line = line.decode("iso-8859-1").strip()
        parts = raw_line.split(" ", 2)
        if len(parts) >= 2 and parts[1].isdigit():
            status_code = int(parts[1])
            ok = status_code < 500
            error = None if ok else f"HTTP {status_code} Server Error"
            return HttpResult(ok=ok, http_ms=elapsed_ms, status_code=status_code, error=error)

        return HttpResult(
            ok=False,
            http_ms=elapsed_ms,
            error=f"Malformed HTTP response line: {raw_line[:64]}",
        )
    except asyncio.TimeoutError:
        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
        return HttpResult(
            ok=False, http_ms=elapsed_ms, error=f"HTTP TTFB timed out after {timeout_s}s"
        )
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
        return HttpResult(ok=False, http_ms=elapsed_ms, error=f"HTTP probe failed: {exc}")


async def probe_http(
    host: str,
    port: int = 80,
    is_tls: bool = False,
    timeout_s: float = 5.0,
    ssl_context: ssl.SSLContext | None = None,
) -> HttpResult:
    """Standalone HTTP probe opening socket, performing optional TLS, and measuring TTFB."""
    try:
        context = (ssl_context or ssl.create_default_context()) if is_tls else None
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=context, server_hostname=host if is_tls else None),
            timeout=timeout_s,
        )
    except Exception as exc:
        return HttpResult(ok=False, error=f"Transport connection failed: {exc}")

    try:
        return await send_http_request(reader, writer, host, timeout_s=timeout_s)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
