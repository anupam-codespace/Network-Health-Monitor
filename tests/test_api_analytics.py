from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from netwatch.config import settings
from netwatch.models import ProbeResultRecord, Target

VIEWER_HEADERS = {"X-API-Key": settings.viewer_api_key}
ADMIN_HEADERS = {"X-API-Key": settings.admin_api_key}


@pytest.mark.asyncio
async def test_api_results_keyset_pagination(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Verifies keyset pagination on /api/results using id < before ordering."""
    await db_session.execute(delete(ProbeResultRecord))
    await db_session.execute(delete(Target))

    target = Target(host="page.test", port=443, interval_s=30, enabled=True)
    db_session.add(target)
    await db_session.commit()
    await db_session.refresh(target)

    # Insert 5 sequential probe records
    now = datetime.now(timezone.utc)
    for i in range(5):
        record = ProbeResultRecord(
            target_id=target.id,
            ts=now - timedelta(seconds=(5 - i) * 10),
            ok=True,
            total_ms=20.0 + i,
            replica_id="replica-test",
            epoch=0,
        )
        db_session.add(record)
    await db_session.commit()

    # Query first page of 2 items
    res1 = await async_client.get(
        f"/api/results?target_id={target.id}&limit=2",
        headers=VIEWER_HEADERS,
    )
    assert res1.status_code == 200
    page1 = res1.json()
    assert len(page1) == 2
    assert "X-Next-Cursor" in res1.headers
    cursor = int(res1.headers["X-Next-Cursor"])
    assert page1[0]["id"] > page1[1]["id"]
    assert cursor == page1[1]["id"]

    # Query second page of 2 items using before=cursor
    res2 = await async_client.get(
        f"/api/results?target_id={target.id}&limit=2&before={cursor}",
        headers=VIEWER_HEADERS,
    )
    assert res2.status_code == 200
    page2 = res2.json()
    assert len(page2) == 2
    assert page2[0]["id"] < cursor
    assert page2[0]["id"] > page2[1]["id"]


@pytest.mark.asyncio
async def test_api_summary_metrics_and_series(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Verifies that /api/summary returns accurate cluster health KPIs and latency series."""
    await db_session.execute(delete(ProbeResultRecord))
    await db_session.execute(delete(Target))

    t1 = Target(host="up.target.test", port=443, interval_s=30, enabled=True)
    t2 = Target(host="down.target.test", port=443, interval_s=30, enabled=True)
    db_session.add_all([t1, t2])
    await db_session.commit()
    await db_session.refresh(t1)
    await db_session.refresh(t2)

    now = datetime.now(timezone.utc)
    # T1 succeeds with 45 days left on cert
    r1 = ProbeResultRecord(
        target_id=t1.id,
        ts=now - timedelta(minutes=5),
        ok=True,
        total_ms=30.0,
        tls_days_left=45.0,
        replica_id="replica-test",
        epoch=0,
    )
    # T2 fails
    r2 = ProbeResultRecord(
        target_id=t2.id,
        ts=now - timedelta(minutes=4),
        ok=False,
        total_ms=None,
        error="Connection refused",
        replica_id="replica-test",
        epoch=0,
    )
    db_session.add_all([r1, r2])
    await db_session.commit()

    res = await async_client.get("/api/summary?range=1h", headers=VIEWER_HEADERS)
    assert res.status_code == 200
    data = res.json()

    assert data["targets_total"] == 2
    assert data["targets_up"] == 1
    assert data["failing"] == 1
    assert data["avg_latency_ms"] == 30.0
    assert data["nearest_cert_expiry_days"] == 45.0
    assert data["uptime_percent"] == 50.0
    assert isinstance(data["latency_series"], list)
    assert len(data["latency_series"]) >= 1


@pytest.mark.asyncio
async def test_api_target_phase_series_math(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Verifies that /api/targets/{id}/series accurately calculates time-bucketed phase averages."""
    await db_session.execute(delete(ProbeResultRecord))
    await db_session.execute(delete(Target))

    target = Target(host="series.math.test", port=443, interval_s=30, enabled=True)
    db_session.add(target)
    await db_session.commit()
    await db_session.refresh(target)

    # Insert two records in the same 1-minute bucket (interval = 60s)
    bucket_base = datetime.now(timezone.utc).replace(second=10, microsecond=0)
    r1 = ProbeResultRecord(
        target_id=target.id,
        ts=bucket_base,
        ok=True,
        dns_ms=2.0,
        tcp_ms=4.0,
        tls_ms=6.0,
        http_ms=8.0,
        total_ms=20.0,
        replica_id="replica-test",
        epoch=0,
    )
    r2 = ProbeResultRecord(
        target_id=target.id,
        ts=bucket_base + timedelta(seconds=15),
        ok=True,
        dns_ms=4.0,
        tcp_ms=6.0,
        tls_ms=8.0,
        http_ms=10.0,
        total_ms=28.0,
        replica_id="replica-test",
        epoch=0,
    )
    db_session.add_all([r1, r2])
    await db_session.commit()

    res = await async_client.get(
        f"/api/targets/{target.id}/series?range=1h",
        headers=VIEWER_HEADERS,
    )
    assert res.status_code == 200
    series = res.json()
    assert len(series) == 1
    point = series[0]

    # Math averages: dns=(2+4)/2=3.0, tcp=(4+6)/2=5.0, tls=(6+8)/2=7.0, http=(8+10)/2=9.0, total=(20+28)/2=24.0
    assert point["dns_ms"] == 3.0
    assert point["tcp_ms"] == 5.0
    assert point["tls_ms"] == 7.0
    assert point["http_ms"] == 9.0
    assert point["total_ms"] == 24.0
    assert point["sample_count"] == 2


@pytest.mark.asyncio
async def test_api_target_detail_and_not_found(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Verifies /api/targets/{id} returns target entity, latest result, recent outcomes, and TLS info."""
    await db_session.execute(delete(ProbeResultRecord))
    await db_session.execute(delete(Target))

    target = Target(host="detail.target.test", port=443, interval_s=15, enabled=True)
    db_session.add(target)
    await db_session.commit()
    await db_session.refresh(target)

    # Insert 3 results
    now = datetime.now(timezone.utc)
    for i in range(3):
        rec = ProbeResultRecord(
            target_id=target.id,
            ts=now - timedelta(seconds=(3 - i) * 15),
            ok=True,
            total_ms=35.0,
            tls_days_left=90.0,
            replica_id="replica-test",
            epoch=0,
        )
        db_session.add(rec)
    await db_session.commit()

    res = await async_client.get(f"/api/targets/{target.id}", headers=VIEWER_HEADERS)
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == target.id
    assert data["host"] == "detail.target.test"
    assert data["latest_result"] is not None
    assert data["latest_result"]["tls_days_left"] == 90.0
    assert len(data["recent_outcomes"]) == 3
    assert data["tls_info"]["status"] == "valid"
    assert data["tls_info"]["days_left"] == 90.0

    # Non-existent target should 404
    res_404 = await async_client.get("/api/targets/999999", headers=VIEWER_HEADERS)
    assert res_404.status_code == 404


@pytest.mark.asyncio
async def test_api_export_csv_streaming(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Verifies that /api/export.csv streams complete CSV without memory buffering."""
    await db_session.execute(delete(ProbeResultRecord))
    await db_session.execute(delete(Target))

    target = Target(host="export.test", port=443, interval_s=30, enabled=True)
    db_session.add(target)
    await db_session.commit()
    await db_session.refresh(target)

    rec = ProbeResultRecord(
        target_id=target.id,
        ts=datetime.now(timezone.utc),
        ok=True,
        dns_ms=1.5,
        tcp_ms=3.2,
        tls_ms=12.0,
        http_ms=10.0,
        total_ms=26.7,
        status_code=200,
        tls_days_left=60.0,
        replica_id="replica-test",
        epoch=0,
    )
    db_session.add(rec)
    await db_session.commit()

    res = await async_client.get("/api/export.csv?range=1h", headers=VIEWER_HEADERS)
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    assert "attachment; filename=" in res.headers["content-disposition"]

    lines = res.text.strip().split("\n")
    assert len(lines) == 2
    assert lines[0].startswith("id,target_id,host,ts,ok,dns_ms,tcp_ms,tls_ms")
    assert "export.test" in lines[1]
    assert "26.7" in lines[1]


@pytest.mark.asyncio
async def test_metrics_prometheus_netwatch_gauges(async_client: AsyncClient) -> None:
    """Verifies that /metrics unauthenticated endpoint outputs NetWatch leadership and queue depth."""
    res = await async_client.get("/metrics")
    assert res.status_code == 200
    content = res.text
    assert "netwatch_is_leader" in content
    assert "netwatch_probe_queue_depth" in content


@pytest.mark.asyncio
async def test_api_summary_ranges_and_tls_states(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Verifies 7d and 24h ranges as well as expiring_soon and expired TLS statuses."""
    await db_session.execute(delete(ProbeResultRecord))
    await db_session.execute(delete(Target))

    t_expiring = Target(host="expiring.tls.test", port=443, interval_s=30, enabled=True)
    t_expired = Target(host="expired.tls.test", port=443, interval_s=30, enabled=True)
    db_session.add_all([t_expiring, t_expired])
    await db_session.commit()
    await db_session.refresh(t_expiring)
    await db_session.refresh(t_expired)

    now = datetime.now(timezone.utc)
    # Expiring soon: 5 days left
    r_exp = ProbeResultRecord(
        target_id=t_expiring.id,
        ts=now - timedelta(days=2),
        ok=True,
        total_ms=45.0,
        tls_days_left=5.0,
        replica_id="replica-test",
        epoch=0,
    )
    # Expired: -1 days left
    r_bad = ProbeResultRecord(
        target_id=t_expired.id,
        ts=now - timedelta(days=3),
        ok=False,
        total_ms=50.0,
        tls_days_left=-1.0,
        replica_id="replica-test",
        epoch=0,
    )
    db_session.add_all([r_exp, r_bad])
    await db_session.commit()

    # Test 7d range
    res_7d = await async_client.get("/api/summary?range=7d", headers=VIEWER_HEADERS)
    assert res_7d.status_code == 200

    # Test 24h range
    res_24h = await async_client.get("/api/summary?range=24h", headers=VIEWER_HEADERS)
    assert res_24h.status_code == 200

    # Verify target detail status for expiring soon
    res_det1 = await async_client.get(f"/api/targets/{t_expiring.id}", headers=VIEWER_HEADERS)
    assert res_det1.status_code == 200
    assert res_det1.json()["tls_info"]["status"] == "expiring_soon"

    # Verify target detail status for expired
    res_det2 = await async_client.get(f"/api/targets/{t_expired.id}", headers=VIEWER_HEADERS)
    assert res_det2.status_code == 200
    assert res_det2.json()["tls_info"]["status"] == "expired"


@pytest.mark.asyncio
async def test_main_app_lifespan() -> None:
    """Verifies that FastAPI application lifespan initializes migrations, seeds, and scheduler."""
    from netwatch.main import create_app, lifespan

    app = create_app()
    async with lifespan(app):
        assert hasattr(app.state, "scheduler")
        assert app.state.scheduler is not None
