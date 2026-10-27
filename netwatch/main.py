import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from netwatch.api.routes import api_router, root_router
from netwatch.auth import seed_api_keys
from netwatch.config import settings
from netwatch.db import async_session_maker, run_migrations_with_lock

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("netwatch.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan running migrations under advisory lock and seeding credentials."""
    logger.info("Starting NetWatch replica '%s'...", settings.replica_id)
    try:
        # Run database migrations safely serialized across replicas
        await run_migrations_with_lock()

        # Seed initial admin and viewer API keys
        async with async_session_maker() as session:
            await seed_api_keys(session)
    except Exception as exc:
        logger.error("Initialization failure during startup: %s", exc)
        raise

    logger.info("NetWatch initialization complete. Serving endpoints.")
    yield
    logger.info("Shutting down NetWatch replica '%s'...", settings.replica_id)


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
    return application


app = create_app()
