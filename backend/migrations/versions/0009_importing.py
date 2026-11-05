"""add import_tasks and import_staging_rows

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "import_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("task_type", sa.String(32), nullable=False),
        sa.Column("original_name", sa.String(500), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="uploaded"),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mapping", postgresql.JSONB(), nullable=True),
        sa.Column("error_summary", postgresql.JSONB(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_username", sa.String(64), nullable=False, server_default=""),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("claimed_by", sa.String(128), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "task_type IN ('supplier', 'purchase_order', 'goods_receipt', 'purchase_invoice')",
            name="ck_import_tasks_type",
        ),
        sa.CheckConstraint(
            "status IN ('uploaded', 'validating', 'awaiting_confirm', 'importing', "
            "'completed', 'partial_failed', 'failed', 'cancelled')",
            name="ck_import_tasks_status",
        ),
    )
    op.create_index(
        "ix_import_tasks_status_created", "import_tasks", ["status", "created_at"]
    )
    op.create_index("ix_import_tasks_file_hash", "import_tasks", ["file_hash"])
    op.create_index("ix_import_tasks_created_by", "import_tasks", ["created_by"])

    op.create_table(
        "import_staging_rows",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("raw_data", postgresql.JSONB(), nullable=False),
        sa.Column("mapped_data", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("error_type", sa.String(64), nullable=True),
        sa.Column("error_field", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("business_key", sa.String(255), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["import_tasks.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN ('pending', 'valid', 'error', 'imported')",
            name="ck_import_staging_status",
        ),
    )
    op.create_index(
        "ix_import_staging_task_status", "import_staging_rows", ["task_id", "status"]
    )
    op.create_index(
        "ix_import_staging_task_row", "import_staging_rows", ["task_id", "row_number"]
    )


def downgrade() -> None:
    op.drop_table("import_staging_rows")
    op.drop_table("import_tasks")
