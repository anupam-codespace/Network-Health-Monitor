import asyncio
from unittest.mock import AsyncMock, patch

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
from netwatch.scheduler import ProbeScheduler


def _make_dummy_result(host: str, ok: bool, error: str | None = None) -> ProbeCompositeResult:
    """Helper creating synthetic probe composite results for deterministic testing."""
    return ProbeCompositeResult(
        host=host,
        port=443,
        ok=ok,
        dns=DnsResult(ok=ok, dns_ms=2.0 if ok else None, resolved_ip="1.1.1.1" if ok else None),
        tcp=TcpResult(ok=ok, tcp_ms=5.0 if ok else None),
        tls=TlsResult(ok=ok, tls_ms=10.0 if ok else None),
        http=HttpResult(ok=ok, http_ms=15.0 if ok else None, status_code=200 if ok else 500),
        total_ms=32.0 if ok else None,
        dns_ms=2.0 if ok else None,
        tcp_ms=5.0 if ok else None,
        tls_ms=10.0 if ok else None,
        http_ms=15.0 if ok else None,
        status_code=200 if ok else 500,
        error=error,
    )


@pytest.mark.asyncio
async def test_scheduler_runs_due_targets_only(db_session: AsyncSession) -> None:
    """Verifies that the scheduler runs probes for enabled targets and ignores disabled ones."""
    await db_session.execute(delete(ProbeResultRecord))
    await db_session.execute(delete(Target))

    t_enabled = Target(host="enabled.target.test", port=443, interval_s=10, enabled=True)
    t_disabled = Target(host="disabled.target.test", port=443, interval_s=10, enabled=False)
    db_session.add_all([t_enabled, t_disabled])
    await db_session.commit()
    await db_session.refresh(t_enabled)
    await db_session.refresh(t_disabled)

    scheduler = ProbeScheduler(max_concurrency=5, sync_interval_s=0.1)
    await scheduler._reconcile_targets()

    # Enabled target should have an active running task; disabled target should not
    assert t_enabled.id in scheduler.running_tasks
    assert t_disabled.id not in scheduler.running_tasks

    await scheduler.stop()


@pytest.mark.asyncio
async def test_failing_target_does_not_block_others(db_session: AsyncSession) -> None:
    """Verifies that a failing target records failure telemetry and does not halt other targets."""
    await db_session.execute(delete(ProbeResultRecord))
    await db_session.execute(delete(Target))

    t_fail = Target(host="fail.target.test", port=443, interval_s=10, enabled=True)
    t_succ = Target(host="success.target.test", port=443, interval_s=10, enabled=True)
    db_session.add_all([t_fail, t_succ])
    await db_session.commit()
    await db_session.refresh(t_fail)
    await db_session.refresh(t_succ)

    async def mock_run_probes(host: str, port: int):
        if host == "fail.target.test":
            return _make_dummy_result(host, ok=False, error="DNS timeout")
        return _make_dummy_result(host, ok=True)

    scheduler = ProbeScheduler(max_concurrency=5)

    with patch("netwatch.scheduler.run_probes", side_effect=mock_run_probes):
        # Run execution directly for both targets
        await scheduler._execute_and_store(t_fail.id, t_fail.host, t_fail.port)
        await scheduler._execute_and_store(t_succ.id, t_succ.host, t_succ.port)

    stmt_fail = select(ProbeResultRecord).where(ProbeResultRecord.target_id == t_fail.id)
    res_fail = (await db_session.scalars(stmt_fail)).all()

    stmt_succ = select(ProbeResultRecord).where(ProbeResultRecord.target_id == t_succ.id)
    res_succ = (await db_session.scalars(stmt_succ)).all()

    assert len(res_fail) == 1
    assert res_fail[0].ok is False
    assert res_fail[0].error == "DNS timeout"

    assert len(res_succ) == 1
    assert res_succ[0].ok is True
    assert res_succ[0].error is None

    # Verify Prometheus failure counters
    fail_metric = REGISTRY.get_sample_value(
        "probe_success",
        {"target": "fail.target.test"},
    )
    assert fail_metric == 0.0

    succ_metric = REGISTRY.get_sample_value(
        "probe_success",
        {"target": "success.target.test"},
    )
    assert succ_metric == 1.0


@pytest.mark.asyncio
async def test_scheduler_picks_up_target_add_and_delete(db_session: AsyncSession) -> None:
    """Verifies that adding and deleting targets through the database updates tasks without restart."""
    await db_session.execute(delete(ProbeResultRecord))
    await db_session.execute(delete(Target))

    t1 = Target(host="dyn1.target.test", port=443, interval_s=10, enabled=True)
    db_session.add(t1)
    await db_session.commit()
    await db_session.refresh(t1)

    scheduler = ProbeScheduler(max_concurrency=5)
    await scheduler._reconcile_targets()
    assert t1.id in scheduler.running_tasks

    # Add second target
    t2 = Target(host="dyn2.target.test", port=443, interval_s=10, enabled=True)
    db_session.add(t2)
    await db_session.commit()
    await db_session.refresh(t2)

    await scheduler._reconcile_targets()
    assert t1.id in scheduler.running_tasks
    assert t2.id in scheduler.running_tasks

    # Delete first target
    await db_session.delete(t1)
    await db_session.commit()

    await scheduler._reconcile_targets()
    assert t1.id not in scheduler.running_tasks
    assert t2.id in scheduler.running_tasks

    await scheduler.stop()


@pytest.mark.asyncio
async def test_scheduler_leader_gate(db_session: AsyncSession) -> None:
    """Verifies that when is_leader() is False, probe tasks are canceled and leader metric is 0."""
    await db_session.execute(delete(Target))
    t = Target(host="gate.target.test", port=443, interval_s=10, enabled=True)
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    is_leader_flag = True

    def mock_leader():
        return is_leader_flag

    scheduler = ProbeScheduler(max_concurrency=5, leader_fn=mock_leader)
    await scheduler._reconcile_targets()
    assert t.id in scheduler.running_tasks
    assert REGISTRY.get_sample_value("netwatch_is_leader") == 1.0

    # Switch to standby (not leader)
    is_leader_flag = False
    await scheduler._reconcile_targets()
    assert len(scheduler.running_tasks) == 0
    assert REGISTRY.get_sample_value("netwatch_is_leader") == 0.0

    await scheduler.stop()


@pytest.mark.asyncio
async def test_scheduler_lifecycle_and_interval_change(db_session: AsyncSession) -> None:
    """Verifies ProbeScheduler start/stop lifecycle and target interval adjustments."""
    await db_session.execute(delete(Target))
    t = Target(host="interval.target.test", port=443, interval_s=20, enabled=True)
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    scheduler = ProbeScheduler(max_concurrency=5, sync_interval_s=0.05)
    await scheduler.start()

    # Allow supervisor loop to run at least one tick
    await asyncio.sleep(0.1)
    assert t.id in scheduler.running_tasks
    assert scheduler.target_intervals[t.id] == 20

    # Change interval in database
    t.interval_s = 45
    db_session.add(t)
    await db_session.commit()

    # Next reconcile should detect interval change and reschedule
    await scheduler._reconcile_targets()
    assert scheduler.target_intervals[t.id] == 45

    await scheduler.stop()
