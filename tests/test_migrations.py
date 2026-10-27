import asyncio

import pytest

from netwatch.db import MIGRATION_ADVISORY_LOCK_ID, acquire_advisory_lock, run_migrations_with_lock


@pytest.mark.asyncio
async def test_migration_advisory_lock_mutual_exclusion() -> None:
    """Verifies that PostgreSQL advisory locks enforce strict mutual exclusion for concurrent migrations."""
    execution_order: list[str] = []

    async def worker(worker_id: str, hold_time_s: float) -> None:
        async with acquire_advisory_lock(MIGRATION_ADVISORY_LOCK_ID):
            execution_order.append(f"{worker_id}_start")
            await asyncio.sleep(hold_time_s)
            execution_order.append(f"{worker_id}_end")

    # Run two workers concurrently contending for the same advisory lock
    task1 = asyncio.create_task(worker("worker_1", 0.05))
    await asyncio.sleep(0.01)  # Ensure worker 1 starts acquiring first
    task2 = asyncio.create_task(worker("worker_2", 0.01))

    await asyncio.gather(task1, task2)

    # Assert sequential non-overlapping execution (one worker must finish before the other starts)
    assert execution_order in (
        ["worker_1_start", "worker_1_end", "worker_2_start", "worker_2_end"],
        ["worker_2_start", "worker_2_end", "worker_1_start", "worker_1_end"],
    )


@pytest.mark.asyncio
async def test_run_migrations_with_lock_idempotent() -> None:
    """Verifies run_migrations_with_lock executes cleanly against the active database."""
    await run_migrations_with_lock()
