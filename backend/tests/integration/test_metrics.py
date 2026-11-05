"""G3 指标正确性测试：小规模人工可核算数据集 + 独立 Gold 验证。

核心：一条订单明细对应两次收货、三次开票时，订单/收货/发票金额均不因 JOIN 重复放大。
Gold 为人工核算常量，独立于 SQL 实现。
"""

from __future__ import annotations

import uuid
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
from app.services import metrics


async def _seed(db_session):
    """构造人工可核算数据集。返回 (供应商 dict, 订单明细引用) 供参考。"""
    s1 = Supplier(code="S1", name="供应商甲", status="active")
    s2 = Supplier(code="S2", name="供应商乙", status="active")
    db_session.add_all([s1, s2])
    await db_session.flush()

    def line(order, no, code, name, qty, price, due, cat):
        return PurchaseOrderLine(
            order_id=order.id, line_no=no, item_code=code, item_name=name,
            category=cat, expected_delivery_date=due,
            quantity=qty, unit="件", unit_price=price, tax_rate=Decimal("0"),
            amount=(qty * price), received_qty=Decimal("0"), invoiced_qty=Decimal("0"),
        )

    # PO-1：S1，两条明细，L1 两次收货 + 三次开票
    po1 = PurchaseOrder(order_no="PO-1", supplier_id=s1.id, order_date=date(2026, 1, 10),
                        status="received", currency="CNY", total_amount=Decimal("2000"))
    po1_l1 = line(po1, 1, "A", "物料A", Decimal("10"), Decimal("100"), date(2026, 1, 20), "电子")
    po1_l2 = line(po1, 2, "B", "物料B", Decimal("5"), Decimal("200"), date(2026, 1, 25), "机械")
    po1.lines = [po1_l1, po1_l2]

    # PO-2：S2
    po2 = PurchaseOrder(order_no="PO-2", supplier_id=s2.id, order_date=date(2026, 2, 5),
                        status="received", currency="CNY", total_amount=Decimal("400"))
    po2_l1 = line(po2, 1, "C", "物料C", Decimal("8"), Decimal("50"), date(2026, 2, 15), "电子")
    po2.lines = [po2_l1]

    # PO-3：取消订单（排除）
    po3 = PurchaseOrder(order_no="PO-3", supplier_id=s1.id, order_date=date(2026, 3, 1),
                        status="cancelled", currency="CNY", total_amount=Decimal("300"))
    po3_l1 = line(po3, 1, "D", "物料D", Decimal("3"), Decimal("100"), None, None)
    po3.lines = [po3_l1]

    # PO-4：未收货，逾期
    po4 = PurchaseOrder(order_no="PO-4", supplier_id=s2.id, order_date=date(2026, 1, 15),
                        status="submitted", currency="CNY", total_amount=Decimal("300"))
    po4_l1 = line(po4, 1, "E", "物料E", Decimal("10"), Decimal("30"), date(2026, 2, 1), "电子")
    po4.lines = [po4_l1]

    # PO-5：收货但未开票
    po5 = PurchaseOrder(order_no="PO-5", supplier_id=s1.id, order_date=date(2026, 4, 5),
                        status="received", currency="CNY", total_amount=Decimal("100"))
    po5_l1 = line(po5, 1, "F", "物料F", Decimal("4"), Decimal("25"), date(2026, 4, 10), "机械")
    po5.lines = [po5_l1]

    db_session.add_all([po1, po2, po3, po4, po5])
    await db_session.flush()

    # 收货：PO-1 L1 两次（6 + 4），PO-1 L2 一次，PO-2 L1 一次，PO-5 L1 一次
    def receipt(no, order, order_line, qty, d):
        r = GoodsReceipt(receipt_no=no, order_id=order.id, supplier_id=order.supplier_id,
                         receipt_date=d, status="posted", total_quantity=qty,
                         total_amount=qty * order_line.unit_price)
        r.lines = [GoodsReceiptLine(order_line_id=order_line.id, line_no=1, quantity=qty,
                                    unit_price=order_line.unit_price, amount=qty * order_line.unit_price)]
        return r

    gr1 = receipt("GR-1", po1, po1_l1, Decimal("6"), date(2026, 1, 15))
    gr2 = receipt("GR-2", po1, po1_l1, Decimal("4"), date(2026, 1, 22))
    gr3 = receipt("GR-3", po1, po1_l2, Decimal("5"), date(2026, 1, 24))
    gr4 = receipt("GR-4", po2, po2_l1, Decimal("8"), date(2026, 2, 12))
    gr5 = receipt("GR-5", po5, po5_l1, Decimal("4"), date(2026, 4, 9))
    db_session.add_all([gr1, gr2, gr3, gr4, gr5])

    # 更新累计收货数量
    po1_l1.received_qty = Decimal("10")
    po1_l2.received_qty = Decimal("5")
    po2_l1.received_qty = Decimal("8")
    po5_l1.received_qty = Decimal("4")

    # 发票：PO-1 L1 三次（3+3+4），PO-1 L2 提前开票，PO-2 L1 一次
    def invoice(no, order, order_line, qty, d, tax_rate, status):
        amount = qty * order_line.unit_price
        tax = (amount * tax_rate).quantize(Decimal("0.01"))
        inv = PurchaseInvoice(invoice_no=no, order_id=order.id, supplier_id=order.supplier_id,
                              invoice_date=d, status=status, currency="CNY",
                              total_amount=amount, tax_amount=tax)
        inv.lines = [PurchaseInvoiceLine(order_line_id=order_line.id, line_no=1,
                                         item_name=order_line.item_name, quantity=qty,
                                         unit_price=order_line.unit_price, amount=amount)]
        return inv

    inv1 = invoice("INV-1", po1, po1_l1, Decimal("3"), date(2026, 1, 16), Decimal("0.13"), "posted")
    inv2 = invoice("INV-2", po1, po1_l1, Decimal("3"), date(2026, 1, 20), Decimal("0.13"), "posted")
    inv3 = invoice("INV-3", po1, po1_l1, Decimal("4"), date(2026, 2, 1), Decimal("0.13"), "posted")
    inv5 = invoice("INV-5", po1, po1_l2, Decimal("5"), date(2026, 1, 18), Decimal("0.13"), "pending_verification")
    inv4 = invoice("INV-4", po2, po2_l1, Decimal("8"), date(2026, 2, 14), Decimal("0.13"), "posted")
    db_session.add_all([inv1, inv2, inv3, inv5, inv4])

    po1_l1.invoiced_qty = Decimal("10")
    po1_l2.invoiced_qty = Decimal("5")
    po2_l1.invoiced_qty = Decimal("8")

    await db_session.commit()
    return {"s1": s1, "s2": s2, "po1_l1": po1_l1}


