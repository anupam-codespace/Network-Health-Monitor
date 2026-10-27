import asyncio
import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import text

from netwatch.config import settings
from netwatch.db import async_session_maker

logger = logging.getLogger("netwatch.heartbeat")


class HeartbeatService:
    """Periodically writes replica liveness heartbeats to PostgreSQL every 2 seconds."""

    def __init__(
        self,
        replica_id: str | None = None,
        role_fn: Callable[[], str] | None = None,
        interval_s: float = 2.0,
    ) -> None:
        self.replica_id = replica_id or settings.replica_id
        self.role_fn = role_fn or (lambda: "STANDBY")
        self.interval_s = interval_s
        self.started_at = datetime.now(timezone.utc)
        self._last_role: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Starts periodic heartbeat upsert background loop."""
        self._stop_event.clear()
        self._task = asyncio.create_task(self._heartbeat_loop())
        logger.info("HeartbeatService started for replica '%s'", self.replica_id)

    async def stop(self) -> None:
        """Stops periodic heartbeat background task."""
        self._stop_event.set()
        if self._task:
            self._task.cancel()
        logger.info("HeartbeatService stopped for replica '%s'", self.replica_id)

    async def write_heartbeat(self) -> None:
        """Executes upsert into replica_heartbeats and broadcasts on role change."""
        current_role = self.role_fn()
        sql = text(
            """
            INSERT INTO replica_heartbeats (replica_id, role, last_seen, started_at)
            VALUES (:rid, :role, NOW(), :started_at)
            ON CONFLICT (replica_id) DO UPDATE SET
                role = EXCLUDED.role,
                last_seen = EXCLUDED.last_seen;
            """
        )
        async with async_session_maker() as session:
            await session.execute(
                sql,
                {
                    "rid": self.replica_id,
                    "role": current_role,
                    "started_at": self.started_at,
                },
            )
            if self._last_role is not None and self._last_role != current_role:
                # Notify cluster of role transition
                payload = json.dumps(
                    {
                        "kind": "replica_role_changed",
                        "replica_id": self.replica_id,
                        "old_role": self._last_role,
                        "new_role": current_role,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }
                )
                await session.execute(
                    text("SELECT pg_notify(:channel, :payload)"),
                    {"channel": "netwatch_events", "payload": payload},
                )
            await session.commit()
            self._last_role = current_role

    async def _heartbeat_loop(self) -> None:
        """Continuously writes heartbeat every interval_s seconds."""
        while not self._stop_event.is_set():
            try:
                await self.write_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Failed to write replica heartbeat: %s", exc)

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_s)
            except asyncio.TimeoutError:
                pass
