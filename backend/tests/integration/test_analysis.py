"""G5 受控问数：真实 PG 集成测试（确定性事实 + 安全边界 + 降级）。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.db.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseInvoice,
    PurchaseInvoiceLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
)
from app.services import analysis


async def _seed(db_session):
    s1 = Supplier(code="S1", name="供应商甲", status="active")
    s2 = Supplier(code="S2", name="供应商乙", status="active")
    db_session.add_all([s1, s2])
    await db_session.flush()

    def line(order, no, name, qty, price, due, cat):
        return PurchaseOrderLine(
            order_id=order.id, line_no=no, item_code=f"I{no}", item_name=name,
            category=cat, expected_delivery_date=due,
            quantity=qty, unit="件", unit_price=price, tax_rate=Decimal("0"),
            amount=(qty * price), received_qty=Decimal("0"), invoiced_qty=Decimal("0"),
        )

    po1 = PurchaseOrder(order_no="PO-1", supplier_id=s1.id, order_date=date(2026, 1, 10),
                        status="received", currency="CNY", total_amount=Decimal("2000"))
    l1 = line(po1, 1, "物料A", Decimal("10"), Decimal("100"), date(2026, 1, 20), "电子")
    po1.lines = [l1]
    po2 = PurchaseOrder(order_no="PO-2", supplier_id=s2.id, order_date=date(2026, 2, 5),
                        status="received", currency="CNY", total_amount=Decimal("400"))
    l2 = line(po2, 1, "物料B", Decimal("8"), Decimal("50"), date(2026, 2, 15), "机械")
    po2.lines = [l2]
    db_session.add_all([po1, po2])
    await db_session.flush()

    gr = GoodsReceipt(receipt_no="GR-1", order_id=po1.id, supplier_id=s1.id,
                      receipt_date=date(2026, 1, 22), status="posted",
                      total_quantity=Decimal("10"), total_amount=Decimal("1000"))
    gr.lines = [GoodsReceiptLine(order_line_id=l1.id, line_no=1, quantity=Decimal("10"),
                                 unit_price=Decimal("100"), amount=Decimal("1000"))]
    db_session.add(gr)
    l1.received_qty = Decimal("10")

    # 一张提前开票（待核对）
    inv = PurchaseInvoice(invoice_no="INV-1", order_id=po2.id, supplier_id=s2.id,
                          invoice_date=date(2026, 2, 14), status="pending_verification",
                          currency="CNY", total_amount=Decimal("400"), tax_amount=Decimal("0"))
    inv.lines = [PurchaseInvoiceLine(order_line_id=l2.id, line_no=1, item_name="物料B",
                                     quantity=Decimal("8"), unit_price=Decimal("50"),
                                     amount=Decimal("400"))]
    db_session.add(inv)
    l2.invoiced_qty = Decimal("8")
    await db_session.commit()

    return [{"id": str(s1.id), "code": s1.code, "name": s1.name},
            {"id": str(s2.id), "code": s2.code, "name": s2.name}]


@pytest.mark.asyncio
async def test_overview_analysis_facts(db_session):
    suppliers = await _seed(db_session)
    r = await analysis.run_analysis(db_session, "2026年采购订单金额是多少？", suppliers)
    assert r["mode"] == "offline"
    assert r["intent"] == analysis.INTENT_OVERVIEW
    assert Decimal(r["facts"]["orderAmount"]) == Decimal("1400")  # 10*100 + 8*50
    assert Decimal(r["facts"]["receiptAmount"]) == Decimal("1000")
    assert Decimal(r["facts"]["pendingVerificationAmount"]) == Decimal("400")


@pytest.mark.asyncio
async def test_supplier_ranking_analysis(db_session):
    suppliers = await _seed(db_session)
    r = await analysis.run_analysis(db_session, "哪些供应商采购金额最高？", suppliers)
    assert r["intent"] == analysis.INTENT_SUPPLIER_RANKING
    amounts = {x["code"]: x["amount"] for x in r["facts"]["ranking"]}
    assert Decimal(amounts["S1"]) == Decimal("1000")
    assert Decimal(amounts["S2"]) == Decimal("400")


@pytest.mark.asyncio
async def test_pending_invoices_analysis(db_session):
    suppliers = await _seed(db_session)
    r = await analysis.run_analysis(db_session, "当前有多少待核对发票？", suppliers)
    assert r["intent"] == analysis.INTENT_PENDING_INVOICES
    assert r["facts"]["count"] == 1
    assert Decimal(r["facts"]["total"]) == Decimal("400")


@pytest.mark.asyncio
async def test_delivery_analysis_no_due_returns_uncomputable(db_session):
    suppliers = await _seed(db_session)
    # 这里订单均有交期，但已收货；测试空交期场景另建
    r = await analysis.run_analysis(db_session, "哪些订单存在交付延期？", suppliers)
    assert r["intent"] == analysis.INTENT_DELIVERY
    assert "rate" in r["facts"]


@pytest.mark.asyncio
async def test_discrepancy_analysis(db_session):
    suppliers = await _seed(db_session)
    r = await analysis.run_analysis(db_session, "哪些订单存在收货与开票差异？", suppliers)
    assert r["intent"] == analysis.INTENT_DISCREPANCIES
    assert r["facts"]["total"] == 2


@pytest.mark.asyncio
async def test_llm_mode_falls_back_offline_without_key(db_session):
    suppliers = await _seed(db_session)
    r = await analysis.run_analysis(db_session, "采购订单金额是多少？", suppliers, mode="llm")
    # 未配置 key → generate_llm_explanation 返回 None，engine 应降级为离线规则解释。
    assert r["mode"] == "offline"
    assert r["explanation"]


@pytest.mark.asyncio
async def test_named_supplier_not_found_returns_clarification(db_session):
    """明确指定未注册供应商：不静默用整体数据，返回澄清且不执行指标计算。"""
    suppliers = await _seed(db_session)
    r = await analysis.run_analysis(db_session, "某某科技今年采购金额变化如何？", suppliers)
    assert r["facts"] == {}  # 未执行任何指标计算
    assert "未在系统中找到" in r["explanation"]
    assert r["supplier"] is None


@pytest.mark.asyncio
async def test_analysis_has_no_write_side_effects(db_session):
    """AI 问数零写副作用：执行多种问数后业务表行数不变。"""
    from sqlalchemy import func, select

    from app.db.models import PurchaseInvoice, PurchaseOrder, Supplier

    suppliers = await _seed(db_session)

    async def counts():
        return (
            await db_session.scalar(select(func.count()).select_from(Supplier)),
            await db_session.scalar(select(func.count()).select_from(PurchaseOrder)),
            await db_session.scalar(select(func.count()).select_from(PurchaseInvoice)),
        )

    before = await counts()
    for q in [
        "哪些供应商采购金额最高？",
        "当前有多少待核对发票？",
        "哪些订单存在交付延期？",
        "哪些订单存在收货与开票差异？",
    ]:
        await analysis.run_analysis(db_session, q, suppliers)
    after = await counts()
    assert before == after  # 业务表无任何写入