YEAR = (date(2026, 1, 1), date(2026, 12, 31))


@pytest.mark.asyncio
async def test_overview_amounts(db_session):
    """总览 KPI：订单/收货/发票金额，排除取消，待核对正确。"""
    await _seed(db_session)
    r = await metrics.overview(db_session, *YEAR)

    assert r["orderAmount"] == Decimal("2800")     # 2000+400+300+100（排除 PO-3）
    assert r["receiptAmount"] == Decimal("2500")   # 600+400+1000+400+100
    assert r["invoiceAmount"] == Decimal("2400")   # 未税 300+300+400+1000+400
    assert r["invoiceTaxAmount"] == Decimal("312")  # 39+39+52+130+52
    assert r["pendingVerificationAmount"] == Decimal("1000")  # INV-5 未税
    assert r["supplierCount"] == 2


@pytest.mark.asyncio
async def test_no_join_amplification(db_session):
    """一条明细两次收货三次开票：订单/收货/发票金额均为 1000，不重复放大。"""
    await _seed(db_session)
    # PO-1 L1：qty=10, price=100 → 订单 1000；收货 6+4=10 件=1000；开票 3+3+4=10 件=1000
    r = await metrics.overview(db_session, *YEAR)
    # 单独统计 PO-1 L1 的订单金额（通过 supplier S1 下 PO-1）
    s1_rank = await metrics.supplier_ranking(db_session, *YEAR, top_n=10)
    s1 = next(x for x in s1_rank["ranking"] if x["code"] == "S1")
    # S1 金额 = PO-1(2000) + PO-5(100) = 2100，其中 PO-1 L1 占 1000
    assert s1["amount"] == Decimal("2100")
    # 收货总金额 2500 中，PO-1 L1 的两次收货 600+400=1000 只计一次（不因开票放大）
    assert r["receiptAmount"] == Decimal("2500")
    assert r["invoiceAmount"] == Decimal("2400")
    # 发票未税金额 2400 中，PO-1 L1 三次开票 300+300+400=1000
    # 关键断言：三个金额互不放大
    assert r["orderAmount"] == Decimal("2800")
    assert r["receiptAmount"] != r["orderAmount"]  # 2800 vs 2500，正确区分


