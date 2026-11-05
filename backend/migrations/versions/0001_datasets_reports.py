"""create datasets and reports

Revision ID: 0001
Revises:
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("physical_table", sa.String(length=200), nullable=False),
        sa.Column("source_file", sa.String(length=500), nullable=False),
        sa.Column("sheet_name", sa.String(length=200), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("owner_id", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("physical_table", name="uq_datasets_physical_table"),
    )
    op.create_index("ix_datasets_status", "datasets", ["status"])

    op.create_table(
        "reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("sql", sa.Text(), nullable=True),
        sa.Column("chart_spec", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("layout", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_reports_created_at", "reports", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_reports_created_at", table_name="reports")
    op.drop_table("reports")
    op.drop_index("ix_datasets_status", table_name="datasets")
    op.drop_table("datasets")
