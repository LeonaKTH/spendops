"""report views, upload quality and drill-down filters

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 上传幂等：同一文件内容只注册一次；quality 保存导入时的行级校验摘要。
    op.add_column("datasets", sa.Column("content_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "datasets",
        sa.Column("quality", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_datasets_content_hash", "datasets", ["content_hash"])

    # 分享链接绑定报表下钻条件。
    op.add_column("report_shares", sa.Column("provider", sa.String(length=200), nullable=True))

    # 复用 reports 表保存命名报表视图。
    op.add_column(
        "reports",
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "reports",
        sa.Column("dataset_name", sa.String(length=200), nullable=False, server_default=""),
    )
    op.add_column(
        "reports",
        sa.Column(
            "created_by_username", sa.String(length=64), nullable=False, server_default=""
        ),
    )
    op.add_column("reports", sa.Column("period_start", sa.Date(), nullable=True))
    op.add_column("reports", sa.Column("period_end", sa.Date(), nullable=True))
    op.add_column("reports", sa.Column("provider", sa.String(length=200), nullable=True))
    op.add_column(
        "reports",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_reports_owner_id", "reports", ["owner_id"])
    op.create_index("ix_reports_dataset_id", "reports", ["dataset_id"])


def downgrade() -> None:
    op.drop_index("ix_reports_dataset_id", table_name="reports")
    op.drop_index("ix_reports_owner_id", table_name="reports")
    op.drop_column("reports", "updated_at")
    op.drop_column("reports", "provider")
    op.drop_column("reports", "period_end")
    op.drop_column("reports", "period_start")
    op.drop_column("reports", "created_by_username")
    op.drop_column("reports", "dataset_name")
    op.drop_column("reports", "owner_id")

    op.drop_column("report_shares", "provider")

    op.drop_index("ix_datasets_content_hash", table_name="datasets")
    op.drop_column("datasets", "quality")
    op.drop_column("datasets", "content_hash")
