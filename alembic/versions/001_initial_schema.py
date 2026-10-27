"""Initial database schema for NetWatch.

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-10-27 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. targets
    op.create_table(
        "targets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False, server_default="443"),
        sa.Column("interval_s", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_targets_host", "targets", ["host"])

    # 2. results
    op.create_table(
        "results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("dns_ms", sa.Float(), nullable=True),
        sa.Column("tcp_ms", sa.Float(), nullable=True),
        sa.Column("tls_ms", sa.Float(), nullable=True),
        sa.Column("http_ms", sa.Float(), nullable=True),
        sa.Column("total_ms", sa.Float(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("tls_days_left", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("replica_id", sa.String(length=64), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["target_id"], ["targets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_results_target_id", "results", ["target_id"])
    op.create_index("ix_results_ts", "results", ["ts"])
    op.create_index("ix_results_replica_id", "results", ["replica_id"])

    # 3. api_keys
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.CheckConstraint("role IN ('admin', 'viewer')", name="ck_api_keys_valid_role"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)

    # 4. replica_heartbeats
    op.create_table(
        "replica_heartbeats",
        sa.Column("replica_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("replica_id"),
    )

    # 5. leadership
    op.create_table(
        "leadership",
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("holder", sa.String(length=64), nullable=False),
        sa.Column(
            "acquired_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("epoch"),
    )

    # 6. events
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("replica_id", sa.String(length=64), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_ts", "events", ["ts"])
    op.create_index("ix_events_kind", "events", ["kind"])


def downgrade() -> None:
    op.drop_table("events")
    op.drop_table("leadership")
    op.drop_table("replica_heartbeats")
    op.drop_table("api_keys")
    op.drop_table("results")
    op.drop_table("targets")
