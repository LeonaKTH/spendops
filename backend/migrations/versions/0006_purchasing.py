"""create purchasing domain tables

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. suppliers
    op.create_table(
        "suppliers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("contact_name", sa.String(length=100), nullable=True),
        sa.Column("contact_phone", sa.String(length=64), nullable=True),
        sa.Column("email", sa.String(length=200), nullable=True),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("code", name="uq_suppliers_code"),
        sa.CheckConstraint("status IN ('active', 'inactive', 'blocked')", name="ck_suppliers_status"),
    )
    op.create_index("ix_suppliers_status", "suppliers", ["status"])

    # 2. purchase_orders
    op.create_table(
        "purchase_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_no", sa.String(length=40), nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="CNY"),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("order_no", name="uq_purchase_orders_order_no"),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'partially_received', 'received', 'cancelled')",
            name="ck_purchase_orders_status",
        ),
        sa.CheckConstraint("currency = 'CNY'", name="ck_purchase_orders_currency"),
    )
    op.create_index("ix_purchase_orders_supplier_id", "purchase_orders", ["supplier_id"])
    op.create_index("ix_purchase_orders_status", "purchase_orders", ["status"])
    op.create_index("ix_purchase_orders_order_date", "purchase_orders", ["order_date"])

    # 3. purchase_order_lines
    op.create_table(
        "purchase_order_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("item_code", sa.String(length=64), nullable=False),
        sa.Column("item_name", sa.String(length=200), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False, server_default="件"),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("tax_rate", sa.Numeric(5, 4), nullable=False, server_default="0"),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("received_qty", sa.Numeric(14, 3), nullable=False, server_default="0"),
        sa.Column("invoiced_qty", sa.Numeric(14, 3), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["order_id"], ["purchase_orders.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("order_id", "line_no", name="uq_purchase_order_lines_order_line"),
        sa.CheckConstraint("quantity >= 0", name="ck_pol_quantity_nonneg"),
        sa.CheckConstraint("unit_price >= 0", name="ck_pol_price_nonneg"),
        sa.CheckConstraint("received_qty >= 0", name="ck_pol_received_nonneg"),
        sa.CheckConstraint("received_qty <= quantity", name="ck_pol_received_le_quantity"),
        sa.CheckConstraint("invoiced_qty >= 0", name="ck_pol_invoiced_nonneg"),
        sa.CheckConstraint("invoiced_qty <= quantity", name="ck_pol_invoiced_le_quantity"),
    )
    op.create_index("ix_pol_order_id", "purchase_order_lines", ["order_id"])

    # 4. goods_receipts
    op.create_table(
        "goods_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("receipt_no", sa.String(length=40), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("receipt_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="posted"),
        sa.Column("total_quantity", sa.Numeric(14, 3), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["purchase_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("receipt_no", name="uq_goods_receipts_receipt_no"),
        sa.CheckConstraint("status IN ('posted', 'cancelled')", name="ck_goods_receipts_status"),
    )
    op.create_index("ix_goods_receipts_order_id", "goods_receipts", ["order_id"])
    op.create_index("ix_goods_receipts_supplier_id", "goods_receipts", ["supplier_id"])
    op.create_index("ix_goods_receipts_receipt_date", "goods_receipts", ["receipt_date"])

    # 5. goods_receipt_lines
    op.create_table(
        "goods_receipt_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("receipt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_line_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.ForeignKeyConstraint(["receipt_id"], ["goods_receipts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_line_id"], ["purchase_order_lines.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("receipt_id", "order_line_id", name="uq_grl_receipt_orderline"),
        sa.CheckConstraint("quantity > 0", name="ck_grl_quantity_positive"),
    )
    op.create_index("ix_grl_receipt_id", "goods_receipt_lines", ["receipt_id"])
    op.create_index("ix_grl_order_line_id", "goods_receipt_lines", ["order_line_id"])

    # 6. purchase_invoices
    op.create_table(
        "purchase_invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("invoice_no", sa.String(length=40), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="posted"),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="CNY"),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("tax_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["purchase_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("invoice_no", name="uq_purchase_invoices_invoice_no"),
        sa.CheckConstraint("status IN ('posted', 'cancelled')", name="ck_purchase_invoices_status"),
        sa.CheckConstraint("currency = 'CNY'", name="ck_purchase_invoices_currency"),
    )
    op.create_index("ix_purchase_invoices_order_id", "purchase_invoices", ["order_id"])
    op.create_index("ix_purchase_invoices_supplier_id", "purchase_invoices", ["supplier_id"])
    op.create_index("ix_purchase_invoices_invoice_date", "purchase_invoices", ["invoice_date"])

    # 7. purchase_invoice_lines
    op.create_table(
        "purchase_invoice_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_line_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("item_name", sa.String(length=200), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.ForeignKeyConstraint(["invoice_id"], ["purchase_invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_line_id"], ["purchase_order_lines.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("invoice_id", "order_line_id", name="uq_pil_invoice_orderline"),
        sa.CheckConstraint("quantity >= 0", name="ck_pil_quantity_nonneg"),
    )
    op.create_index("ix_pil_invoice_id", "purchase_invoice_lines", ["invoice_id"])
    op.create_index("ix_pil_order_line_id", "purchase_invoice_lines", ["order_line_id"])


def downgrade() -> None:
    op.drop_table("purchase_invoice_lines")
    op.drop_table("purchase_invoices")
    op.drop_table("goods_receipt_lines")
    op.drop_table("goods_receipts")
    op.drop_table("purchase_order_lines")
    op.drop_table("purchase_orders")
    op.drop_table("suppliers")
