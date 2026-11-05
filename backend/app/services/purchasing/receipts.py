"""采购收货业务服务。

关键规则：
- 已取消订单不能收货。
- 收货数量不能超过「订单数量 - 已收数量」（在事务内对订单明细行加锁防并发）。
- 一张收货单对同一订单明细只收一次（数据库唯一约束兜底）。
- 收货后订单状态自动联动：全部收满 -> received，否则 -> partially_received。
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
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
)
from app.services.purchasing.domain import (
    ORDER_CANCELLED,
    ORDER_DRAFT,
    ORDER_PARTIALLY_RECEIVED,
    ORDER_RECEIVED,
    BusinessError,
    ConflictError,
    NotFoundError,
    line_amount,
    money,
    total_amount,
)


@dataclass
class ReceiptLineData:
    id: uuid.UUID
    line_no: int
    order_line_id: uuid.UUID
    item_name: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal


@dataclass
class ReceiptData:
    id: uuid.UUID
    receipt_no: str
    order_id: uuid.UUID
    order_no: str
    supplier_id: uuid.UUID
    supplier_name: str
    receipt_date: date
    status: str
    total_quantity: Decimal
    total_amount: Decimal
    remark: str | None
    lines: list[ReceiptLineData]
    created_at: datetime


def _line_data(line: GoodsReceiptLine) -> ReceiptLineData:
    return ReceiptLineData(
        id=line.id,
        line_no=line.line_no,
        order_line_id=line.order_line_id,
        item_name="",
        quantity=line.quantity,
        unit_price=line.unit_price,
        amount=line.amount,
    )


def _to_data(receipt: GoodsReceipt) -> ReceiptData:
    return ReceiptData(
        id=receipt.id,
        receipt_no=receipt.receipt_no,
        order_id=receipt.order_id,
        order_no=receipt.order.order_no if receipt.order else "",
        supplier_id=receipt.supplier_id,
        supplier_name=receipt.supplier.name if receipt.supplier else "",
        receipt_date=receipt.receipt_date,
        status=receipt.status,
        total_quantity=receipt.total_quantity,
        total_amount=receipt.total_amount,
        remark=receipt.remark,
        lines=[_line_data(line) for line in receipt.lines],
        created_at=receipt.created_at,
    )


async def list_receipts(session: AsyncSession, order_id: str | None = None) -> list[ReceiptData]:
    statement = (
        select(GoodsReceipt)
        .options(
            selectinload(GoodsReceipt.lines),
            selectinload(GoodsReceipt.order),
            selectinload(GoodsReceipt.supplier),
        )
        .order_by(GoodsReceipt.created_at.desc())
    )
    if order_id:
        try:
            statement = statement.where(GoodsReceipt.order_id == uuid.UUID(order_id))
        except ValueError as exc:
            raise NotFoundError("无效的采购订单 ID。") from exc
    rows = (await session.execute(statement)).scalars().unique()
    return [_to_data(receipt) for receipt in rows]


async def get_receipt(session: AsyncSession, receipt_id: str) -> ReceiptData:
    try:
        key = uuid.UUID(receipt_id)
    except ValueError as exc:
        raise NotFoundError("无效的收货单 ID。") from exc
    receipt = await session.get(
        GoodsReceipt,
        key,
        options=(
            selectinload(GoodsReceipt.lines),
            selectinload(GoodsReceipt.order),
            selectinload(GoodsReceipt.supplier),
        ),
    )
    if receipt is None:
        raise NotFoundError("收货单不存在。")
    return _to_data(receipt)


async def create_receipt(
    session: AsyncSession,
    *,
    receipt_no: str,
    order_id: str,
    receipt_date: date,
    lines: list[dict],
    remark: str | None,
) -> ReceiptData:
    try:
        order_key = uuid.UUID(order_id)
    except ValueError as exc:
        raise NotFoundError("无效的采购订单 ID。") from exc

    # 锁定订单行，防止并发收货导致超量。
    order = await session.get(
        PurchaseOrder,
        order_key,
        with_for_update=True,
        options=(selectinload(PurchaseOrder.lines), selectinload(PurchaseOrder.supplier)),
    )
    if order is None:
        raise NotFoundError("采购订单不存在。")
    if order.status == ORDER_CANCELLED:
        raise BusinessError("订单已取消，不能收货。")
    if order.status == ORDER_DRAFT:
        raise BusinessError("订单尚未提交，不能收货。")

    # 锁定订单明细行，并在事务内校验数量。
    line_ids = [str(line["order_line_id"]) for line in lines]
    order_lines: dict[str, PurchaseOrderLine] = {}
    for line_id in line_ids:
        try:
            key = uuid.UUID(line_id)
        except ValueError as exc:
            raise NotFoundError(f"无效的订单明细 ID：{line_id}。") from exc
        line = await session.get(PurchaseOrderLine, key, with_for_update=True)
        if line is None:
            raise NotFoundError(f"订单明细 {line_id} 不存在。")
        if line.order_id != order_key:
            raise BusinessError(f"订单明细 {line_id} 不属于订单 {order.order_no}。")
        order_lines[line_id] = line

    # 检查重复明细（同一收货单对同一订单明细只收一次）。
    if len(set(line_ids)) != len(line_ids):
        raise BusinessError("收货明细中存在重复的订单明细行。")

    receipt = GoodsReceipt(
        receipt_no=receipt_no.strip(),
        order_id=order_key,
        supplier_id=order.supplier_id,
        order=order,
        supplier=order.supplier,
        receipt_date=receipt_date,
        status="posted",
        remark=remark,
    )
    session.add(receipt)

    amount_list: list[Decimal] = []
    qty_list: list[Decimal] = []
    for index, line_in in enumerate(lines, start=1):
        line_id = str(line_in["order_line_id"])
        order_line = order_lines[line_id]
        quantity = line_in["quantity"]
        # 数量约束：本次收货 + 已收 <= 订单数量。
        if quantity + order_line.received_qty > order_line.quantity:
            raise BusinessError(
                f"订单明细「{order_line.item_name}」收货数量超限："
                f"可收 {order_line.quantity - order_line.received_qty}，"
                f"本次 {quantity}。"
            )
        amount = line_amount(quantity, order_line.unit_price)
        amount_list.append(amount)
        qty_list.append(quantity)

        receipt.lines.append(
            GoodsReceiptLine(
                line_no=index,
                order_line_id=order_line.id,
                quantity=quantity,
                unit_price=order_line.unit_price,
                amount=amount,
            )
        )
        order_line.received_qty = order_line.received_qty + quantity

    receipt.total_quantity = total_amount(qty_list)
    receipt.total_amount = total_amount(amount_list)

    # 订单状态联动。
    all_received = all(line.received_qty >= line.quantity for line in order.lines)
    order.status = ORDER_RECEIVED if all_received else ORDER_PARTIALLY_RECEIVED

    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError(f"收货单号「{receipt_no}」已存在。") from exc

    return _to_data(receipt)
