"""create report shares

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "report_shares",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "dataset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dataset_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_username", sa.String(length=64), nullable=False, server_default=""
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("token_hash", name="uq_report_shares_token_hash"),
    )
    op.create_index("ix_report_shares_dataset_id", "report_shares", ["dataset_id"])
    op.create_index("ix_report_shares_created_by", "report_shares", ["created_by"])


def downgrade() -> None:
    op.drop_index("ix_report_shares_created_by", table_name="report_shares")
    op.drop_index("ix_report_shares_dataset_id", table_name="report_shares")
    op.drop_table("report_shares")
