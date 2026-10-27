import asyncio
import json
import logging
from typing import Any

import asyncpg

from netwatch.db import get_raw_asyncpg_connection

logger = logging.getLogger("netwatch.events")


class EventBroker:
    """In-process fan-out broker distributing live cluster events to local subscriber queues."""

    def __init__(self, max_queue_size: int = 100) -> None:
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.max_queue_size = max_queue_size

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Registers a new subscriber queue bounded by max_queue_size."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self.max_queue_size)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Removes an active subscriber queue."""
        self.subscribers.discard(queue)

    def publish(self, event: dict[str, Any]) -> None:
        """Broadcasts event to all subscribers, dropping oldest items on slow queues."""
        for queue in list(self.subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass


# Global singleton in-process broker
event_broker = EventBroker()


class PostgresEventListener:
    """Maintains a dedicated asyncpg connection listening for PostgreSQL LISTEN/NOTIFY events."""

    def __init__(
        self,
        channel: str = "netwatch_events",
        broker: EventBroker = event_broker,
    ) -> None:
        self.channel = channel
        self.broker = broker
        self._conn: asyncpg.Connection | None = None
        self._listener_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Starts background task managing connection and incoming NOTIFY broadcasts."""
        self._stop_event.clear()
        self._listener_task = asyncio.create_task(self._listen_loop())
        logger.info("PostgresEventListener started on channel '%s'", self.channel)

    async def stop(self) -> None:
        """Closes dedicated listener connection cleanly."""
        self._stop_event.set()
        if self._listener_task:
            self._listener_task.cancel()
        if self._conn:
            try:
                await self._conn.close()
            except Exception:
                pass
            self._conn = None
        logger.info("PostgresEventListener stopped.")

    def _on_notification(
        self,
        connection: asyncpg.Connection,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        """Invoked by asyncpg protocol parser when a pg_notify payload arrives."""
        try:
            event = json.loads(payload)
            if isinstance(event, dict):
                self.broker.publish(event)
        except Exception as exc:
            logger.warning("Failed to parse event notification payload '%s': %s", payload, exc)

    async def _listen_loop(self) -> None:
        """Reconnecting supervisor keeping the LISTEN connection open continuously."""
        while not self._stop_event.is_set():
            try:
                self._conn = await get_raw_asyncpg_connection(aggressive_keepalives=True)
                await self._conn.add_listener(self.channel, self._on_notification)
                logger.info("Connected and listening on channel '%s'", self.channel)

                # Keep connection alive until closed or cancelled
                while not self._stop_event.is_set() and not self._conn.is_closed():
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("PostgresEventListener connection error: %s. Retrying in 1s...", exc)
                if self._conn:
                    try:
                        await self._conn.close()
                    except Exception:
                        pass
                    self._conn = None
                await asyncio.sleep(1.0)
