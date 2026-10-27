import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from netwatch.api.routes import api_router, root_router
from netwatch.auth import seed_api_keys
from netwatch.config import settings
from netwatch.db import async_session_maker, run_migrations_with_lock
from netwatch.events import PostgresEventListener
from netwatch.heartbeat import HeartbeatService
from netwatch.leader import LeaderElector
from netwatch.scheduler import ProbeScheduler
from netwatch.seeds import seed_targets_if_empty

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("netwatch.main")

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan managing migrations, leader election, heartbeats, and probing."""
    logger.info("Starting NetWatch replica '%s'...", settings.replica_id)
    scheduler: ProbeScheduler | None = None
    elector: LeaderElector | None = None
    heartbeat: HeartbeatService | None = None
    event_listener: PostgresEventListener | None = None

    try:
        # Run database migrations safely serialized across replicas
        await run_migrations_with_lock()

        # Seed initial admin, viewer API keys, and initial targets
        async with async_session_maker() as session:
            await seed_api_keys(session)
            await seed_targets_if_empty(session)

        # 1. Start Postgres LISTEN/NOTIFY event listener
        event_listener = PostgresEventListener()
        app.state.event_listener = event_listener
        await event_listener.start()

        # 2. Instantiate probe scheduler
        scheduler = ProbeScheduler()
        app.state.scheduler = scheduler

        # 3. Instantiate and start leader elector
        elector = LeaderElector(
            replica_id=settings.replica_id,
            on_promoted=scheduler.trigger_reconcile,
            on_demoted=scheduler.cancel_probes,
        )
        app.state.elector = elector

        # Connect elector state to scheduler and start services
        scheduler.leader_fn = elector.is_leader
        scheduler.epoch_fn = lambda: elector.current_epoch
        await elector.start()

        # 4. Instantiate and start heartbeat service
        heartbeat = HeartbeatService(
            replica_id=settings.replica_id,
            role_fn=lambda: "LEADER" if elector.is_leader() else "STANDBY",
        )
        app.state.heartbeat = heartbeat
        await heartbeat.start()

        # 5. Start probe scheduler supervisor
        await scheduler.start()

    except Exception as exc:
        logger.error("Initialization failure during startup: %s", exc)
        raise

    logger.info("NetWatch initialization complete. Serving endpoints.")
    yield

    logger.info("Shutting down NetWatch replica '%s'...", settings.replica_id)
    if scheduler:
        await scheduler.stop()
    if heartbeat:
        await heartbeat.stop()
    if elector:
        await elector.stop()
    if event_listener:
        await event_listener.stop()


def create_app() -> FastAPI:
    """Factory creating configured FastAPI application instance."""
    application = FastAPI(
        title="NetWatch API",
        version="0.1.0",
        description="Network Health Monitor with leader failover and real-time dashboard",
        lifespan=lifespan,
    )

    # Register root routes (/healthz, /metrics) and API routes (/api/*)
    application.include_router(root_router)
    application.include_router(api_router)

    if STATIC_DIR.exists():
        application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @application.get("/", response_class=FileResponse)
    async def serve_index():
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return Response(content="NetWatch API Running", media_type="text/plain")

    return application


app = create_app()
