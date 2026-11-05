"""采购业务服务层集成测试（真实 PostgreSQL）。

覆盖 G1 核心业务规则：
- 供应商创建与唯一编码。
- 订单创建、明细金额计算、订单总额。
- 已停用供应商不能建单。
- 部分收货、超量收货拒绝、收货后订单状态联动。
- 已取消订单不能收货。
- 发票追溯订单明细、开票数量约束。
- 完整业务闭环（供应商 -> 订单 -> 收货 -> 发票）。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.purchasing import invoices, orders, receipts, suppliers
from app.services.purchasing.domain import (
    BusinessError,
    ConflictError,
    ORDER_PARTIALLY_RECEIVED,
    ORDER_RECEIVED,
    SUPPLIER_BLOCKED,
)


async def _make_supplier(db_session, code="S001", name="供应商甲", **kw):
    defaults = dict(
        contact_name=None, contact_phone=None, email=None, address=None, remark=None
    )
    defaults.update(kw)
    return await suppliers.create_supplier(db_session, code=code, name=name, **defaults)


async def _make_order(db_session, supplier_id, order_no="PO-001", lines=None, **kw):
    return await orders.create_order(
        db_session,
        order_no=order_no,
        supplier_id=supplier_id,
        order_date=date(2026, 1, 1),
        lines=lines
        or [
            {"item_code": "A", "item_name": "物料A", "quantity": Decimal("10"), "unit_price": Decimal("100"), "tax_rate": Decimal("0")},
            {"item_code": "B", "item_name": "物料B", "quantity": Decimal("5"), "unit_price": Decimal("200"), "tax_rate": Decimal("0")},
        ],
        remark=kw.get("remark"),
    )


# ---------- 供应商 ----------


@pytest.mark.asyncio
async def test_create_supplier(db_session):
    data = await _make_supplier(db_session)
    assert data.code == "S001"
    assert data.status == "active"


@pytest.mark.asyncio
async def test_duplicate_supplier_code_conflict(db_session):
    await _make_supplier(db_session, code="DUP")
    with pytest.raises(ConflictError):
        await _make_supplier(db_session, code="DUP", name="另一个")


# ---------- 订单 ----------


@pytest.mark.asyncio
async def test_create_order_computes_line_and_total_amount(db_session):
    sup = await _make_supplier(db_session)
    order = await _make_order(db_session, str(sup.id))
    # 10×100 + 5×200 = 2000
    assert order.total_amount == Decimal("2000.00")
    assert order.lines[0].amount == Decimal("1000.00")
    assert order.lines[1].amount == Decimal("1000.00")
    assert order.status == "submitted"


@pytest.mark.asyncio
async def test_blocked_supplier_cannot_create_order(db_session):
    sup = await _make_supplier(db_session, code="BLK")
    await suppliers.update_supplier(db_session, str(sup.id), status=SUPPLIER_BLOCKED)
    with pytest.raises(BusinessError, match="停用"):
        await _make_order(db_session, str(sup.id), order_no="PO-BLK")


@pytest.mark.asyncio
async def test_duplicate_order_no_conflict(db_session):
    sup = await _make_supplier(db_session)
    await _make_order(db_session, str(sup.id), order_no="PO-DUP")
    with pytest.raises(ConflictError):
        await _make_order(db_session, str(sup.id), order_no="PO-DUP")


# ---------- 收货 ----------


@pytest.mark.asyncio
async def test_partial_receipt_updates_order_status(db_session):
    sup = await _make_supplier(db_session)
    order = await _make_order(db_session, str(sup.id))
    line = order.lines[0]

    receipt = await receipts.create_receipt(
        db_session,
        receipt_no="GR-001",
        order_id=str(order.id),
        receipt_date=date(2026, 1, 5),
        lines=[{"order_line_id": str(line.id), "quantity": Decimal("3")}],
        remark=None,
    )
    assert receipt.status == "posted"
    assert receipt.total_quantity == Decimal("3.000")
    assert receipt.total_amount == Decimal("300.00")

    updated = await orders.get_order(db_session, str(order.id))
    assert updated.status == ORDER_PARTIALLY_RECEIVED
    assert updated.lines[0].received_qty == Decimal("3")


@pytest.mark.asyncio
async def test_full_receipt_marks_order_received(db_session):
    sup = await _make_supplier(db_session)
    order = await _make_order(db_session, str(sup.id))

    # 分两次收满第一条明细（10 件）
    line = order.lines[0]
    await receipts.create_receipt(
        db_session, receipt_no="GR-A", order_id=str(order.id),
        receipt_date=date(2026, 1, 5),
        lines=[{"order_line_id": str(line.id), "quantity": Decimal("6")}], remark=None,
    )
    await receipts.create_receipt(
        db_session, receipt_no="GR-B", order_id=str(order.id),
        receipt_date=date(2026, 1, 6),
        lines=[
            {"order_line_id": str(line.id), "quantity": Decimal("4")},
            {"order_line_id": str(order.lines[1].id), "quantity": Decimal("5")},
        ],
        remark=None,
    )
    updated = await orders.get_order(db_session, str(order.id))
    assert updated.status == ORDER_RECEIVED


@pytest.mark.asyncio
async def test_over_receipt_is_rejected(db_session):
    sup = await _make_supplier(db_session)
    order = await _make_order(db_session, str(sup.id))
    line = order.lines[0]  # 数量 10

    with pytest.raises(BusinessError, match="超限"):
        await receipts.create_receipt(
            db_session, receipt_no="GR-OVER", order_id=str(order.id),
            receipt_date=date(2026, 1, 5),
            lines=[{"order_line_id": str(line.id), "quantity": Decimal("11")}], remark=None,
        )

    # 确认数据库状态未被非法修改
    updated = await orders.get_order(db_session, str(order.id))
    assert updated.lines[0].received_qty == Decimal("0")
    assert updated.status == "submitted"


@pytest.mark.asyncio
async def test_cancelled_order_cannot_receive(db_session):
    sup = await _make_supplier(db_session)
    order = await _make_order(db_session, str(sup.id))
    await orders.cancel_order(db_session, str(order.id))

    with pytest.raises(BusinessError, match="取消"):
        await receipts.create_receipt(
            db_session, receipt_no="GR-CX", order_id=str(order.id),
            receipt_date=date(2026, 1, 5),
            lines=[{"order_line_id": str(order.lines[0].id), "quantity": Decimal("1")}],
            remark=None,
        )


@pytest.mark.asyncio
async def test_received_order_cannot_cancel(db_session):
    sup = await _make_supplier(db_session)
    order = await _make_order(db_session, str(sup.id))
    await receipts.create_receipt(
        db_session, receipt_no="GR-R", order_id=str(order.id),
        receipt_date=date(2026, 1, 5),
        lines=[{"order_line_id": str(order.lines[0].id), "quantity": Decimal("1")}],
        remark=None,
    )
    with pytest.raises(BusinessError, match="收货"):
        await orders.cancel_order(db_session, str(order.id))


# ---------- 发票 ----------


@pytest.mark.asyncio
async def test_invoice_traces_order_line(db_session):
    sup = await _make_supplier(db_session)
    order = await _make_order(db_session, str(sup.id))
    line = order.lines[0]

    inv = await invoices.create_invoice(
        db_session,
        invoice_no="INV-001",
        order_id=str(order.id),
        supplier_id=str(sup.id),
        invoice_date=date(2026, 1, 10),
        lines=[{
            "order_line_id": str(line.id),
            "item_name": line.item_name,
            "quantity": Decimal("10"),
            "unit_price": Decimal("100"),
            "tax_rate": Decimal("0.13"),
        }],
        remark=None,
    )
    assert inv.total_amount == Decimal("1000.00")
    assert inv.tax_amount == Decimal("130.00")  # 1000 × 13%
    assert inv.lines[0].order_line_id is not None


@pytest.mark.asyncio
async def test_invoice_over_quantity_is_rejected(db_session):
    sup = await _make_supplier(db_session)
    order = await _make_order(db_session, str(sup.id))
    line = order.lines[0]  # 数量 10

    with pytest.raises(BusinessError, match="超限"):
        await invoices.create_invoice(
            db_session,
            invoice_no="INV-OVER",
            order_id=str(order.id),
            supplier_id=str(sup.id),
            invoice_date=date(2026, 1, 10),
            lines=[{
                "order_line_id": str(line.id),
                "item_name": line.item_name,
                "quantity": Decimal("11"),
                "unit_price": Decimal("100"),
                "tax_rate": Decimal("0"),
            }],
            remark=None,
        )


# ---------- 完整业务闭环 ----------


@pytest.mark.asyncio
async def test_full_procurement_flow(db_session):
    """供应商 -> 订单(2明细) -> 部分收货 -> 发票，验证关联与状态。"""
    sup = await _make_supplier(db_session, code="FLOW", name="闭环供应商")

    order = await orders.create_order(
        db_session,
        order_no="PO-FLOW",
        supplier_id=str(sup.id),
        order_date=date(2026, 1, 1),
        lines=[
            {"item_code": "A", "item_name": "物料A", "quantity": Decimal("10"), "unit_price": Decimal("100"), "tax_rate": Decimal("0")},
            {"item_code": "B", "item_name": "物料B", "quantity": Decimal("5"), "unit_price": Decimal("200"), "tax_rate": Decimal("0")},
        ],
        remark=None,
    )
    assert order.total_amount == Decimal("2000.00")

    # 对第一条明细部分收货 4 件
    receipt = await receipts.create_receipt(
        db_session, receipt_no="GR-FLOW", order_id=str(order.id),
        receipt_date=date(2026, 1, 5),
        lines=[{"order_line_id": str(order.lines[0].id), "quantity": Decimal("4")}],
        remark=None,
    )
    assert receipt.total_amount == Decimal("400.00")

    # 录入发票，追溯订单明细
    invoice = await invoices.create_invoice(
        db_session, invoice_no="INV-FLOW", order_id=str(order.id),
        supplier_id=str(sup.id), invoice_date=date(2026, 1, 10),
        lines=[{
            "order_line_id": str(order.lines[0].id),
            "item_name": "物料A",
            "quantity": Decimal("10"),
            "unit_price": Decimal("100"),
            "tax_rate": Decimal("0"),
        }],
        remark=None,
    )
    assert invoice.total_amount == Decimal("1000.00")

    # 校验订单状态与累计数量
    updated = await orders.get_order(db_session, str(order.id))
    assert updated.status == ORDER_PARTIALLY_RECEIVED
    assert updated.lines[0].received_qty == Decimal("4")
    assert updated.lines[0].invoiced_qty == Decimal("10")

    # 收货单与发票都能追溯到订单
    receipt_list = await receipts.list_receipts(db_session, str(order.id))
    invoice_list = await invoices.list_invoices(db_session, str(order.id))
    assert len(receipt_list) == 1
    assert len(invoice_list) == 1


# ---------- 提前开票 / 幂等（G1.1 新增）----------


@pytest.mark.asyncio
async def test_pre_invoice_marks_pending_verification(db_session):
    """提前开票（开票数量 > 已收货数量）应标记为待核对，而非直接认定匹配。"""
    from app.services.purchasing.idempotency import request_fingerprint, resolve_idempotency

    sup = await _make_supplier(db_session, code="PRE", name="提前开票")
    order = await _make_order(db_session, str(sup.id), order_no="PO-PRE")
    line = order.lines[0]  # 数量 10，未收货

    inv = await invoices.create_invoice(
        db_session,
        invoice_no="INV-PRE",
        order_id=str(order.id),
        supplier_id=str(sup.id),
        invoice_date=date(2026, 1, 10),
        lines=[{
            "order_line_id": str(line.id),
            "item_name": line.item_name,
            "quantity": Decimal("10"),
            "unit_price": Decimal("100"),
            "tax_rate": Decimal("0"),
        }],
        remark=None,
    )
    assert inv.status == "pending_verification"


@pytest.mark.asyncio
async def test_invoice_after_receipt_is_posted(db_session):
    """已收货后再开票（开票数量 <= 已收货数量）应为 posted。"""
    sup = await _make_supplier(db_session, code="POST", name="已收货")
    order = await _make_order(db_session, str(sup.id), order_no="PO-POST")
    line = order.lines[0]  # 数量 10

    await receipts.create_receipt(
        db_session, receipt_no="GR-POST", order_id=str(order.id),
        receipt_date=date(2026, 1, 5),
        lines=[{"order_line_id": str(line.id), "quantity": Decimal("10")}], remark=None,
    )

    inv = await invoices.create_invoice(
        db_session,
        invoice_no="INV-POST",
        order_id=str(order.id),
        supplier_id=str(sup.id),
        invoice_date=date(2026, 1, 10),
        lines=[{
            "order_line_id": str(line.id),
            "item_name": line.item_name,
            "quantity": Decimal("10"),
            "unit_price": Decimal("100"),
            "tax_rate": Decimal("0"),
        }],
        remark=None,
    )
    assert inv.status == "posted"


@pytest.mark.asyncio
async def test_idempotency_returns_same_resource(db_session):
    """Idempotency-Key：同 key 同内容重试返回原资源，不重复创建。"""
    from app.db.models import IdempotencyKey
    from app.services.purchasing.idempotency import (
        record_idempotency,
        request_fingerprint,
        resolve_idempotency,
    )

    key = "idem-test-001"
    payload = {"code": "IDEM", "name": "幂等供应商"}
    fingerprint = request_fingerprint(payload)

    # 第一次：未命中，执行业务并记录
    first = await resolve_idempotency(db_session, key, "supplier", fingerprint)
    assert first is None
    sup = await _make_supplier(db_session, code="IDEM", name="幂等供应商")
    await record_idempotency(db_session, key, "supplier", str(sup.id), fingerprint)

    # 第二次：命中，返回原资源
    second = await resolve_idempotency(db_session, key, "supplier", fingerprint)
    assert second == str(sup.id)

    # 同 key 不同内容：409
    other_fingerprint = request_fingerprint({"code": "IDEM", "name": "不同内容"})
    with pytest.raises(Exception) as exc_info:
        await resolve_idempotency(db_session, key, "supplier", other_fingerprint)
    assert "不同的请求内容" in str(exc_info.value)
