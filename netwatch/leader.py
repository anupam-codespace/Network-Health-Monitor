import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

import asyncpg

from netwatch.config import settings
from netwatch.db import LEADER_ADVISORY_LOCK_ID, get_raw_asyncpg_connection
from netwatch.metrics import netwatch_is_leader

logger = logging.getLogger("netwatch.leader")


class LeaderElector:
    """Coordinates leader election via a long-lived PostgreSQL session advisory lock."""

    def __init__(
        self,
        replica_id: str | None = None,
        lock_id: int = LEADER_ADVISORY_LOCK_ID,
        on_promoted: Callable[[], Awaitable[None]] | None = None,
        on_demoted: Callable[[], Awaitable[None]] | None = None,
        tick_interval_s: float = 1.0,
    ) -> None:
        self.replica_id = replica_id or settings.replica_id
        self.lock_id = lock_id
        self.on_promoted = on_promoted
        self.on_demoted = on_demoted
        self.tick_interval_s = tick_interval_s

        self._conn: asyncpg.Connection | None = None
        self._is_leader: bool = False
        self._current_epoch: int = 0
        self._loop_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    def is_leader(self) -> bool:
        """Returns True if this replica currently holds the active leadership lock."""
        return self._is_leader

    @property
    def current_epoch(self) -> int:
        """Returns the current cluster epoch acknowledged by this replica."""
        return self._current_epoch

    async def start(self) -> None:
        """Starts background election loop on dedicated connection."""
        self._stop_event.clear()
        self._loop_task = asyncio.create_task(self._election_loop())
        logger.info("LeaderElector started for replica '%s'", self.replica_id)

    async def stop(self) -> None:
        """Gracefully steps down, releases advisory lock, and terminates connection."""
        self._stop_event.set()
        await self.step_down_gracefully()
        if self._loop_task:
            self._loop_task.cancel()
        if self._conn:
            try:
                await self._conn.close()
            except Exception:
                pass
            self._conn = None
        logger.info("LeaderElector stopped for replica '%s'", self.replica_id)

    async def step_down_gracefully(self) -> None:
        """Releases the advisory lock and logs leader_released event for instant failover."""
        if not self._is_leader:
            return

        logger.info("Replica '%s' stepping down gracefully...", self.replica_id)
        if self._conn and not self._conn.is_closed():
            try:
                async with self._conn.transaction():
                    detail = json.dumps({"epoch": self._current_epoch, "holder": self.replica_id})
                    await self._conn.execute(
                        "INSERT INTO events (ts, kind, replica_id, detail) "
                        "VALUES (NOW(), 'leader_released', $1, $2::jsonb)",
                        self.replica_id,
                        detail,
                    )
                    payload = json.dumps(
                        {
                            "kind": "leader_released",
                            "replica_id": self.replica_id,
                            "epoch": self._current_epoch,
                            "ts": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                    await self._conn.execute(
                        "SELECT pg_notify($1, $2)",
                        "netwatch_events",
                        payload,
                    )
                # Release advisory lock so standby can acquire it immediately
                await self._conn.execute("SELECT pg_advisory_unlock($1)", self.lock_id)
            except Exception as exc:
                logger.warning("Error releasing advisory lock during graceful step-down: %s", exc)

        self._is_leader = False
        netwatch_is_leader.set(0.0)
        if self.on_demoted:
            try:
                await self.on_demoted()
            except Exception as exc:
                logger.error("Error executing on_demoted callback: %s", exc)

    async def _handle_connection_drop(self) -> None:
        """Steps down immediately on connection loss without modifying database state."""
        if self._is_leader:
            logger.warning("Lost database connection. Stepping down immediately.")
            self._is_leader = False
            netwatch_is_leader.set(0.0)
            if self.on_demoted:
                try:
                    await self.on_demoted()
                except Exception as exc:
                    logger.error("Error executing on_demoted callback: %s", exc)

        if self._conn:
            try:
                await self._conn.close()
            except Exception:
                pass
            self._conn = None

    async def _promote_to_leader(self) -> None:
        """Increments epoch, records holder, logs audit event, and notifies cluster in 1 tx."""
        assert self._conn is not None
        logger.info("Advisory lock acquired. Promoting '%s' to cluster leader...", self.replica_id)
        async with self._conn.transaction():
            row = await self._conn.fetchrow("SELECT epoch FROM leadership FOR UPDATE")
            if row is None:
                new_epoch = 1
                await self._conn.execute(
                    "INSERT INTO leadership (epoch, holder, acquired_at) VALUES ($1, $2, NOW())",
                    new_epoch,
                    self.replica_id,
                )
            else:
                new_epoch = row["epoch"] + 1
                await self._conn.execute(
                    "UPDATE leadership SET epoch = $1, holder = $2, acquired_at = NOW() "
                    "WHERE epoch = $3",
                    new_epoch,
                    self.replica_id,
                    row["epoch"],
                )

            detail = json.dumps({"epoch": new_epoch, "holder": self.replica_id})
            await self._conn.execute(
                "INSERT INTO events (ts, kind, replica_id, detail) "
                "VALUES (NOW(), 'leader_acquired', $1, $2::jsonb)",
                self.replica_id,
                detail,
            )
            payload = json.dumps(
                {
                    "kind": "leader_acquired",
                    "replica_id": self.replica_id,
                    "epoch": new_epoch,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
            )
            await self._conn.execute("SELECT pg_notify($1, $2)", "netwatch_events", payload)

        self._is_leader = True
        self._current_epoch = new_epoch
        netwatch_is_leader.set(1.0)
        logger.info("Promoted to LEADER at epoch %d", new_epoch)

        if self.on_promoted:
            try:
                await self.on_promoted()
            except Exception as exc:
                logger.error("Error executing on_promoted callback: %s", exc)

    async def _election_loop(self) -> None:
        """Runs periodic lock acquisition and keepalive verification every 1 second."""
        while not self._stop_event.is_set():
            try:
                if self._conn is None or self._conn.is_closed():
                    if self._is_leader:
                        await self._handle_connection_drop()
                    self._conn = await get_raw_asyncpg_connection(aggressive_keepalives=True)

                if not self._is_leader:
                    # Sync current epoch even while standing by
                    epoch_val = await self._conn.fetchval("SELECT epoch FROM leadership")
                    if epoch_val is not None:
                        self._current_epoch = int(epoch_val)

                    acquired = await self._conn.fetchval(
                        "SELECT pg_try_advisory_lock($1)", self.lock_id
                    )
                    if acquired:
                        await self._promote_to_leader()
                else:
                    # Liveness check on held advisory lock connection
                    await self._conn.fetchval("SELECT 1")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Leader election error: %s", exc)
                await self._handle_connection_drop()

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.tick_interval_s)
            except asyncio.TimeoutError:
                pass
