"""SpendOps 采购领域模型。

与上游 datasets/documents 等「动态导入数据」不同，这里是**固定关系、有约束、有状态**
的业务数据。金额一律使用 Decimal（数据库 Numeric），禁止使用 Float 参与财务核对。

业务主键（幂等）：
- Supplier.code
- PurchaseOrder.order_no
- GoodsReceipt.receipt_no
- PurchaseInvoice.invoice_no

这些字段均建唯一约束，重复提交由数据库层兜底拦截。
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# 金额精度：数量支持小数（如公斤、吨），单价保留 4 位小数避免舍入误差，
# 金额统一落 2 位小数（分）。税率为小数比例（0.1300 = 13%）。
QTY_PRECISION = (14, 3)
PRICE_PRECISION = (18, 4)
AMOUNT_PRECISION = (18, 2)
TAX_PRECISION = (5, 4)


class Supplier(Base):
    """供应商。"""

    __tablename__ = "suppliers"
    __table_args__ = (
        UniqueConstraint("code", name="uq_suppliers_code"),
        CheckConstraint("status IN ('active', 'inactive', 'blocked')", name="ck_suppliers_status"),
        Index("ix_suppliers_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    contact_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default=text("'active'")
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )

    orders: Mapped[list["PurchaseOrder"]] = relationship(back_populates="supplier")


class PurchaseOrder(Base):
    """采购订单（头）。"""

    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("order_no", name="uq_purchase_orders_order_no"),
        CheckConstraint(
            "status IN ('draft', 'submitted', 'partially_received', 'received', 'cancelled')",
            name="ck_purchase_orders_status",
        ),
        CheckConstraint("currency = 'CNY'", name="ck_purchase_orders_currency"),
        Index("ix_purchase_orders_supplier_id", "supplier_id"),
        Index("ix_purchase_orders_status", "status"),
        Index("ix_purchase_orders_order_date", "order_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_no: Mapped[str] = mapped_column(String(40))
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT")
    )
    order_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        String(20), default="draft", server_default=text("'draft'")
    )
    currency: Mapped[str] = mapped_column(
        String(3), default="CNY", server_default=text("'CNY'")
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(*AMOUNT_PRECISION), default=Decimal("0"), server_default=text("0")
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )

    supplier: Mapped["Supplier"] = relationship(back_populates="orders")
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="PurchaseOrderLine.line_no",
    )


class PurchaseOrderLine(Base):
    """采购订单明细。"""

    __tablename__ = "purchase_order_lines"
    __table_args__ = (
        UniqueConstraint("order_id", "line_no", name="uq_purchase_order_lines_order_line"),
        CheckConstraint("quantity >= 0", name="ck_pol_quantity_nonneg"),
        CheckConstraint("unit_price >= 0", name="ck_pol_price_nonneg"),
        CheckConstraint("received_qty >= 0", name="ck_pol_received_nonneg"),
        CheckConstraint("received_qty <= quantity", name="ck_pol_received_le_quantity"),
        CheckConstraint("invoiced_qty >= 0", name="ck_pol_invoiced_nonneg"),
        CheckConstraint("invoiced_qty <= quantity", name="ck_pol_invoiced_le_quantity"),
        Index("ix_pol_order_id", "order_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="CASCADE")
    )
    line_no: Mapped[int] = mapped_column(Integer)
    item_code: Mapped[str] = mapped_column(String(64))
    item_name: Mapped[str] = mapped_column(String(200))
    # 物料品类（可选，用于品类分析）。空值表示未归类，不参与品类统计。
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 约定交货日期（可选，用于交货及时率）。空值表示未约定交期，不参与及时率统计。
    expected_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(*QTY_PRECISION))
    unit: Mapped[str] = mapped_column(String(20), default="件")
    unit_price: Mapped[Decimal] = mapped_column(Numeric(*PRICE_PRECISION))
    tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(*TAX_PRECISION), default=Decimal("0"), server_default=text("0")
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(*AMOUNT_PRECISION))
    # 累计已收 / 已开票数量，由服务层在事务内维护，用于收货/开票数量约束。
    received_qty: Mapped[Decimal] = mapped_column(
        Numeric(*QTY_PRECISION), default=Decimal("0"), server_default=text("0")
    )
    invoiced_qty: Mapped[Decimal] = mapped_column(
        Numeric(*QTY_PRECISION), default=Decimal("0"), server_default=text("0")
    )

    order: Mapped["PurchaseOrder"] = relationship(back_populates="lines")


class GoodsReceipt(Base):
    """采购收货单（头）。"""

    __tablename__ = "goods_receipts"
    __table_args__ = (
        UniqueConstraint("receipt_no", name="uq_goods_receipts_receipt_no"),
        CheckConstraint("status IN ('posted', 'cancelled')", name="ck_goods_receipts_status"),
        Index("ix_goods_receipts_order_id", "order_id"),
        Index("ix_goods_receipts_supplier_id", "supplier_id"),
        Index("ix_goods_receipts_receipt_date", "receipt_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    receipt_no: Mapped[str] = mapped_column(String(40))
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="RESTRICT")
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT")
    )
    receipt_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        String(20), default="posted", server_default=text("'posted'")
    )
    total_quantity: Mapped[Decimal] = mapped_column(
        Numeric(*QTY_PRECISION), default=Decimal("0"), server_default=text("0")
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(*AMOUNT_PRECISION), default=Decimal("0"), server_default=text("0")
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    lines: Mapped[list["GoodsReceiptLine"]] = relationship(
        back_populates="receipt",
        cascade="all, delete-orphan",
        order_by="GoodsReceiptLine.line_no",
    )
    order: Mapped["PurchaseOrder"] = relationship()
    supplier: Mapped["Supplier"] = relationship()


class GoodsReceiptLine(Base):
    """采购收货明细。一张收货单对同一订单明细只收一次（唯一约束）。"""

    __tablename__ = "goods_receipt_lines"
    __table_args__ = (
        UniqueConstraint("receipt_id", "order_line_id", name="uq_grl_receipt_orderline"),
        CheckConstraint("quantity > 0", name="ck_grl_quantity_positive"),
        Index("ix_grl_receipt_id", "receipt_id"),
        Index("ix_grl_order_line_id", "order_line_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("goods_receipts.id", ondelete="CASCADE")
    )
    order_line_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_order_lines.id", ondelete="RESTRICT")
    )
    line_no: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[Decimal] = mapped_column(Numeric(*QTY_PRECISION))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(*PRICE_PRECISION))
    amount: Mapped[Decimal] = mapped_column(Numeric(*AMOUNT_PRECISION))

    receipt: Mapped["GoodsReceipt"] = relationship(back_populates="lines")


class PurchaseInvoice(Base):
    """采购发票（头）。"""

    __tablename__ = "purchase_invoices"
    __table_args__ = (
        UniqueConstraint("invoice_no", name="uq_purchase_invoices_invoice_no"),
        CheckConstraint(
            "status IN ('posted', 'pending_verification', 'cancelled')",
            name="ck_purchase_invoices_status",
        ),
        CheckConstraint("currency = 'CNY'", name="ck_purchase_invoices_currency"),
        Index("ix_purchase_invoices_order_id", "order_id"),
        Index("ix_purchase_invoices_supplier_id", "supplier_id"),
        Index("ix_purchase_invoices_invoice_date", "invoice_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    invoice_no: Mapped[str] = mapped_column(String(40))
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="RESTRICT"), nullable=True
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT")
    )
    invoice_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        String(20), default="posted", server_default=text("'posted'")
    )
    currency: Mapped[str] = mapped_column(
        String(3), default="CNY", server_default=text("'CNY'")
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(*AMOUNT_PRECISION), default=Decimal("0"), server_default=text("0")
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(*AMOUNT_PRECISION), default=Decimal("0"), server_default=text("0")
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    lines: Mapped[list["PurchaseInvoiceLine"]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="PurchaseInvoiceLine.line_no",
    )
    order: Mapped["PurchaseOrder | None"] = relationship()
    supplier: Mapped["Supplier"] = relationship()


class PurchaseInvoiceLine(Base):
    """采购发票明细。order_line_id 用于把发票追溯到订单明细。"""

    __tablename__ = "purchase_invoice_lines"
    __table_args__ = (
        UniqueConstraint("invoice_id", "order_line_id", name="uq_pil_invoice_orderline"),
        CheckConstraint("quantity >= 0", name="ck_pil_quantity_nonneg"),
        Index("ix_pil_invoice_id", "invoice_id"),
        Index("ix_pil_order_line_id", "order_line_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_invoices.id", ondelete="CASCADE")
    )
    order_line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_order_lines.id", ondelete="RESTRICT"),
        nullable=True,
    )
    line_no: Mapped[int] = mapped_column(Integer)
    item_name: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[Decimal] = mapped_column(Numeric(*QTY_PRECISION))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(*PRICE_PRECISION))
    amount: Mapped[Decimal] = mapped_column(Numeric(*AMOUNT_PRECISION))

    invoice: Mapped["PurchaseInvoice"] = relationship(back_populates="lines")


class IdempotencyKey(Base):
    """幂等键：记录 Idempotency-Key 与已创建资源的映射。

    客户端对关键写操作传 Idempotency-Key，重试时若 key 与请求内容一致，
    返回原资源，不重复创建。key 作为主键，数据库层保证并发唯一。
    """

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        Index("ix_idempotency_keys_created_at", "created_at"),
    )

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
