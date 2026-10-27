from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netwatch.api.schemas import TargetCreate, TargetResponse
from netwatch.auth import require_admin, require_viewer
from netwatch.config import settings
from netwatch.db import get_db
from netwatch.models import Target

SessionDep = Annotated[AsyncSession, Depends(get_db)]
api_router = APIRouter(prefix="/api")


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