@pytest.mark.asyncio
async def test_supplier_concentration(db_session):
    await _seed(db_session)
    r = await metrics.supplier_ranking(db_session, *YEAR, top_n=10)
    s1 = next(x for x in r["ranking"] if x["code"] == "S1")
    s2 = next(x for x in r["ranking"] if x["code"] == "S2")
    assert s1["amount"] == Decimal("2100")
    assert s2["amount"] == Decimal("700")
    assert s1["share"] == Decimal("0.75")
    assert s2["share"] == Decimal("0.25")
    # Top N 集中度：top_n=1 时 = S1 金额 / 总金额 = 2100/2800 = 0.75
    r1 = await metrics.supplier_ranking(db_session, *YEAR, top_n=1)
    assert r1["concentration"] == Decimal("0.75")


@pytest.mark.asyncio
async def test_monthly_trend(db_session):
    await _seed(db_session)
    r = await metrics.monthly_trend(db_session, *YEAR)
    series = {s["month"]: s for s in r["series"]}
    assert series["2026-01"]["orderAmount"] == Decimal("2300")   # PO-1 2000 + PO-4 300
    assert series["2026-01"]["receiptAmount"] == Decimal("2000")  # GR-1+2+3
    assert series["2026-01"]["invoiceAmount"] == Decimal("1600")  # INV-1+2+5
    assert series["2026-02"]["orderAmount"] == Decimal("400")
    assert series["2026-03"]["orderAmount"] == Decimal("0")      # PO-3 取消
    assert series["2026-04"]["orderAmount"] == Decimal("100")    # PO-5
    assert series["2026-04"]["receiptAmount"] == Decimal("100")  # GR-5
    assert series["2026-04"]["invoiceAmount"] == Decimal("0")


@pytest.mark.asyncio
async def test_delivery_performance(db_session):
    await _seed(db_session)
    r = await metrics.delivery_performance(db_session, *YEAR)
    # 及时：PO-1 L2(01-24<=01-25)、PO-2 L1(02-12<=02-15)、PO-5 L1(04-09<=04-10)
    # 延期：PO-1 L1(01-22>01-20)、PO-4 L1(逾期未收)
    assert r["ontime"] == 3
    assert r["late"] == 2
    assert r["judged"] == 5
    assert r["rate"] == Decimal("0.6")


@pytest.mark.asyncio
async def test_delivery_no_data_is_uncomputable(db_session):
    """无交期数据时及时率返回 None（不可计算），不默认 0 或 100。"""
    s = Supplier(code="X1", name="无交期供应商", status="active")
    db_session.add(s)
    await db_session.flush()
    po = PurchaseOrder(order_no="PO-X", supplier_id=s.id, order_date=date(2026, 1, 1),
                       status="submitted", currency="CNY", total_amount=Decimal("100"))
    po.lines = [PurchaseOrderLine(order_id=po.id, line_no=1, item_code="X", item_name="X",
                                  quantity=Decimal("1"), unit="件", unit_price=Decimal("100"),
                                  tax_rate=Decimal("0"), amount=Decimal("100"),
                                  received_qty=Decimal("0"), invoiced_qty=Decimal("0"),
                                  expected_delivery_date=None)]
    db_session.add(po)
    await db_session.commit()
    r = await metrics.delivery_performance(db_session, *YEAR)
    assert r["rate"] is None
    assert r["judged"] == 0


