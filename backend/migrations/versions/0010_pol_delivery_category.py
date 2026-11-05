"""add expected_delivery_date and category to purchase_order_lines

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "purchase_order_lines",
        sa.Column("category", sa.String(50), nullable=True),
    )
    op.add_column(
        "purchase_order_lines",
        sa.Column("expected_delivery_date", sa.Date(), nullable=True),
    )
    op.create_index(
        "ix_pol_expected_delivery_date",
        "purchase_order_lines",
        ["expected_delivery_date"],
    )
    op.create_index("ix_pol_category", "purchase_order_lines", ["category"])


def downgrade() -> None:
    op.drop_index("ix_pol_category", table_name="purchase_order_lines")
    op.drop_index("ix_pol_expected_delivery_date", table_name="purchase_order_lines")
    op.drop_column("purchase_order_lines", "expected_delivery_date")
    op.drop_column("purchase_order_lines", "category")
