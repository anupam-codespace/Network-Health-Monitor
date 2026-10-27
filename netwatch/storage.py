import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from netwatch.metrics import update_probe_metrics
from netwatch.models import ProbeResultRecord
from netwatch.probes.models import ProbeCompositeResult

logger = logging.getLogger("netwatch.storage")


async def record_result(
    session: AsyncSession,
    target_id: int,
    host: str,
    result: ProbeCompositeResult,
    replica_id: str,
    epoch: int = 0,
) -> ProbeResultRecord:
    """Persists multi-phase probe telemetry and updates Prometheus metrics."""
    record = ProbeResultRecord(
        target_id=target_id,
        ts=datetime.now(timezone.utc),
        ok=result.ok,
        dns_ms=result.dns_ms,
        tcp_ms=result.tcp_ms,
        tls_ms=result.tls_ms,
        http_ms=result.http_ms,
        total_ms=result.total_ms,
        status_code=result.status_code,
        tls_days_left=result.tls_days_left,
        error=result.error,
        replica_id=replica_id,
        epoch=epoch,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)

    # Export latest telemetry to Prometheus metrics
    update_probe_metrics(host=host, result=result)
    return record


async def run_retention_cleanup(
    session: AsyncSession,
    retention_days: int = 7,
) -> int:
    """Deletes historical results older than retention threshold to bound disk usage."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    stmt = delete(ProbeResultRecord).where(ProbeResultRecord.ts < cutoff)
    res = await session.execute(stmt)
    await session.commit()
    deleted = res.rowcount or 0
    if deleted > 0:
        logger.info("Retention pruned %d records older than %s", deleted, cutoff.isoformat())
    return deleted
