import hashlib
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netwatch.config import settings
from netwatch.db import get_db
from netwatch.models import ApiKey


class Role(StrEnum):
    """Role-Based Access Control privilege tiers."""

    ADMIN = "admin"
    VIEWER = "viewer"


def hash_api_key(raw_key: str) -> str:
    """Computes deterministic SHA-256 digest of plaintext API key for secure storage."""
    return hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()


async def seed_api_keys(session: AsyncSession) -> None:
    """Idempotently seeds default admin and viewer keys into database during application startup."""
    admin_hash = hash_api_key(settings.admin_api_key)
    viewer_hash = hash_api_key(settings.viewer_api_key)

    # Check and insert admin key
    admin_exists = await session.scalar(
        select(ApiKey).where(ApiKey.key_hash == admin_hash)
    )
    if not admin_exists:
        session.add(
            ApiKey(
                key_hash=admin_hash,
                role=Role.ADMIN,
                label=f"Seeded Admin ({settings.replica_id})",
            )
        )

    # Check and insert viewer key
    viewer_exists = await session.scalar(
        select(ApiKey).where(ApiKey.key_hash == viewer_hash)
    )
    if not viewer_exists:
        session.add(
            ApiKey(
                key_hash=viewer_hash,
                role=Role.VIEWER,
                label=f"Seeded Viewer ({settings.replica_id})",
            )
        )

    await session.commit()


async def get_current_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    session: AsyncSession = Depends(get_db),
) -> ApiKey:
    """Authenticates incoming requests by checking the X-API-Key header against database hashes."""
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )

    key_hash = hash_api_key(x_api_key)
    record = await session.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash))
    if not record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    return record


ApiKeyDep = Annotated[ApiKey, Depends(get_current_api_key)]


def require_role(required_role: Role):
    """Enforces role-based hierarchy (Admin has full access; Viewer is read-only)."""

    async def _role_checker(api_key: ApiKeyDep) -> ApiKey:
        if required_role == Role.ADMIN and api_key.role != Role.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: admin role required",
            )
        return api_key

    return _role_checker


# Convenient dependencies for route handlers
require_admin = require_role(Role.ADMIN)
require_viewer = require_role(Role.VIEWER)
