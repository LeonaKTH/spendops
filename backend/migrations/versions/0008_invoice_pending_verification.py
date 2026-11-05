"""add pending_verification status to purchase_invoices

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_purchase_invoices_status", "purchase_invoices", type_="check")
    op.create_check_constraint(
        "ck_purchase_invoices_status",
        "purchase_invoices",
        "status IN ('posted', 'pending_verification', 'cancelled')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_purchase_invoices_status", "purchase_invoices", type_="check")
    op.create_check_constraint(
        "ck_purchase_invoices_status",
        "purchase_invoices",
        "status IN ('posted', 'cancelled')",
    )
