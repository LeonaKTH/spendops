"""采购发票业务服务。

关键规则：
- 发票必须能追溯到供应商（必填）与订单/订单明细（可选）。
- 明细金额 = 数量 × 单价，税额按明细税率累加。
- invoice_no 唯一约束兜底幂等。
- 若发票关联订单明细，则校验开票数量不超过订单数量 - 已开票数量。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    PurchaseInvoice,
    PurchaseInvoiceLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
)
from app.services.purchasing.domain import (
    SUPPLIER_BLOCKED,
    BusinessError,
    ConflictError,
    NotFoundError,
    line_amount,
    money,
    total_amount,
)


@dataclass
class InvoiceLineData:
    id: uuid.UUID
    line_no: int
    order_line_id: uuid.UUID | None
    item_name: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal


@dataclass
class InvoiceData:
    id: uuid.UUID
    invoice_no: str
    order_id: uuid.UUID | None
    order_no: str
    supplier_id: uuid.UUID
    supplier_name: str
    invoice_date: date
    status: str
    currency: str
    total_amount: Decimal
    tax_amount: Decimal
    remark: str | None
    lines: list[InvoiceLineData]
    created_at: datetime


def _line_data(line: PurchaseInvoiceLine) -> InvoiceLineData:
    return InvoiceLineData(
        id=line.id,
        line_no=line.line_no,
        order_line_id=line.order_line_id,
        item_name=line.item_name,
        quantity=line.quantity,
        unit_price=line.unit_price,
        amount=line.amount,
    )


def _to_data(invoice: PurchaseInvoice) -> InvoiceData:
    return InvoiceData(
        id=invoice.id,
        invoice_no=invoice.invoice_no,
        order_id=invoice.order_id,
        order_no=invoice.order.order_no if invoice.order else "",
        supplier_id=invoice.supplier_id,
        supplier_name=invoice.supplier.name if invoice.supplier else "",
        invoice_date=invoice.invoice_date,
        status=invoice.status,
        currency=invoice.currency,
        total_amount=invoice.total_amount,
        tax_amount=invoice.tax_amount,
        remark=invoice.remark,
        lines=[_line_data(line) for line in invoice.lines],
        created_at=invoice.created_at,
    )


async def list_invoices(session: AsyncSession, order_id: str | None = None) -> list[InvoiceData]:
    statement = (
        select(PurchaseInvoice)
        .options(
            selectinload(PurchaseInvoice.lines),
            selectinload(PurchaseInvoice.order),
            selectinload(PurchaseInvoice.supplier),
        )
        .order_by(PurchaseInvoice.created_at.desc())
    )
    if order_id:
        try:
            statement = statement.where(PurchaseInvoice.order_id == uuid.UUID(order_id))
        except ValueError as exc:
            raise NotFoundError("无效的采购订单 ID。") from exc
    rows = (await session.execute(statement)).scalars().unique()
    return [_to_data(invoice) for invoice in rows]


async def get_invoice(session: AsyncSession, invoice_id: str) -> InvoiceData:
    try:
        key = uuid.UUID(invoice_id)
    except ValueError as exc:
        raise NotFoundError("无效的发票 ID。") from exc
    invoice = await session.get(
        PurchaseInvoice,
        key,
        options=(
            selectinload(PurchaseInvoice.lines),
            selectinload(PurchaseInvoice.order),
            selectinload(PurchaseInvoice.supplier),
        ),
    )
    if invoice is None:
        raise NotFoundError("发票不存在。")
    return _to_data(invoice)


async def verify_invoice(session: AsyncSession, invoice_id: str) -> InvoiceData:
    """人工核对：把 pending_verification 发票标记为 posted（财务审核通过）。

    仅允许 pending_verification -> posted；posted/cancelled 不可重复核对。
    后续收货补齐数量不会自动改变发票状态，核对必须人工执行。
    """
    try:
        key = uuid.UUID(invoice_id)
    except ValueError as exc:
        raise NotFoundError("无效的发票 ID。") from exc
    invoice = await session.scalar(
        select(PurchaseInvoice)
        .options(
            selectinload(PurchaseInvoice.lines),
            selectinload(PurchaseInvoice.order),
            selectinload(PurchaseInvoice.supplier),
        )
        .where(PurchaseInvoice.id == key)
    )
    if invoice is None:
        raise NotFoundError("发票不存在。")
    if invoice.status == "posted":
        raise BusinessError("发票已核对通过，无需重复操作。")
    if invoice.status == "cancelled":
        raise BusinessError("已取消发票不能核对。")
    # 业务前置：关联订单已取消的发票不能核对通过。
    if invoice.order is not None and invoice.order.status == "cancelled":
        raise BusinessError("关联采购订单已取消，发票不能核对通过。")
    invoice.status = "posted"
    await session.flush()
    return _to_data(invoice)


async def create_invoice(
    session: AsyncSession,
    *,
    invoice_no: str,
    order_id: str | None,
    supplier_id: str,
    invoice_date: date,
    lines: list[dict],
    remark: str | None,
) -> InvoiceData:
    try:
        supplier_key = uuid.UUID(supplier_id)
    except ValueError as exc:
        raise NotFoundError("无效的供应商 ID。") from exc

    supplier = await session.get(Supplier, supplier_key)
    if supplier is None:
        raise NotFoundError("供应商不存在。")
    if supplier.status == SUPPLIER_BLOCKED:
        raise BusinessError("该供应商已停用，不能录入发票。")

    order: PurchaseOrder | None = None
    if order_id:
        try:
            order_key = uuid.UUID(order_id)
        except ValueError as exc:
            raise NotFoundError("无效的采购订单 ID。") from exc
        order = await session.get(PurchaseOrder, order_key)
        if order is None:
            raise NotFoundError("采购订单不存在。")
        if order.supplier_id != supplier_key:
            raise BusinessError("发票的供应商与采购订单的供应商不一致。")

    # 先在事务内校验并锁定订单明细（此时尚未 add invoice，避免 autoflush 使 collection 过期）。
    resolved_lines: list[dict] = []
    pre_invoiced = False  # 是否提前开票（开票数量超过已收货数量）
    for line_in in lines:
        order_line_id = line_in.get("order_line_id")
        quantity = line_in["quantity"]
        unit_price = line_in["unit_price"]
        tax_rate = line_in.get("tax_rate") or Decimal("0")

        resolved_order_line_id: uuid.UUID | None = None
        if order_line_id:
            try:
                ol_key = uuid.UUID(str(order_line_id))
            except ValueError as exc:
                raise NotFoundError(f"无效的订单明细 ID：{order_line_id}。") from exc
            order_line = await session.get(PurchaseOrderLine, ol_key, with_for_update=True)
            if order_line is None:
                raise NotFoundError(f"订单明细 {order_line_id} 不存在。")
            if order is None or order_line.order_id != order.id:
                raise BusinessError(f"订单明细 {order_line_id} 不属于关联订单。")
            # 开票数量约束：已开票 + 本次 <= 订单数量。
            if order_line.invoiced_qty + quantity > order_line.quantity:
                raise BusinessError(
                    f"订单明细「{order_line.item_name}」开票数量超限："
                    f"可开 {order_line.quantity - order_line.invoiced_qty}，本次 {quantity}。"
                )
            # 提前开票判定：开票数量超过已收货数量，说明尚未收货即开票，标记待核对。
            if quantity > order_line.received_qty:
                pre_invoiced = True
            order_line.invoiced_qty = order_line.invoiced_qty + quantity
            resolved_order_line_id = ol_key

        amount = line_amount(quantity, unit_price)
        tax = money(amount * tax_rate)
        resolved_lines.append(
            {
                "order_line_id": resolved_order_line_id,
                "item_name": line_in["item_name"].strip(),
                "quantity": quantity,
                "unit_price": unit_price,
                "amount": amount,
                "tax": tax,
            }
        )

    invoice = PurchaseInvoice(
        invoice_no=invoice_no.strip(),
        order_id=order.id if order else None,
        supplier_id=supplier_key,
        order=order,
        supplier=supplier,
        invoice_date=invoice_date,
        status="pending_verification" if pre_invoiced else "posted",
        currency="CNY",
        remark=remark,
    )
    session.add(invoice)

    amount_list: list[Decimal] = []
    tax_list: list[Decimal] = []
    for index, resolved in enumerate(resolved_lines, start=1):
        amount_list.append(resolved["amount"])
        tax_list.append(resolved["tax"])
        invoice.lines.append(
            PurchaseInvoiceLine(
                line_no=index,
                order_line_id=resolved["order_line_id"],
                item_name=resolved["item_name"],
                quantity=resolved["quantity"],
                unit_price=resolved["unit_price"],
                amount=resolved["amount"],
            )
        )

    invoice.total_amount = total_amount(amount_list)
    invoice.tax_amount = total_amount(tax_list)

    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError(f"发票号「{invoice_no}」已存在。") from exc

    return _to_data(invoice)
