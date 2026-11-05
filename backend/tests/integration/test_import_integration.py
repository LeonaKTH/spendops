"""G2 真实 PostgreSQL 集成测试：数据接入、暂存、业务导入、错误隔离、部分成功。

覆盖：任务创建与字段校验、四类业务导入、关联校验、数量约束、重复单号、
部分成功、Worker 认领、重复导入不产生重复数据。
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, update

from app.db.importing import (
    IMPORT_GOODS_RECEIPT,
    IMPORT_PURCHASE_INVOICE,
    IMPORT_PURCHASE_ORDER,
    IMPORT_SUPPLIER,
    ImportStagingRow,
    ImportTask,
    ROW_ERROR,
    ROW_IMPORTED,
    ROW_VALID,
    TASK_AWAITING_CONFIRM,
    TASK_IMPORTING,
)
from app.db.models import (
    PurchaseInvoice,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
)
from app.services.importing import importer, tasks
from app.services.importing.validate import mapped_to_json


def _make_task(session, task_type: str) -> ImportTask:
    task = ImportTask(
        task_type=task_type,
        original_name="test.csv",
        file_hash=uuid.uuid4().hex,
        file_size=0,
        status=TASK_IMPORTING,
        total_rows=0,
    )
    session.add(task)
    return task


async def _make_staging(session, task, mapped: dict, row_number: int = 2) -> ImportStagingRow:
    row = ImportStagingRow(
        task_id=task.id,
        row_number=row_number,
        raw_data={},
        mapped_data=mapped_to_json(mapped),
        status=ROW_VALID,
    )
    session.add(row)
    await session.flush()
    return row


async def _make_supplier(session, code="S001", name="供应商甲", status="active"):
    sup = Supplier(code=code, name=name, status=status)
    session.add(sup)
    await session.flush()
    return sup


# ---------------------------------------------------------------- 任务创建与字段校验

@pytest.mark.asyncio
async def test_create_task_supplier_validation(db_session):
    content = "供应商编码,供应商名称,联系人\nS001,供应商甲,张三\nS002,,李四\n".encode("utf-8")
    task, preview = await tasks.create_import_task(
        db_session,
        task_type=IMPORT_SUPPLIER,
        filename="s.csv",
        content=content,
        created_by=None,
        created_by_username="admin",
    )
    assert task.status == TASK_AWAITING_CONFIRM
    assert task.total_rows == 2
    assert task.failed_rows == 1  # S002 缺名称

    # 错误行已记录
    total, errors = await tasks.get_task_errors(db_session, str(task.id))
    assert total == 1
    assert errors[0]["errorType"] == "missing_required"
    assert errors[0]["field"] == "name"


# ---------------------------------------------------------------- 供应商导入

@pytest.mark.asyncio
async def test_import_suppliers_success(db_session):
    task = _make_task(db_session, IMPORT_SUPPLIER)
    await db_session.flush()
    row = await _make_staging(db_session, task, {
        "code": "S001", "name": "供应商甲", "contact_name": "张三",
        "contact_phone": None, "email": None, "address": None, "remark": None,
    })

    success, failed, summary = await importer.run_import(db_session, task.task_type, [row])
    assert success == 1
    assert failed == 0

    saved = await db_session.scalar(select(Supplier).where(Supplier.code == "S001"))
    assert saved is not None
    assert saved.name == "供应商甲"
    assert saved.contact_name == "张三"


@pytest.mark.asyncio
async def test_import_suppliers_duplicate_code(db_session):
    await _make_supplier(db_session, code="S001", name="已存在")
    task = _make_task(db_session, IMPORT_SUPPLIER)
    await db_session.flush()
    row = await _make_staging(db_session, task, {"code": "S001", "name": "重复"})

    success, failed, summary = await importer.run_import(db_session, task.task_type, [row])
    assert success == 0
    assert failed == 1
    assert summary["duplicate_business_key"] == 1


# ---------------------------------------------------------------- 采购订单导入

@pytest.mark.asyncio
async def test_import_orders_success_with_amount(db_session):
    await _make_supplier(db_session, code="S001", name="供应商甲")
    task = _make_task(db_session, IMPORT_PURCHASE_ORDER)
    await db_session.flush()

    lines = [
        {"order_no": "PO-1", "supplier_code": "S001", "order_date": date(2026, 1, 1),
         "item_code": "A1", "item_name": "物料A", "quantity": Decimal("10"),
         "unit": "件", "unit_price": Decimal("1.50"), "tax_rate": Decimal("0"),
         "remark": None},
        {"order_no": "PO-1", "supplier_code": "S001", "order_date": date(2026, 1, 1),
         "item_code": "B2", "item_name": "物料B", "quantity": Decimal("5"),
         "unit": "件", "unit_price": Decimal("2.25"), "tax_rate": Decimal("0"),
         "remark": None},
    ]
    rows = []
    for i, mapped in enumerate(lines):
        rows.append(await _make_staging(db_session, task, mapped, row_number=2 + i))

    success, failed, summary = await importer.run_import(db_session, task.task_type, rows)
    assert success == 2
    assert failed == 0

    order = await db_session.scalar(select(PurchaseOrder).where(PurchaseOrder.order_no == "PO-1"))
    assert order is not None
    # 金额：10*1.50 + 5*2.25 = 15.00 + 11.25 = 26.25（Decimal 精确）
    assert order.total_amount == Decimal("26.25")
    assert len(order.lines) == 2


@pytest.mark.asyncio
async def test_import_orders_supplier_not_found(db_session):
    task = _make_task(db_session, IMPORT_PURCHASE_ORDER)
    await db_session.flush()
    row = await _make_staging(db_session, task, {
        "order_no": "PO-1", "supplier_code": "NOPE", "order_date": date(2026, 1, 1),
        "item_code": "A1", "item_name": "物料A", "quantity": Decimal("10"),
        "unit": "件", "unit_price": Decimal("1.00"), "tax_rate": Decimal("0"),
        "remark": None,
    })
    success, failed, summary = await importer.run_import(db_session, task.task_type, [row])
    assert failed == 1
    assert summary["supplier_not_found"] == 1


@pytest.mark.asyncio
async def test_import_orders_duplicate_item_code(db_session):
    await _make_supplier(db_session, code="S001")
    task = _make_task(db_session, IMPORT_PURCHASE_ORDER)
    await db_session.flush()
    base = {"order_no": "PO-1", "supplier_code": "S001", "order_date": date(2026, 1, 1),
            "item_code": "A1", "item_name": "物料A", "quantity": Decimal("1"),
            "unit": "件", "unit_price": Decimal("1.00"), "tax_rate": Decimal("0")}
    r1 = await _make_staging(db_session, task, base, row_number=2)
    r2 = await _make_staging(db_session, task, base, row_number=3)  # 同物料重复
    success, failed, summary = await importer.run_import(db_session, task.task_type, [r1, r2])
    assert failed == 2  # 整个单据失败，2 行都标记错误
    assert summary["order_line_not_found"] == 2


# ---------------------------------------------------------------- 收货导入

@pytest.mark.asyncio
async def test_import_receipts_success_and_quantity_limit(db_session):
    await _make_supplier(db_session, code="S001")
    # 先创建订单（数量 10）
    order_task = _make_task(db_session, IMPORT_PURCHASE_ORDER)
    await db_session.flush()
    order_row = await _make_staging(db_session, order_task, {
        "order_no": "PO-1", "supplier_code": "S001", "order_date": date(2026, 1, 1),
        "item_code": "A1", "item_name": "物料A", "quantity": Decimal("10"),
        "unit": "件", "unit_price": Decimal("2.00"), "tax_rate": Decimal("0"),
        "remark": None,
    })
    await importer.run_import(db_session, order_task.task_type, [order_row])

    # 收货 4 件
    task = _make_task(db_session, IMPORT_GOODS_RECEIPT)
    await db_session.flush()
    receipt_row = await _make_staging(db_session, task, {
        "receipt_no": "GR-1", "order_no": "PO-1", "item_code": "A1",
        "receipt_date": date(2026, 1, 5), "quantity": Decimal("4"), "remark": None,
    })
    success, failed, summary = await importer.run_import(db_session, task.task_type, [receipt_row])
    assert success == 1
    assert failed == 0

    order = await db_session.scalar(select(PurchaseOrder).where(PurchaseOrder.order_no == "PO-1"))
    assert order.status == "partially_received"
    assert order.lines[0].received_qty == Decimal("4")

    # 超量收货（再收 7 > 可收 6）→ invalid_quantity
    task2 = _make_task(db_session, IMPORT_GOODS_RECEIPT)
    await db_session.flush()
    over_row = await _make_staging(db_session, task2, {
        "receipt_no": "GR-2", "order_no": "PO-1", "item_code": "A1",
        "receipt_date": date(2026, 1, 6), "quantity": Decimal("7"), "remark": None,
    })
    success2, failed2, summary2 = await importer.run_import(db_session, task2.task_type, [over_row])
    assert failed2 == 1
    assert summary2["invalid_quantity"] == 1


# ---------------------------------------------------------------- 发票导入（提前开票）

@pytest.mark.asyncio
async def test_import_invoice_pre_invoiced_marks_pending(db_session):
    await _make_supplier(db_session, code="S001")
    order_task = _make_task(db_session, IMPORT_PURCHASE_ORDER)
    await db_session.flush()
    order_row = await _make_staging(db_session, order_task, {
        "order_no": "PO-1", "supplier_code": "S001", "order_date": date(2026, 1, 1),
        "item_code": "A1", "item_name": "物料A", "quantity": Decimal("10"),
        "unit": "件", "unit_price": Decimal("2.00"), "tax_rate": Decimal("0"),
        "remark": None,
    })
    await importer.run_import(db_session, order_task.task_type, [order_row])

    # 未收货就开票 → pending_verification
    task = _make_task(db_session, IMPORT_PURCHASE_INVOICE)
    await db_session.flush()
    inv_row = await _make_staging(db_session, task, {
        "invoice_no": "INV-1", "order_no": "PO-1", "supplier_code": "S001",
        "invoice_date": date(2026, 1, 10), "item_name": "物料A",
        "quantity": Decimal("10"), "unit_price": Decimal("2.00"),
        "tax_rate": Decimal("0.13"), "remark": None,
    })
    success, failed, summary = await importer.run_import(db_session, task.task_type, [inv_row])
    assert success == 1

    invoice = await db_session.scalar(
        select(PurchaseInvoice).where(PurchaseInvoice.invoice_no == "INV-1")
    )
    assert invoice.status == "pending_verification"
    # 税额：20.00 * 0.13 = 2.60
    assert invoice.tax_amount == Decimal("2.60")


# ---------------------------------------------------------------- 部分成功

@pytest.mark.asyncio
async def test_import_partial_failure(db_session):
    await _make_supplier(db_session, code="S001")
    task = _make_task(db_session, IMPORT_PURCHASE_ORDER)
    await db_session.flush()

    good = await _make_staging(db_session, task, {
        "order_no": "PO-OK", "supplier_code": "S001", "order_date": date(2026, 1, 1),
        "item_code": "A1", "item_name": "物料A", "quantity": Decimal("1"),
        "unit": "件", "unit_price": Decimal("1.00"), "tax_rate": Decimal("0")}, row_number=2)
    bad = await _make_staging(db_session, task, {
        "order_no": "PO-BAD", "supplier_code": "NOPE", "order_date": date(2026, 1, 1),
        "item_code": "B1", "item_name": "物料B", "quantity": Decimal("1"),
        "unit": "件", "unit_price": Decimal("1.00"), "tax_rate": Decimal("0")}, row_number=3)

    success, failed, summary = await importer.run_import(db_session, task.task_type, [good, bad])
    assert success == 1
    assert failed == 1
    assert summary["supplier_not_found"] == 1

    # 好的单据已入库，坏的不入库
    assert await db_session.scalar(select(PurchaseOrder).where(PurchaseOrder.order_no == "PO-OK")) is not None
    assert await db_session.scalar(select(PurchaseOrder).where(PurchaseOrder.order_no == "PO-BAD")) is None


# ---------------------------------------------------------------- Worker 认领

@pytest.mark.asyncio
async def test_claim_task_skip_locked(db_session):
    task = _make_task(db_session, IMPORT_SUPPLIER)
    task.status = TASK_IMPORTING
    await db_session.commit()

    claimed = await tasks.claim_task(db_session, "worker-1")
    assert claimed is not None
    assert claimed.claimed_by == "worker-1"
    assert claimed.attempts == 1

    # 已认领未超时的任务，其他 Worker 认领不到
    again = await tasks.claim_task(db_session, "worker-2")
    assert again is None


@pytest.mark.asyncio
async def test_claim_task_recover_after_timeout(db_session):
    """Worker 异常退出：任务认领超时后可被其他 Worker 重新认领（恢复语义）。"""
    from datetime import UTC, datetime, timedelta

    task = _make_task(db_session, IMPORT_SUPPLIER)
    task.status = TASK_IMPORTING
    await db_session.commit()

    # worker-1 认领后崩溃（claimed_at 设为超时之前）
    claimed = await tasks.claim_task(db_session, "worker-1")
    assert claimed is not None
    task_id = str(claimed.id)
    await db_session.execute(
        update(ImportTask)
        .where(ImportTask.id == claimed.id)
        .values(claimed_at=datetime.now(UTC) - timedelta(seconds=600))
    )
    await db_session.commit()

    # worker-2 能重新认领（超时已过期）
    recovered = await tasks.claim_task(db_session, "worker-2")
    assert recovered is not None
    assert str(recovered.id) == task_id
    assert recovered.claimed_by == "worker-2"
    assert recovered.attempts == 2  # 第二次尝试


# ---------------------------------------------------------------- 重复导入

@pytest.mark.asyncio
async def test_reimport_same_business_key_no_duplicate(db_session):
    await _make_supplier(db_session, code="S001")
    task1 = _make_task(db_session, IMPORT_PURCHASE_ORDER)
    await db_session.flush()
    row = await _make_staging(db_session, task1, {
        "order_no": "PO-1", "supplier_code": "S001", "order_date": date(2026, 1, 1),
        "item_code": "A1", "item_name": "物料A", "quantity": Decimal("1"),
        "unit": "件", "unit_price": Decimal("1.00"), "tax_rate": Decimal("0")})
    await importer.run_import(db_session, task1.task_type, [row])

    # 再次导入同一 order_no（模拟重复文件/重复单据）
    task2 = _make_task(db_session, IMPORT_PURCHASE_ORDER)
    await db_session.flush()
    row2 = await _make_staging(db_session, task2, {
        "order_no": "PO-1", "supplier_code": "S001", "order_date": date(2026, 1, 1),
        "item_code": "A1", "item_name": "物料A", "quantity": Decimal("1"),
        "unit": "件", "unit_price": Decimal("1.00"), "tax_rate": Decimal("0")})
    success, failed, summary = await importer.run_import(db_session, task2.task_type, [row2])
    assert failed == 1
    assert summary["duplicate_business_key"] == 1

    # 业务表仍只有 1 条订单
    orders = list((await db_session.execute(select(PurchaseOrder).where(PurchaseOrder.order_no == "PO-1"))).scalars())
    assert len(orders) == 1
