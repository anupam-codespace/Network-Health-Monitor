import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from netwatch.config import settings

logger = logging.getLogger("netwatch.db")

# Postgres advisory lock ID reserved for serializing Alembic schema migrations
MIGRATION_ADVISORY_LOCK_ID = 918273645

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=False,
    poolclass=NullPool,
)

async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a transactional async database session."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def acquire_advisory_lock(lock_id: int):
    """Context manager acquiring a PostgreSQL session-level advisory lock to serialize work."""
    async with engine.connect() as conn:
        logger.info("Attempting to acquire PostgreSQL advisory lock %d", lock_id)
        # Block until lock is granted to guarantee safe serialization across replicas
        await conn.execute(text("SELECT pg_advisory_lock(:lock_id)"), {"lock_id": lock_id})
        logger.info("Acquired PostgreSQL advisory lock %d", lock_id)
        try:
            yield conn
        finally:
            await conn.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": lock_id}
            )
            await conn.commit()
            logger.info("Released PostgreSQL advisory lock %d", lock_id)


def _run_alembic_upgrade_sync(connection) -> None:
    from alembic.config import Config

    from alembic import command

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.attributes["connection"] = connection
    command.upgrade(alembic_cfg, "head")


async def run_migrations_with_lock() -> None:
    """Acquires an advisory lock to ensure only one replica runs migrations at startup."""
    async with acquire_advisory_lock(MIGRATION_ADVISORY_LOCK_ID):
        logger.info("Executing Alembic migrations under advisory lock...")
        async with engine.connect() as conn:
            await conn.run_sync(_run_alembic_upgrade_sync)
            await conn.commit()
        logger.info("Alembic migrations completed successfully.")

