"""采购订单业务服务。

关键规则：
- 明细金额 = 数量 × 单价（Decimal，四舍五入到分），由确定性代码计算。
- 订单总额 = 各明细金额之和。
- 已停用（blocked）供应商不能新建订单。
- 已收货订单不能取消。
- order_no 唯一约束兜底幂等。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import PurchaseOrder, PurchaseOrderLine, Supplier
from app.services.purchasing.domain import (
    ORDER_CANCELLED,
    ORDER_DRAFT,
    ORDER_RECEIVED,
    ORDER_SUBMITTED,
    SUPPLIER_BLOCKED,
    BusinessError,
    ConflictError,
    NotFoundError,
    line_amount,
    money,
    total_amount,
)


@dataclass
class OrderLineData:
    id: uuid.UUID
    line_no: int
    item_code: str
    item_name: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    tax_rate: Decimal
    amount: Decimal
    received_qty: Decimal
    invoiced_qty: Decimal


@dataclass
class OrderData:
    id: uuid.UUID
    order_no: str
    supplier_id: uuid.UUID
    supplier_name: str
    order_date: date
    status: str
    currency: str
    total_amount: Decimal
    remark: str | None
    lines: list[OrderLineData]
    created_at: datetime
    updated_at: datetime


def _line_data(line: PurchaseOrderLine) -> OrderLineData:
    return OrderLineData(
        id=line.id,
        line_no=line.line_no,
        item_code=line.item_code,
        item_name=line.item_name,
        quantity=line.quantity,
        unit=line.unit,
        unit_price=line.unit_price,
        tax_rate=line.tax_rate,
        amount=line.amount,
        received_qty=line.received_qty,
        invoiced_qty=line.invoiced_qty,
    )


def _to_data(order: PurchaseOrder, supplier_name: str = "") -> OrderData:
    return OrderData(
        id=order.id,
        order_no=order.order_no,
        supplier_id=order.supplier_id,
        supplier_name=supplier_name or (order.supplier.name if order.supplier else ""),
        order_date=order.order_date,
        status=order.status,
        currency=order.currency,
        total_amount=order.total_amount,
        remark=order.remark,
        lines=[_line_data(line) for line in order.lines],
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


_ORDER_OPTIONS = (
    selectinload(PurchaseOrder.lines),
    selectinload(PurchaseOrder.supplier),
)


async def list_orders(
    session: AsyncSession,
    status: str | None = None,
    supplier_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[OrderData], int]:
    """分页列出订单，返回 (订单列表, 总数)。避免大规模数据下全量加载。"""
    filters = []
    if status:
        filters.append(PurchaseOrder.status == status)
    if supplier_id:
        try:
            filters.append(PurchaseOrder.supplier_id == uuid.UUID(supplier_id))
        except ValueError as exc:
            raise NotFoundError("无效的供应商 ID。") from exc

    total = await session.scalar(
        select(func.count()).select_from(PurchaseOrder).where(*filters)
    )

    statement = (
        select(PurchaseOrder)
        .options(*_ORDER_OPTIONS)
        .where(*filters)
        .order_by(PurchaseOrder.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(statement)).scalars().unique()
    return [_to_data(order) for order in rows], int(total or 0)


async def get_order(session: AsyncSession, order_id: str) -> OrderData:
    try:
        key = uuid.UUID(order_id)
    except ValueError as exc:
        raise NotFoundError("无效的采购订单 ID。") from exc
    order = await session.get(PurchaseOrder, key, options=_ORDER_OPTIONS)
    if order is None:
        raise NotFoundError("采购订单不存在。")
    return _to_data(order)


async def create_order(
    session: AsyncSession,
    *,
    order_no: str,
    supplier_id: str,
    order_date: date,
    lines: list[dict],
    remark: str | None,
) -> OrderData:
    try:
        supplier_key = uuid.UUID(supplier_id)
    except ValueError as exc:
        raise NotFoundError("无效的供应商 ID。") from exc

    supplier = await session.get(Supplier, supplier_key)
    if supplier is None:
        raise NotFoundError("供应商不存在。")
    if supplier.status == SUPPLIER_BLOCKED:
        raise BusinessError("该供应商已停用，不能创建采购订单。")

    order = PurchaseOrder(
        order_no=order_no.strip(),
        supplier_id=supplier_key,
        supplier=supplier,
        order_date=order_date,
        status=ORDER_DRAFT,
        currency="CNY",
        remark=remark,
    )
    session.add(order)

    amount_list: list[Decimal] = []
    for index, line_in in enumerate(lines, start=1):
        quantity = line_in["quantity"]
        unit_price = line_in["unit_price"]
        amount = line_amount(quantity, unit_price)
        amount_list.append(amount)
        order.lines.append(
            PurchaseOrderLine(
                line_no=index,
                item_code=line_in["item_code"].strip(),
                item_name=line_in["item_name"].strip(),
                quantity=quantity,
                unit=line_in.get("unit") or "件",
                unit_price=unit_price,
                tax_rate=line_in.get("tax_rate") or Decimal("0"),
                amount=amount,
            )
        )

    order.total_amount = total_amount(amount_list)
    order.status = ORDER_SUBMITTED  # 创建即提交（G1 简化，明细齐全即可收货）

    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError(f"采购订单号「{order_no}」已存在。") from exc

    return _to_data(order)


async def cancel_order(session: AsyncSession, order_id: str) -> OrderData:
    try:
        key = uuid.UUID(order_id)
    except ValueError as exc:
        raise NotFoundError("无效的采购订单 ID。") from exc
    order = await session.get(PurchaseOrder, key, options=_ORDER_OPTIONS)
    if order is None:
        raise NotFoundError("采购订单不存在。")

    if order.status == ORDER_CANCELLED:
        raise BusinessError("订单已取消。")
    if order.status == ORDER_RECEIVED:
        raise BusinessError("订单已全部收货，不能取消。")
    if any(line.received_qty > 0 for line in order.lines):
        raise BusinessError("订单已有收货记录，不能取消。")

    order.status = ORDER_CANCELLED
    await session.flush()
    return _to_data(order)
