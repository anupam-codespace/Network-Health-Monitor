"""Add composite indexes for analytics and keyset pagination.

Revision ID: 002_add_indexes_for_analytics
Revises: 001_initial_schema
Create Date: 2026-10-27 21:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_add_indexes_for_analytics"
down_revision: str | None = "001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Composite indexes optimize target-filtered time ranges and cursor keyset pagination
    op.create_index(
        "ix_results_target_id_ts",
        "results",
        ["target_id", sa.text("ts DESC")],
    )
    op.create_index(
        "ix_results_target_id_id",
        "results",
        ["target_id", sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_results_target_id_id", table_name="results")
    op.drop_index("ix_results_target_id_ts", table_name="results")
