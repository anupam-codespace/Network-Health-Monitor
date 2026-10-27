from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base declarative class for all NetWatch relational models."""

    pass


class Target(Base):
    """Monitored target endpoint configuration."""

    __tablename__ = "targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    host: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=443)
    interval_s: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    results: Mapped[list["ProbeResultRecord"]] = relationship(
        "ProbeResultRecord",
        back_populates="target",
        cascade="all, delete-orphan",
    )


class ProbeResultRecord(Base):
    """Persisted multi-phase telemetry record from a probe execution."""

    __tablename__ = "results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    target_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("targets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    dns_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    tcp_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    tls_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    http_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tls_days_left: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    replica_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    target: Mapped["Target"] = relationship("Target", back_populates="results")


class ApiKey(Base):
    """Hashed API keys for Role-Based Access Control."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)

    __table_args__ = (
        CheckConstraint("role IN ('admin', 'viewer')", name="ck_api_keys_valid_role"),
    )


class ReplicaHeartbeat(Base):
    """Active replica node state tracked via 2-second periodic heartbeat updates."""

    __tablename__ = "replica_heartbeats"

    replica_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Leadership(Base):
    """Singleton row tracking active leadership election epoch and holder."""

    __tablename__ = "leadership"

    epoch: Mapped[int] = mapped_column(Integer, primary_key=True)
    holder: Mapped[str] = mapped_column(String(64), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class EventRecord(Base):
    """Audited system and network health state transition events."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    replica_id: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
