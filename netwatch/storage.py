import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from netwatch.metrics import netwatch_fenced_writes_total, update_probe_metrics
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
) -> ProbeResultRecord | None:
    """Conditionally persists probe telemetry under current epoch and notifies cluster."""
    now = datetime.now(timezone.utc)
    # Fencing condition prevents stale split-brain writes if a paused ex-leader resumes
    sql = text(
        """
        INSERT INTO results (
            target_id, ts, ok, dns_ms, tcp_ms, tls_ms, http_ms, total_ms,
            status_code, tls_days_left, error, replica_id, epoch
        )
        SELECT
            :target_id, :ts, :ok, :dns_ms, :tcp_ms, :tls_ms, :http_ms, :total_ms,
            :status_code, :tls_days_left, :error, :replica_id, :epoch
        WHERE COALESCE((SELECT epoch FROM leadership), 0) = :epoch
        RETURNING id;
        """
    )
    res = await session.execute(
        sql,
        {
            "target_id": target_id,
            "ts": now,
            "ok": result.ok,
            "dns_ms": result.dns_ms,
            "tcp_ms": result.tcp_ms,
            "tls_ms": result.tls_ms,
            "http_ms": result.http_ms,
            "total_ms": result.total_ms,
            "status_code": result.status_code,
            "tls_days_left": result.tls_days_left,
            "error": result.error,
            "replica_id": replica_id,
            "epoch": epoch,
        },
    )
    inserted_id = res.scalar_one_or_none()
    if inserted_id is None:
        netwatch_fenced_writes_total.inc()
        logger.warning(
            "Fenced write rejected for target '%s': epoch %d != cluster leader",
            host,
            epoch,
        )
        return None

    await session.commit()
    update_probe_metrics(host=host, result=result)

    payload = json.dumps(
        {
            "kind": "probe_result",
            "id": inserted_id,
            "target_id": target_id,
            "host": host,
            "ok": result.ok,
            "total_ms": result.total_ms,
            "dns_ms": result.dns_ms,
            "tcp_ms": result.tcp_ms,
            "tls_ms": result.tls_ms,
            "http_ms": result.http_ms,
            "status_code": result.status_code,
            "tls_days_left": result.tls_days_left,
            "error": result.error,
            "ts": now.isoformat(),
            "replica_id": replica_id,
            "epoch": epoch,
        }
    )
    await session.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": "netwatch_events", "payload": payload},
    )
    await session.commit()

    return ProbeResultRecord(
        id=inserted_id,
        target_id=target_id,
        ts=now,
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
