import time

import httpx

from netwatch.probes.models import PhaseResult


async def probe_http(
    url: str,
    timeout: float = 5.0,
    client: httpx.AsyncClient | None = None,
) -> PhaseResult:
    """Measures HTTP time-to-first-byte via streaming to isolate server latency."""
    start = time.perf_counter()

    async def _execute_probe(active_client: httpx.AsyncClient) -> PhaseResult:
        nonlocal start
        start = time.perf_counter()
        try:
            # Streaming request pauses after headers are received, accurately capturing TTFB
            async with active_client.stream("GET", url, timeout=timeout) as response:
                ttfb = time.perf_counter() - start
                status_code = response.status_code
                http_version = response.http_version

                return PhaseResult(
                    phase="http",
                    success=status_code < 500,
                    duration_seconds=ttfb,
                    error=None if status_code < 500 else f"HTTP {status_code} Server Error",
                    details={
                        "status_code": status_code,
                        "http_version": http_version,
                        "content_type": response.headers.get("content-type"),
                    },
                )
        except httpx.TimeoutException:
            ttfb = time.perf_counter() - start
            return PhaseResult(
                phase="http",
                success=False,
                duration_seconds=ttfb,
                error=f"HTTP request to {url} timed out after {timeout}s",
            )
        except httpx.RequestError as exc:
            ttfb = time.perf_counter() - start
            return PhaseResult(
                phase="http",
                success=False,
                duration_seconds=ttfb,
                error=f"HTTP request failed: {exc}",
            )
        except Exception as exc:
            ttfb = time.perf_counter() - start
            return PhaseResult(
                phase="http",
                success=False,
                duration_seconds=ttfb,
                error=f"Unexpected HTTP error: {exc}",
            )

    if client is not None:
        return await _execute_probe(client)

    # Use follow_redirects=True to test full user-facing flow up to the target landing page
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as managed_client:
        return await _execute_probe(managed_client)
