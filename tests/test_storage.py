from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from prometheus_client import REGISTRY
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from netwatch.models import ProbeResultRecord, Target
from netwatch.probes.models import (
    DnsResult,
    HttpResult,
    ProbeCompositeResult,
    TcpResult,
    TlsResult,
)
from netwatch.seeds import seed_targets_if_empty
from netwatch.storage import record_result, run_retention_cleanup


@pytest.mark.asyncio
async def test_record_result_persists_telemetry(db_session: AsyncSession) -> None:
    """Verifies that record_result persists probe telemetry and updates Prometheus metrics."""
    # Clean previous results for target
    await db_session.execute(delete(ProbeResultRecord))
    target = Target(host="test.example.com", port=443, interval_s=30, enabled=True)
    db_session.add(target)
    await db_session.commit()
    await db_session.refresh(target)

    composite = ProbeCompositeResult(
        host="test.example.com",
        port=443,
        ok=True,
        dns=DnsResult(ok=True, dns_ms=1.5, resolved_ip="1.2.3.4"),
        tcp=TcpResult(ok=True, tcp_ms=10.2),
        tls=TlsResult(ok=True, tls_ms=25.4, tls_days_left=88.5),
        http=HttpResult(ok=True, http_ms=15.0, status_code=200),
        total_ms=52.1,
        dns_ms=1.5,
        tcp_ms=10.2,
        tls_ms=25.4,
        http_ms=15.0,
        status_code=200,
        tls_days_left=88.5,
    )

    record = await record_result(
        session=db_session,
        target_id=target.id,
        host=target.host,
        result=composite,
        replica_id="replica-test",
        epoch=0,
    )

    assert record.id is not None
    assert record.target_id == target.id
    assert record.ok is True
    assert record.dns_ms == 1.5
    assert record.tcp_ms == 10.2
    assert record.tls_ms == 25.4
    assert record.http_ms == 15.0
    assert record.total_ms == 52.1
    assert record.status_code == 200
    assert record.tls_days_left == 88.5
    assert record.replica_id == "replica-test"
    assert record.epoch == 0

    # Verify Prometheus gauge metrics updated
    success_val = REGISTRY.get_sample_value(
        "probe_success",
        {"target": "test.example.com"},
    )
    assert success_val == 1.0

    cert_days = REGISTRY.get_sample_value(
        "tls_cert_expiry_days",
        {"target": "test.example.com"},
    )
    assert cert_days == 88.5

    dns_duration = REGISTRY.get_sample_value(
        "probe_duration_seconds",
        {"target": "test.example.com", "phase": "dns"},
    )
    assert dns_duration == pytest.approx(0.0015, abs=1e-5)


@pytest.mark.asyncio
async def test_retention_deletes_expired_records(db_session: AsyncSession) -> None:
    """Verifies that retention cleanup strictly purges records older than RETENTION_DAYS."""
    target = Target(host="retention.example.com", port=443, interval_s=30, enabled=True)
    db_session.add(target)
    await db_session.commit()
    await db_session.refresh(target)

    now = datetime.now(timezone.utc)
    # Record from 8 days ago (expired under 7-day policy)
    old_record = ProbeResultRecord(
        target_id=target.id,
        ts=now - timedelta(days=8),
        ok=True,
        total_ms=40.0,
        replica_id="replica-test",
        epoch=0,
    )
    # Record from 2 days ago (active)
    new_record = ProbeResultRecord(
        target_id=target.id,
        ts=now - timedelta(days=2),
        ok=True,
        total_ms=45.0,
        replica_id="replica-test",
        epoch=0,
    )
    db_session.add_all([old_record, new_record])
    await db_session.commit()

    # Run retention cleanup
    deleted = await run_retention_cleanup(session=db_session, retention_days=7)
    assert deleted >= 1

    # Verify old_record is deleted while new_record remains
    res_old = await db_session.get(ProbeResultRecord, old_record.id)
    assert res_old is None

    res_new = await db_session.get(ProbeResultRecord, new_record.id)
    assert res_new is not None


@pytest.mark.asyncio
async def test_seed_targets_if_empty(db_session: AsyncSession, tmp_path: Path) -> None:
    """Verifies that targets are seeded only when the table is empty."""
    # Ensure targets table has no entries
    await db_session.execute(delete(Target))
    await db_session.commit()

    yaml_file = tmp_path / "test_targets.yaml"
    yaml_file.write_text(
        """
        targets:
          - host: host1.example.com
            port: 443
            interval_s: 15
          - host: host2.example.com
            port: 80
            interval_s: 30
        """,
        encoding="utf-8",
    )

    created = await seed_targets_if_empty(session=db_session, seed_path=yaml_file)
    assert created == 2

    # Second invocation should skip seeding because table is no longer empty
    created_second = await seed_targets_if_empty(session=db_session, seed_path=yaml_file)
    assert created_second == 0

    stmt = select(Target).order_by(Target.host.asc())
    targets = (await db_session.scalars(stmt)).all()
    assert len(targets) == 2
    assert targets[0].host == "host1.example.com"
    assert targets[1].host == "host2.example.com"
