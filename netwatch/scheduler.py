import asyncio
import logging
import random
from typing import Callable

from sqlalchemy import select

from netwatch.config import settings
from netwatch.db import async_session_maker
from netwatch.metrics import netwatch_is_leader, netwatch_probe_queue_depth
from netwatch.models import Target
from netwatch.probes.runner import run_probes
from netwatch.storage import record_result, run_retention_cleanup

logger = logging.getLogger("netwatch.scheduler")


def is_leader() -> bool:
    """Returns cluster leadership status; hardcoded to True until election in Prompt 3."""
    return True


class ProbeScheduler:
    """Asyncio supervisor managing concurrent target probing and retention cleanup."""

    def __init__(
        self,
        max_concurrency: int | None = None,
        leader_fn: Callable[[], bool] = is_leader,
        epoch_fn: Callable[[], int] = (lambda: 0),
        sync_interval_s: float = 2.0,
    ) -> None:
        self.max_concurrency = max_concurrency or settings.max_concurrent_probes
        self.semaphore = asyncio.Semaphore(self.max_concurrency)
        self.leader_fn = leader_fn
        self.epoch_fn = epoch_fn
        self.sync_interval_s = sync_interval_s
        self.running_tasks: dict[int, asyncio.Task[None]] = {}
        self.target_intervals: dict[int, int] = {}
        self._supervisor_task: asyncio.Task[None] | None = None
        self._retention_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Starts background supervisor and retention tasks."""
        self._stop_event.clear()
        self._supervisor_task = asyncio.create_task(self._supervisor_loop())
        self._retention_task = asyncio.create_task(self._retention_loop())
        logger.info("ProbeScheduler started with max concurrency %d.", self.max_concurrency)

    async def stop(self) -> None:
        """Cancels all active target loops and supervisor tasks cleanly."""
        self._stop_event.set()
        if self._supervisor_task:
            self._supervisor_task.cancel()
        if self._retention_task:
            self._retention_task.cancel()
        await self._cancel_all_probes()
        logger.info("ProbeScheduler stopped successfully.")

    async def _cancel_all_probes(self) -> None:
        """Stops all running probe tasks when standing down or shutting down."""
        for task in self.running_tasks.values():
            task.cancel()
        if self.running_tasks:
            await asyncio.gather(*self.running_tasks.values(), return_exceptions=True)
        self.running_tasks.clear()
        self.target_intervals.clear()

    async def _supervisor_loop(self) -> None:
        """Continuously reconciles database targets against running probe tasks."""
        while not self._stop_event.is_set():
            try:
                await self._reconcile_targets()
            except Exception as exc:
                logger.error("Supervisor encountered unexpected error: %s", exc)

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.sync_interval_s)
            except asyncio.TimeoutError:
                pass

    async def _reconcile_targets(self) -> None:
        """Synchronizes running probe tasks with enabled targets in the database."""
        if not self.leader_fn():
            netwatch_is_leader.set(0.0)
            if self.running_tasks:
                await self._cancel_all_probes()
            return

        netwatch_is_leader.set(1.0)
        async with async_session_maker() as session:
            stmt = select(Target).where(Target.enabled == True)  # noqa: E712
            targets = (await session.scalars(stmt)).all()

        current_ids = {t.id for t in targets}

        # Cancel tasks for targets that were deleted or disabled in the database
        for tid in list(self.running_tasks.keys()):
            if tid not in current_ids:
                logger.info("Stopping probe task for removed/disabled target %d", tid)
                self.running_tasks[tid].cancel()
                del self.running_tasks[tid]
                self.target_intervals.pop(tid, None)

        # Launch or reschedule tasks for current targets
        for target in targets:
            tid = target.id
            if tid in self.running_tasks and self.target_intervals.get(tid) != target.interval_s:
                self.running_tasks[tid].cancel()
                del self.running_tasks[tid]
                self.target_intervals.pop(tid, None)

            if tid not in self.running_tasks or self.running_tasks[tid].done():
                self.target_intervals[tid] = target.interval_s
                task = asyncio.create_task(
                    self._run_target_loop(tid, target.host, target.port, target.interval_s)
                )
                self.running_tasks[tid] = task

    async def _run_target_loop(
        self,
        target_id: int,
        host: str,
        port: int,
        interval_s: int,
    ) -> None:
        """Probes a single target periodically, bounded by the concurrency semaphore."""
        # Random start jitter spreads network load evenly across initial targets
        jitter = random.uniform(0.0, min(5.0, float(interval_s)))
        try:
            await asyncio.sleep(jitter)
        except asyncio.CancelledError:
            return

        while not self._stop_event.is_set():
            start_time = asyncio.get_running_loop().time()
            try:
                await self._execute_and_store(target_id, host, port)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                # Isolates exceptions so a failing host probe never halts sibling probes
                logger.error("Target %s (id=%d) probe failure: %s", host, target_id, exc)

            elapsed = asyncio.get_running_loop().time() - start_time
            sleep_s = max(0.0, float(interval_s) - elapsed)
            try:
                await asyncio.sleep(sleep_s)
            except asyncio.CancelledError:
                break

    async def _execute_and_store(self, target_id: int, host: str, port: int) -> None:
        """Executes the probe pipeline under concurrency limits and persists telemetry."""
        netwatch_probe_queue_depth.inc()
        try:
            async with self.semaphore:
                result = await run_probes(host=host, port=port)
        finally:
            netwatch_probe_queue_depth.dec()

        async with async_session_maker() as session:
            await record_result(
                session=session,
                target_id=target_id,
                host=host,
                result=result,
                replica_id=settings.replica_id,
                epoch=self.epoch_fn(),
            )

    async def cancel_probes(self) -> None:
        """Explicitly cancels all running probe tasks when stepping down from leadership."""
        await self._cancel_all_probes()

    async def trigger_reconcile(self) -> None:
        """Immediately wakes up supervisor to reconcile targets without waiting."""
        await self._reconcile_targets()

    async def _retention_loop(self) -> None:
        """Hourly task pruning historical probe records past retention threshold."""
        while not self._stop_event.is_set():
            try:
                if self.leader_fn():
                    async with async_session_maker() as session:
                        await run_retention_cleanup(session, settings.retention_days)
            except Exception as exc:
                logger.error("Retention pruning encountered an error: %s", exc)

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=3600.0)
            except asyncio.TimeoutError:
                pass
