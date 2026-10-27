import asyncio
import json
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from prometheus_client import REGISTRY
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from netwatch.config import settings
from netwatch.db import pg_notify
from netwatch.events import EventBroker, PostgresEventListener
from netwatch.leader import LeaderElector
from netwatch.models import EventRecord, Leadership, ProbeResultRecord, ReplicaHeartbeat, Target
from netwatch.probes.models import (
    DnsResult,
    HttpResult,
    ProbeCompositeResult,
    TcpResult,
    TlsResult,
)
from netwatch.storage import record_result

VIEWER_HEADERS = {"X-API-Key": settings.viewer_api_key}


def _dummy_composite(host: str = "example.com") -> ProbeCompositeResult:
    """Creates a basic ProbeCompositeResult for testing telemetry writes."""
    return ProbeCompositeResult(
        host=host,
        port=443,
        ok=True,
        dns=DnsResult(ok=True, dns_ms=1.2),
        tcp=TcpResult(ok=True, tcp_ms=5.4),
        tls=TlsResult(ok=True, tls_ms=12.1),
        http=HttpResult(ok=True, http_ms=18.0, status_code=200),
        total_ms=36.7,
        dns_ms=1.2,
        tcp_ms=5.4,
        tls_ms=12.1,
        http_ms=18.0,
        status_code=200,
    )


TEST_ADVISORY_LOCK_ID = 888777666


@pytest.mark.asyncio
async def test_two_electors_exactly_one_leader(db_session: AsyncSession) -> None:
    """Verifies that between two competing electors, exactly one acquires leadership."""
    elector1 = LeaderElector("rep-test-1", lock_id=TEST_ADVISORY_LOCK_ID, tick_interval_s=0.1)
    elector2 = LeaderElector("rep-test-2", lock_id=TEST_ADVISORY_LOCK_ID, tick_interval_s=0.1)

    try:
        await elector1.start()
        await elector2.start()

        # Allow election ticks to settle
        for _ in range(15):
            await asyncio.sleep(0.1)
            if elector1.is_leader() or elector2.is_leader():
                break

        # Exactly one must be leader, the other standby
        assert elector1.is_leader() != elector2.is_leader()
        assert (elector1.is_leader() and not elector2.is_leader()) or (
            elector2.is_leader() and not elector1.is_leader()
        )
    finally:
        await elector1.stop()
        await elector2.stop()


@pytest.mark.asyncio
async def test_pg_terminate_backend_promotes_standby(db_session: AsyncSession) -> None:
    """Verifies that abruptly terminating the leader's backend connection triggers failover."""
    elector1 = LeaderElector("rep-test-1", lock_id=TEST_ADVISORY_LOCK_ID, tick_interval_s=0.1)
    elector2 = LeaderElector("rep-test-2", lock_id=TEST_ADVISORY_LOCK_ID, tick_interval_s=0.1)

    try:
        await elector1.start()
        # Wait for elector1 to acquire leadership
        for _ in range(20):
            await asyncio.sleep(0.1)
            if elector1.is_leader():
                break
        assert elector1.is_leader() is True
        initial_epoch = elector1.current_epoch

        await elector2.start()
        await asyncio.sleep(0.2)
        assert elector2.is_leader() is False

        # Terminate backend connection of elector1 to simulate sudden node crash
        assert elector1._conn is not None
        leader_pid = elector1._conn.get_server_pid()
        await db_session.execute(text(f"SELECT pg_terminate_backend({leader_pid})"))
        await db_session.commit()

        # Elector2 should detect released lock and promote
        for _ in range(30):
            await asyncio.sleep(0.1)
            if elector2.is_leader():
                break

        assert elector2.is_leader() is True
        assert elector2.current_epoch > initial_epoch

        # Elector1 detects terminated connection and steps down
        for _ in range(20):
            if not elector1.is_leader():
                break
            await asyncio.sleep(0.1)

        assert elector1.is_leader() is False
    finally:
        await elector1.stop()
        await elector2.stop()


