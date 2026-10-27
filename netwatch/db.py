import logging
import socket
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import asyncpg
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
# Postgres advisory lock ID reserved for cluster leader election
LEADER_ADVISORY_LOCK_ID = 827364501

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
            await conn.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": lock_id})
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


async def get_raw_asyncpg_connection(
    dsn: str | None = None,
    aggressive_keepalives: bool = True,
) -> asyncpg.Connection:
    """Creates a dedicated raw asyncpg connection with aggressive TCP keepalives."""
    raw_dsn = (dsn or settings.database_url).replace("postgresql+asyncpg://", "postgresql://")
    server_settings = (
        {
            "tcp_keepalives_idle": "1",
            "tcp_keepalives_interval": "1",
            "tcp_keepalives_count": "3",
        }
        if aggressive_keepalives
        else None
    )
    conn = await asyncpg.connect(raw_dsn, server_settings=server_settings)
    if aggressive_keepalives:
        sock = conn._transport.get_extra_info("socket")
        if sock:
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            except Exception:
                pass
    return conn


async def pg_notify(channel: str, payload: str) -> None:
    """Broadcasts a real-time event across replicas via PostgreSQL LISTEN/NOTIFY."""
    async with async_session_maker() as session:
        await session.execute(
            text("SELECT pg_notify(:channel, :payload)"),
            {"channel": channel, "payload": payload},
        )
        await session.commit()
