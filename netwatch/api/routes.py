from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from netwatch.api.schemas import (
    LatencyPoint,
    PhaseSeriesPoint,
    ProbeOutcomeSummary,
    ProbeResultResponse,
    SummaryResponse,
    TargetCreate,
    TargetDetailResponse,
    TargetResponse,
    TargetTlsSummary,
)
from netwatch.auth import require_admin, require_viewer
from netwatch.config import settings
from netwatch.db import async_session_maker, get_db
from netwatch.models import ProbeResultRecord, Target

SessionDep = Annotated[AsyncSession, Depends(get_db)]
api_router = APIRouter(prefix="/api")


def parse_time_range(range_param: str) -> tuple[datetime, int]:
    """Translates range string into past UTC cutoff and histogram bucket interval in seconds."""
    now = datetime.now(timezone.utc)
    if range_param == "1h":
        return now - timedelta(hours=1), 60
    if range_param == "7d":
        return now - timedelta(days=7), 14400
    return now - timedelta(hours=24), 900


@api_router.get(
    "/targets",
    response_model=list[TargetResponse],
    dependencies=[Depends(require_viewer)],
)
async def list_targets(session: SessionDep) -> list[Target]:
    """Retrieves all registered monitoring targets for viewers and admins."""
    stmt = select(Target).order_by(Target.id.asc())
    result = await session.scalars(stmt)
    return list(result.all())


