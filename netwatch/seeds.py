import logging
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from netwatch.config import settings
from netwatch.models import Target

logger = logging.getLogger("netwatch.seeds")


async def seed_targets_if_empty(
    session: AsyncSession,
    seed_path: str | Path | None = None,
) -> int:
    """Seeds default monitored targets from a YAML file only when targets table is empty.

    Avoids overwriting user additions on application restarts.
    """
    stmt = select(func.count(Target.id))
    count = await session.scalar(stmt)
    if count and count > 0:
        logger.debug("Targets table already contains %d entries. Skipping seeding.", count)
        return 0

    path = Path(seed_path or settings.targets_seed_file)
    if not path.is_file():
        # Check fallback in seeds/targets.yaml if file is in subfolder
        fallback = Path("seeds") / path.name
        if fallback.is_file():
            path = fallback
        else:
            logger.warning("Seed targets file '%s' not found. Skipping seeding.", path)
            return 0

    with open(path, "r", encoding="utf-8") as f:
        data: Any = yaml.safe_load(f)

    raw_targets = data.get("targets", data) if isinstance(data, dict) else data
    if not isinstance(raw_targets, list):
        logger.warning("Seed file '%s' does not contain a list of targets.", path)
        return 0

    created = 0
    for item in raw_targets:
        if not isinstance(item, dict) or "host" not in item:
            continue
        target = Target(
            host=item["host"],
            port=item.get("port", 443),
            interval_s=item.get("interval_s", 30),
            enabled=item.get("enabled", True),
        )
        session.add(target)
        created += 1

    await session.commit()
    logger.info("Successfully seeded %d targets from '%s'.", created, path)
    return created