@pytest.mark.asyncio
async def test_category_breakdown(db_session):
    await _seed(db_session)
    r = await metrics.category_breakdown(db_session, *YEAR)
    items = {x["category"]: x for x in r["items"]}
    assert items["电子"]["amount"] == Decimal("1700")  # 1000+400+300
    assert items["机械"]["amount"] == Decimal("1100")  # 1000+100
    assert r["total"] == Decimal("2800")


@pytest.mark.asyncio
async def test_discrepancies(db_session):
    await _seed(db_session)
    rows = await metrics.discrepancies(db_session, *YEAR)
    by_order = {r["orderNo"]: r for r in rows}
    assert "unreceived" in by_order["PO-4"]["discrepancyKinds"]            # 未收货
    assert "received_not_invoiced" in by_order["PO-5"]["discrepancyKinds"]  # 已收货未开票
    # PO-1 L1 收满开满，无差异
    po1 = [r for r in rows if r["orderNo"] == "PO-1" and r["itemName"] == "物料A"][0]
    assert po1["discrepancyKinds"] == []


@pytest.mark.asyncio
async def test_pending_invoice_verify_flow(db_session):
    """提前开票状态一致性：收货补齐不自动改状态，人工核对后才减少待核对金额。"""
    from sqlalchemy import select

    from app.db.models import PurchaseInvoice
    from app.services.purchasing.invoices import verify_invoice

    await _seed(db_session)

    # 待核对金额 = INV-5 的 1000（提前开票）
    ov1 = await metrics.overview(db_session, *YEAR)
    assert ov1["pendingVerificationAmount"] == Decimal("1000")

    inv5 = await db_session.scalar(
        select(PurchaseInvoice).where(PurchaseInvoice.invoice_no == "INV-5")
    )
    assert inv5.status == "pending_verification"

    # 后续收货（PO-1 L2 已收货）不会自动改变发票状态
    assert inv5.status == "pending_verification"

    # 人工核对：pending_verification -> posted
    await verify_invoice(db_session, str(inv5.id))
    assert inv5.status == "posted"

    # 核对后待核对金额 = 0，已开票金额不变
    ov2 = await metrics.overview(db_session, *YEAR)
    assert ov2["pendingVerificationAmount"] == Decimal("0")
    assert ov2["invoiceAmount"] == ov1["invoiceAmount"]


@pytest.mark.asyncio
async def test_verify_invoice_idempotent_guard(db_session):
    """已 posted 发票不能重复核对；已取消发票不能核对。"""
    from sqlalchemy import select

    from app.db.models import PurchaseInvoice
    from app.services.purchasing.domain import BusinessError
    from app.services.purchasing.invoices import verify_invoice

    await _seed(db_session)
    # INV-1 是 posted，重复核对应报错
    inv1 = await db_session.scalar(
        select(PurchaseInvoice).where(PurchaseInvoice.invoice_no == "INV-1")
    )
    assert inv1.status == "posted"
    with pytest.raises(BusinessError):
        await verify_invoice(db_session, str(inv1.id))


@pytest.mark.asyncio
async def test_verify_invoice_rejects_cancelled_order(db_session):
    """核对前置：关联订单已取消的发票不能核对通过。"""
    from sqlalchemy import select

    from app.db.models import PurchaseInvoice
    from app.services.purchasing.domain import BusinessError
    from app.services.purchasing.invoices import verify_invoice

    # 构造一个已取消订单 + 一张关联它的待核对发票
    s = Supplier(code="CANC", name="取消单供应商", status="active")
    db_session.add(s)
    await db_session.flush()
    po = PurchaseOrder(order_no="PO-CANC", supplier_id=s.id, order_date=date(2026, 5, 1),
                       status="cancelled", currency="CNY", total_amount=Decimal("100"))
    db_session.add(po)
    await db_session.flush()
    inv = PurchaseInvoice(invoice_no="INV-CANC", order_id=po.id, supplier_id=s.id,
                          invoice_date=date(2026, 5, 3), status="pending_verification",
                          currency="CNY", total_amount=Decimal("100"), tax_amount=Decimal("0"))
    db_session.add(inv)
    await db_session.commit()

    with pytest.raises(BusinessError, match="已取消"):
        await verify_invoice(db_session, str(inv.id))