@api_router.post(
    "/targets",
    response_model=TargetResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_target(
    payload: TargetCreate,
    session: SessionDep,
) -> Target:
    """Registers a new monitoring target with strict host, port, and interval validation."""
    target = Target(
        host=payload.host,
        port=payload.port,
        interval_s=payload.interval_s,
        enabled=payload.enabled,
    )
    session.add(target)
    await session.commit()
    await session.refresh(target)
    return target


@api_router.get(
    "/targets/{target_id}",
    response_model=TargetDetailResponse,
    dependencies=[Depends(require_viewer)],
)
async def get_target_detail(
    target_id: int,
    session: SessionDep,
) -> TargetDetailResponse:
    """Returns target entity with its latest telemetry, recent 20 outcomes, and TLS state."""
    target = await session.get(Target, target_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Target {target_id} not found",
        )

    # Latest single result
    stmt_latest = (
        select(ProbeResultRecord)
        .where(ProbeResultRecord.target_id == target_id)
        .order_by(ProbeResultRecord.id.desc())
        .limit(1)
    )
    latest = await session.scalar(stmt_latest)

    # Last 20 probe outcomes for health sparkline
    stmt_recent = (
        select(ProbeResultRecord)
        .where(ProbeResultRecord.target_id == target_id)
        .order_by(ProbeResultRecord.id.desc())
        .limit(20)
    )
    recent = (await session.scalars(stmt_recent)).all()
    recent_outcomes = [
        ProbeOutcomeSummary(
            id=r.id,
            ts=r.ts,
            ok=r.ok,
            total_ms=r.total_ms,
            status_code=r.status_code,
            error=r.error,
        )
        for r in recent
    ]

    tls_info = None
    if latest and latest.tls_days_left is not None:
        status_str = (
            "valid"
            if latest.tls_days_left > 14
            else ("expiring_soon" if latest.tls_days_left > 0 else "expired")
        )
        tls_info = TargetTlsSummary(days_left=latest.tls_days_left, status=status_str)

    latest_res = ProbeResultResponse.model_validate(latest) if latest else None
    return TargetDetailResponse(
        id=target.id,
        host=target.host,
        port=target.port,
        interval_s=target.interval_s,
        enabled=target.enabled,
        created_at=target.created_at,
        latest_result=latest_res,
        recent_outcomes=recent_outcomes,
        tls_info=tls_info,
    )


@api_router.delete(
    "/targets/{target_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
async def delete_target(
    target_id: int,
    session: SessionDep,
) -> Response:
    """Deletes an existing target by ID; cascades to all associated historical probe results."""
    target = await session.get(Target, target_id)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Target {target_id} not found",
        )
    await session.delete(target)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@api_router.get(
    "/results",
    response_model=list[ProbeResultResponse],
    dependencies=[Depends(require_viewer)],
)
async def list_results(
    session: SessionDep,
    response: Response,
    target_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    before: int | None = Query(
        default=None, description="Cursor keyset: return records with id < before"
    ),
) -> list[ProbeResultRecord]:
    """Keyset-paginated probe telemetry sorted descending by ID for constant-time paging."""
    stmt = select(ProbeResultRecord).order_by(ProbeResultRecord.id.desc()).limit(limit)
    if target_id is not None:
        stmt = stmt.where(ProbeResultRecord.target_id == target_id)
    if before is not None:
        stmt = stmt.where(ProbeResultRecord.id < before)

    results = list((await session.scalars(stmt)).all())
    if results:
        response.headers["X-Next-Cursor"] = str(results[-1].id)
    return results


@api_router.get(
    "/targets/{target_id}/series",
    response_model=list[PhaseSeriesPoint],
    dependencies=[Depends(require_viewer)],
)
async def get_target_phase_series(
    target_id: int,
    session: SessionDep,
    range: str = Query(default="24h", pattern="^(1h|24h|7d)$"),
) -> list[PhaseSeriesPoint]:
    """Calculates time-bucketed latency averages across each phase for a specific target."""
    target = await session.get(Target, target_id)
    if not target:
        raise HTTPException(status_code=404, detail=f"Target {target_id} not found")

    cutoff, bucket_sec = parse_time_range(range)
    # Uses integer epoch division to form contiguous fixed-interval time buckets
    sql = text(
        """
        SELECT
            to_timestamp(floor(extract(epoch from ts) / :bsec) * :bsec) as bucket,
            round(avg(dns_ms)::numeric, 2) as avg_dns_ms,
            round(avg(tcp_ms)::numeric, 2) as avg_tcp_ms,
            round(avg(tls_ms)::numeric, 2) as avg_tls_ms,
            round(avg(http_ms)::numeric, 2) as avg_http_ms,
            round(avg(total_ms)::numeric, 2) as avg_total_ms,
            count(id) as sample_count
        FROM results
        WHERE target_id = :tid AND ts >= :cutoff
        GROUP BY bucket
        ORDER BY bucket ASC
        """
    )
    result = await session.execute(sql, {"bsec": bucket_sec, "tid": target_id, "cutoff": cutoff})
    return [
        PhaseSeriesPoint(
            bucket=row.bucket,
            dns_ms=float(row.avg_dns_ms) if row.avg_dns_ms is not None else None,
            tcp_ms=float(row.avg_tcp_ms) if row.avg_tcp_ms is not None else None,
            tls_ms=float(row.avg_tls_ms) if row.avg_tls_ms is not None else None,
            http_ms=float(row.avg_http_ms) if row.avg_http_ms is not None else None,
            total_ms=float(row.avg_total_ms) if row.avg_total_ms is not None else None,
            sample_count=row.sample_count,
        )
        for row in result.all()
    ]


@api_router.get(
    "/summary",
    response_model=SummaryResponse,
    dependencies=[Depends(require_viewer)],
)
async def get_summary(
    session: SessionDep,
    range: str = Query(default="24h", pattern="^(1h|24h|7d)$"),
) -> SummaryResponse:
    """Computes cluster-wide health KPIs and an aggregate line chart latency series."""
    cutoff, bucket_sec = parse_time_range(range)

    # 1. Active target count
    stmt_targets = select(Target.id).where(Target.enabled == True)  # noqa: E712
    enabled_target_ids = set((await session.scalars(stmt_targets)).all())
    targets_total = len(enabled_target_ids)

    # 2. Latest status per target for up/failing KPIs and nearest cert expiry
    latest_sql = text(
        """
        SELECT DISTINCT ON (target_id) target_id, ok, total_ms, tls_days_left
        FROM results
        ORDER BY target_id, ts DESC
        """
    )
    latest_rows = (await session.execute(latest_sql)).all()
    active_latest = [r for r in latest_rows if r.target_id in enabled_target_ids]

    targets_up = sum(1 for r in active_latest if r.ok)
    failing = sum(1 for r in active_latest if not r.ok)
    valid_certs = [
        r.tls_days_left
        for r in active_latest
        if r.tls_days_left is not None and r.tls_days_left >= 0
    ]
    nearest_cert = min(valid_certs) if valid_certs else None

    # 3. Overall window averages
    stmt_agg = select(
        func.avg(ProbeResultRecord.total_ms),
        func.count(ProbeResultRecord.id),
        func.sum(case((ProbeResultRecord.ok == True, 1), else_=0)),  # noqa: E712
    ).where(ProbeResultRecord.ts >= cutoff)
    agg_row = (await session.execute(stmt_agg)).one()
    avg_latency = round(float(agg_row[0]), 2) if agg_row[0] is not None else None
    samples_count = agg_row[1] or 0
    success_count = agg_row[2] or 0
    uptime_pct = round((success_count / samples_count) * 100.0, 2) if samples_count > 0 else 100.0

    # 4. Latency trend series across all targets
    series_sql = text(
        """
        SELECT
            to_timestamp(floor(extract(epoch from ts) / :bsec) * :bsec) as bucket,
            round(avg(total_ms)::numeric, 2) as avg_latency
        FROM results
        WHERE ts >= :cutoff AND total_ms IS NOT NULL
        GROUP BY bucket
        ORDER BY bucket ASC
        """
    )
    series_rows = (await session.execute(series_sql, {"bsec": bucket_sec, "cutoff": cutoff})).all()
    latency_series = [
        LatencyPoint(
            ts=row.bucket,
            avg_latency_ms=float(row.avg_latency) if row.avg_latency is not None else None,
        )
        for row in series_rows
    ]

    return SummaryResponse(
        targets_up=targets_up,
        targets_total=targets_total,
        avg_latency_ms=avg_latency,
        failing=failing,
        nearest_cert_expiry_days=nearest_cert,
        uptime_percent=uptime_pct,
        latency_series=latency_series,
    )


async def _generate_csv_chunks(cutoff: datetime) -> AsyncGenerator[str, None]:
    """Streams probe results in fixed batches to eliminate memory pressure on export."""
    yield (
        "id,target_id,host,ts,ok,dns_ms,tcp_ms,tls_ms,http_ms,"
        "total_ms,status_code,tls_days_left,error,replica_id,epoch\n"
    )
    last_id = 0
    batch_size = 200

    while True:
        async with async_session_maker() as stream_session:
            stmt = (
                select(ProbeResultRecord, Target.host)
                .join(Target, ProbeResultRecord.target_id == Target.id)
                .where(ProbeResultRecord.ts >= cutoff, ProbeResultRecord.id > last_id)
                .order_by(ProbeResultRecord.id.asc())
                .limit(batch_size)
            )
            rows = (await stream_session.execute(stmt)).all()
            if not rows:
                break

            for rec, host in rows:
                last_id = rec.id
                err_clean = (rec.error or "").replace('"', '""').replace("\n", " ")
                yield (
                    f"{rec.id},{rec.target_id},{host},{rec.ts.isoformat()},{rec.ok},"
                    f"{rec.dns_ms or ''},{rec.tcp_ms or ''},{rec.tls_ms or ''},"
                    f"{rec.http_ms or ''},{rec.total_ms or ''},{rec.status_code or ''},"
                    f'{rec.tls_days_left or ""},"{err_clean}",{rec.replica_id},{rec.epoch}\n'
                )


@api_router.get(
    "/export.csv",
    dependencies=[Depends(require_viewer)],
)
async def export_csv(
    range: str = Query(default="24h", pattern="^(1h|24h|7d)$"),
) -> StreamingResponse:
    """Streams all probe results for the requested time window as a CSV without buffering."""
    cutoff, _ = parse_time_range(range)
    filename = f"netwatch_export_{range}.csv"
    return StreamingResponse(
        _generate_csv_chunks(cutoff),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Public health and telemetry router
root_router = APIRouter()


@root_router.get("/healthz")
async def healthz():
    """Unauthenticated healthcheck returning container liveness and active replica identity."""
    return {"status": "ok", "replica_id": settings.replica_id}


@root_router.get("/metrics")
async def metrics():
    """Exposes standard Prometheus scrape metrics."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