@pytest.mark.asyncio
async def test_stale_epoch_fencing_rejects_write(db_session: AsyncSession) -> None:
    """Verifies that conditional insert fences off writes with stale epochs."""
    await db_session.execute(delete(ProbeResultRecord))
    await db_session.execute(delete(Target))
    await db_session.execute(delete(Leadership))

    target = Target(host="fence.test.com", port=443, interval_s=30, enabled=True)
    db_session.add(target)
    # Set current leadership epoch to 5
    lead = Leadership(epoch=5, holder="replica-active", acquired_at=datetime.now(timezone.utc))
    db_session.add(lead)
    await db_session.commit()
    await db_session.refresh(target)

    # Initial fenced metric count
    initial_fenced = REGISTRY.get_sample_value("netwatch_fenced_writes_total") or 0.0

    # Write from ex-leader with stale epoch 4
    result = _dummy_composite("fence.test.com")
    stale_write = await record_result(
        session=db_session,
        target_id=target.id,
        host=target.host,
        result=result,
        replica_id="replica-paused",
        epoch=4,
    )
    assert stale_write is None

    new_fenced = REGISTRY.get_sample_value("netwatch_fenced_writes_total") or 0.0
    assert new_fenced == initial_fenced + 1.0

    # Write from active leader with epoch 5 succeeds
    valid_write = await record_result(
        session=db_session,
        target_id=target.id,
        host=target.host,
        result=result,
        replica_id="replica-active",
        epoch=5,
    )
    assert valid_write is not None
    assert valid_write.id is not None


@pytest.mark.asyncio
async def test_postgres_notify_reaches_subscriber() -> None:
    """Verifies that pg_notify dispatches real-time events to PostgresEventListener subscribers."""
    broker = EventBroker()
    listener = PostgresEventListener(channel="netwatch_events", broker=broker)
    await listener.start()

    queue = broker.subscribe()
    try:
        # Give listener connection a brief moment to attach
        await asyncio.sleep(0.2)

        # Broadcast test event via pg_notify
        test_payload = json.dumps({"kind": "test_ping", "msg": "hello_from_pg"})
        await pg_notify("netwatch_events", test_payload)

        # Wait for subscriber queue to receive broadcast
        received = await asyncio.wait_for(queue.get(), timeout=3.0)
        assert received.get("kind") == "test_ping"
        assert received.get("msg") == "hello_from_pg"
    finally:
        broker.unsubscribe(queue)
        await listener.stop()


@pytest.mark.asyncio
async def test_api_cluster_and_events_endpoints(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Verifies GET /api/cluster and GET /api/events return live replica and event state."""
    await db_session.execute(delete(EventRecord))
    await db_session.execute(delete(ReplicaHeartbeat))
    await db_session.execute(delete(Leadership))

    now = datetime.now(timezone.utc)
    # Replica heartbeats
    hb1 = ReplicaHeartbeat(
        replica_id="replica-1",
        role="LEADER",
        last_seen=now,
        started_at=now,
    )
    hb2 = ReplicaHeartbeat(
        replica_id="replica-2",
        role="STANDBY",
        last_seen=now,
        started_at=now,
    )
    # Leadership
    lead = Leadership(epoch=1, holder="replica-1", acquired_at=now)
    # Event
    evt = EventRecord(
        ts=now,
        kind="leader_acquired",
        replica_id="replica-1",
        detail={"epoch": 1, "holder": "replica-1"},
    )
    db_session.add_all([hb1, hb2, lead, evt])
    await db_session.commit()

    # Query /api/cluster
    res_cluster = await async_client.get("/api/cluster", headers=VIEWER_HEADERS)
    assert res_cluster.status_code == 200
    data = res_cluster.json()
    assert len(data["replicas"]) == 2
    assert data["current_epoch"] == 1
    assert data["leader"] == "replica-1"
    assert len(data["recent_events"]) >= 1

    # Query /api/events with keyset pagination
    res_events = await async_client.get("/api/events?limit=5", headers=VIEWER_HEADERS)
    assert res_events.status_code == 200
    events_list = res_events.json()
    assert len(events_list) >= 1
    assert events_list[0]["kind"] == "leader_acquired"
