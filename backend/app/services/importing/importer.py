"""SpendOps G2 采购业务导入器。

把校验通过的暂存行按业务单据分组，逐单据写入正式业务表。

事务策略（明确，不假装同时原子与部分成功）：
- 每个业务单据（一个供应商 / 一个订单 / 一张收货单 / 一张发票）为一个事务单元。
- 单据内部原子：头和明细要么一起成功，要么一起回滚。
- 单据之间独立：某个单据失败不影响其他单据，失败单据记录行级错误，
  任务最终按 success_rows / failed_rows 标记 completed / partial_failed / failed。

金额一律 Decimal（复用 domain.line_amount / total_amount），业务校验与
错误类型映射到 errors.py 定义的错误码。
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal

import time

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.importing import (
    IMPORT_GOODS_RECEIPT,
    IMPORT_PURCHASE_INVOICE,
    IMPORT_PURCHASE_ORDER,
    IMPORT_SUPPLIER,
    ImportStagingRow,
    ROW_ERROR,
    ROW_IMPORTED,
)
from app.db.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseInvoice,
    PurchaseInvoiceLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
)
from app.services.importing.errors import (
    ERR_BUSINESS_CONFLICT,
    ERR_DUPLICATE_KEY,
    ERR_INVALID_INVOICE_QTY,
    ERR_INVALID_QUANTITY,
    ERR_ORDER_LINE_NOT_FOUND,
    ERR_ORDER_NOT_FOUND,
    ERR_SUPPLIER_NOT_FOUND,
)
from app.services.purchasing.domain import (
    ORDER_CANCELLED,
    ORDER_DRAFT,
    ORDER_PARTIALLY_RECEIVED,
    ORDER_RECEIVED,
    SUPPLIER_BLOCKED,
    line_amount,
    money,
    total_amount,
)
from app.services.importing.validate import parse_date


class ImportFailure(Exception):
    """导入单据失败，携带行级错误类型。"""

    def __init__(self, error_type: str, message: str, field: str | None = None):
        super().__init__(message)
        self.error_type = error_type
        self.field = field
        self.message = message


def _dec(value, default=None) -> Decimal | None:
    """JSONB 读出的字符串 -> Decimal。"""
    if value is None or str(value).strip() == "":
        return default
    return Decimal(str(value))


def _date(value):
    """JSONB 读出的 ISO 字符串 -> date。"""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return parse_date(str(value))


def _group_by(rows: list[ImportStagingRow], key_field: str) -> dict[str, list[ImportStagingRow]]:
    groups: dict[str, list[ImportStagingRow]] = defaultdict(list)
    for row in rows:
        data = row.mapped_data or {}
        key = str(data.get(key_field, "")).strip()
        groups[key].append(row)
    return dict(groups)


async def _commit_group(
    session: AsyncSession,
    rows: list[ImportStagingRow],
    write_fn,
) -> tuple[int, list[dict]]:
    """对一组（一个单据）行执行写入并提交；失败则回滚并标记错误。

    返回 (成功行数, 失败详情列表)。
    """
    try:
        await write_fn(rows)
        for row in rows:
            row.status = ROW_IMPORTED
            row.error_type = None
            row.error_field = None
            row.error_message = None
        await session.commit()
        return len(rows), []
    except ImportFailure as exc:
        await session.rollback()
        for row in rows:
            row.status = ROW_ERROR
            row.error_type = exc.error_type
            row.error_field = exc.field
            row.error_message = exc.message
        await session.commit()
        return 0, [
            {"row_number": row.row_number, "error_type": exc.error_type,
             "field": exc.field, "message": exc.message}
            for row in rows
        ]
    except IntegrityError as exc:
        await session.rollback()
        for row in rows:
            row.status = ROW_ERROR
            row.error_type = ERR_DUPLICATE_KEY
            row.error_field = None
            row.error_message = f"业务单号重复或约束冲突：{exc}"
        await session.commit()
        return 0, [
            {"row_number": row.row_number, "error_type": ERR_DUPLICATE_KEY,
             "field": None, "message": f"业务单号重复或约束冲突：{exc}"}
            for row in rows
        ]
    except Exception as exc:  # 意外错误也记录，不静默跳过
        await session.rollback()
        for row in rows:
            row.status = ROW_ERROR
            row.error_type = ERR_BUSINESS_CONFLICT
            row.error_field = None
            row.error_message = f"导入失败：{exc}"
        await session.commit()
        return 0, [
            {"row_number": row.row_number, "error_type": ERR_BUSINESS_CONFLICT,
             "field": None, "message": f"导入失败：{exc}"}
            for row in rows
        ]


# 心跳节流：时间驱动（超过 HEARTBEAT_INTERVAL_SECONDS 秒）或行数兜底（超过 HEARTBEAT_MAX_ROWS 单据），
# 任一满足即向 Worker 报告进度（续租 + 取消检查）。时间驱动确保单单据长时间阻塞也能及时续租。
HEARTBEAT_INTERVAL_SECONDS = 30
HEARTBEAT_MAX_ROWS = 1000


class ImportInterrupted(Exception):
    """导入被中断：任务被取消，或 Worker 所有权丢失（被其他 Worker 重认领）。"""


async def run_import(
    session: AsyncSession,
    task_type: str,
    rows: list[ImportStagingRow],
    on_progress=None,
) -> tuple[int, int, dict[str, int]]:
    """执行导入，返回 (成功行数, 失败行数, 错误摘要 {错误类型: 数量})。

    on_progress: 可选 async 回调，签名为 ``async def (processed: int) -> bool``，
    返回 False 表示应中止导入（抛出 ImportInterrupted）。
    """
    dispatcher = {
        IMPORT_SUPPLIER: _import_suppliers,
        IMPORT_PURCHASE_ORDER: _import_orders,
        IMPORT_GOODS_RECEIPT: _import_receipts,
        IMPORT_PURCHASE_INVOICE: _import_invoices,
    }
    handler = dispatcher.get(task_type)
    if handler is None:
        raise ValueError(f"未知导入类型 {task_type}")

    # 开始处理前先检查一次：任务可能已被取消，或所有权已丢失。
    if on_progress is not None and not await on_progress(0):
        raise ImportInterrupted("导入在开始前被中断")

    # 时间驱动的节流心跳闭包：传给 handler，每处理一个单据后调用。
    last_heartbeat = [time.monotonic()]

    async def heartbeat(processed: int) -> None:
        if on_progress is None:
            return
        now = time.monotonic()
        if (
            now - last_heartbeat[0] >= HEARTBEAT_INTERVAL_SECONDS
            or processed % HEARTBEAT_MAX_ROWS == 0
        ):
            last_heartbeat[0] = now
            if not await on_progress(processed):
                raise ImportInterrupted("导入被中断")

    success_rows, failures = await handler(session, rows, heartbeat)

    error_summary: dict[str, int] = defaultdict(int)
    for failure in failures:
        error_summary[failure["error_type"]] += 1

    return success_rows, len(failures), dict(error_summary)


# ---------------------------------------------------------------- supplier

async def _import_suppliers(
    session: AsyncSession, rows: list[ImportStagingRow], on_progress=None
) -> tuple[int, list[dict]]:
    success = 0
    failures: list[dict] = []
    seen_codes: set[str] = set()
    processed = 0

    for row in rows:
        processed += 1
        data = row.mapped_data or {}
        code = str(data.get("code", "")).strip()
        if code in seen_codes:
            row.status = ROW_ERROR
            row.error_type = ERR_DUPLICATE_KEY
            row.error_field = "code"
            row.error_message = f"文件内供应商编码「{code}」重复。"
            await session.commit()
            failures.append({"row_number": row.row_number, "error_type": ERR_DUPLICATE_KEY,
                             "field": "code", "message": row.error_message})
            await on_progress(processed)
            continue
        seen_codes.add(code)

        async def write_supplier(r: list[ImportStagingRow]) -> None:
            d = r[0].mapped_data or {}
            existing = await session.scalar(select(Supplier).where(Supplier.code == d["code"]))
            if existing is not None:
                raise ImportFailure(ERR_DUPLICATE_KEY, f"供应商编码「{d['code']}」已存在。", "code")
            session.add(
                Supplier(
                    code=d["code"],
                    name=d["name"],
                    contact_name=d.get("contact_name"),
                    contact_phone=d.get("contact_phone"),
                    email=d.get("email"),
                    address=d.get("address"),
                    remark=d.get("remark"),
                )
            )

        ok, errs = await _commit_group(session, [row], write_supplier)
        success += ok
        failures.extend(errs)
        await on_progress(processed)

    return success, failures


# ---------------------------------------------------------------- order

async def _import_orders(
    session: AsyncSession, rows: list[ImportStagingRow], on_progress=None
) -> tuple[int, list[dict]]:
    success = 0
    failures: list[dict] = []
    groups = _group_by(rows, "order_no")
    processed = 0

    for order_no, group in groups.items():
        processed += 1
        async def write_order(r: list[ImportStagingRow]) -> None:
            first = r[0].mapped_data or {}
            supplier_code = str(first.get("supplier_code", "")).strip()
            supplier = await session.scalar(
                select(Supplier).where(Supplier.code == supplier_code)
            )
            if supplier is None:
                raise ImportFailure(
                    ERR_SUPPLIER_NOT_FOUND,
                    f"供应商编码「{supplier_code}」不存在，请先导入或创建供应商。",
                    "supplier_code",
                )
            if supplier.status == SUPPLIER_BLOCKED:
                raise ImportFailure(
                    ERR_BUSINESS_CONFLICT,
                    f"供应商「{supplier_code}」已停用，不能创建订单。",
                    "supplier_code",
                )
            existing = await session.scalar(
                select(PurchaseOrder).where(PurchaseOrder.order_no == order_no)
            )
            if existing is not None:
                raise ImportFailure(ERR_DUPLICATE_KEY, f"采购订单号「{order_no}」已存在。", "order_no")

            order_date = _date(first.get("order_date"))
            if order_date is None:
                raise ImportFailure(
                    ERR_BUSINESS_CONFLICT, f"订单「{order_no}」缺少有效下单日期。", "order_date")

            order = PurchaseOrder(
                order_no=order_no,
                supplier_id=supplier.id,
                supplier=supplier,
                order_date=order_date,
                status="submitted",
                currency="CNY",
                remark=first.get("remark"),
            )
            session.add(order)

            amount_list: list[Decimal] = []
            seen_items: set[str] = set()
            for index, row in enumerate(r, start=1):
                d = row.mapped_data or {}
                item_code = str(d.get("item_code", "")).strip()
                if item_code in seen_items:
                    raise ImportFailure(
                        ERR_ORDER_LINE_NOT_FOUND,
                        f"订单「{order_no}」内物料编码「{item_code}」重复。",
                        "item_code",
                    )
                seen_items.add(item_code)
                quantity = _dec(d.get("quantity"))
                unit_price = _dec(d.get("unit_price"))
                if quantity is None or unit_price is None:
                    raise ImportFailure(
                        ERR_BUSINESS_CONFLICT, f"订单「{order_no}」明细缺少数量或单价。")
                if quantity <= 0 or unit_price < 0:
                    raise ImportFailure(
                        ERR_INVALID_QUANTITY, f"订单「{order_no}」明细数量/单价非法。")
                amount = line_amount(quantity, unit_price)
                amount_list.append(amount)
                order.lines.append(
                    PurchaseOrderLine(
                        line_no=index,
                        item_code=item_code,
                        item_name=str(d.get("item_name", "")).strip(),
                        category=d.get("category"),
                        expected_delivery_date=_date(d.get("expected_delivery_date")),
                        quantity=quantity,
                        unit=d.get("unit") or "件",
                        unit_price=unit_price,
                        tax_rate=_dec(d.get("tax_rate")) or Decimal("0"),
                        amount=amount,
                    )
                )
            order.total_amount = total_amount(amount_list)

        ok, errs = await _commit_group(session, group, write_order)
        success += ok
        failures.extend(errs)
        await on_progress(processed)

    return success, failures


# ---------------------------------------------------------------- receipt

async def _import_receipts(
    session: AsyncSession, rows: list[ImportStagingRow], on_progress=None
) -> tuple[int, list[dict]]:
    success = 0
    failures: list[dict] = []
    groups = _group_by(rows, "receipt_no")
    processed = 0

    for receipt_no, group in groups.items():
        processed += 1
        async def write_receipt(r: list[ImportStagingRow]) -> None:
            first = r[0].mapped_data or {}
            order_no = str(first.get("order_no", "")).strip()
            order = await session.scalar(
                select(PurchaseOrder)
                .options(selectinload(PurchaseOrder.lines))
                .where(PurchaseOrder.order_no == order_no)
            )
            if order is None:
                raise ImportFailure(ERR_ORDER_NOT_FOUND, f"采购订单「{order_no}」不存在。", "order_no")
            if order.status == ORDER_CANCELLED:
                raise ImportFailure(
                    ERR_BUSINESS_CONFLICT, f"订单「{order_no}」已取消，不能收货。", "order_no")
            if order.status == ORDER_DRAFT:
                raise ImportFailure(
                    ERR_BUSINESS_CONFLICT, f"订单「{order_no}」尚未提交，不能收货。", "order_no")

            existing = await session.scalar(
                select(GoodsReceipt).where(GoodsReceipt.receipt_no == receipt_no)
            )
            if existing is not None:
                raise ImportFailure(ERR_DUPLICATE_KEY, f"收货单号「{receipt_no}」已存在。", "receipt_no")

            receipt_date = _date(first.get("receipt_date"))
            if receipt_date is None:
                raise ImportFailure(
                    ERR_BUSINESS_CONFLICT, f"收货单「{receipt_no}」缺少有效收货日期。", "receipt_date")

            receipt = GoodsReceipt(
                receipt_no=receipt_no,
                order_id=order.id,
                supplier_id=order.supplier_id,
                order=order,
                supplier=order.supplier,
                receipt_date=receipt_date,
                status="posted",
                remark=first.get("remark"),
            )
            session.add(receipt)

            amount_list: list[Decimal] = []
            qty_list: list[Decimal] = []
            matched_line_ids: set[uuid.UUID] = set()
            for index, row in enumerate(r, start=1):
                d = row.mapped_data or {}
                item_code = str(d.get("item_code", "")).strip()
                order_line = next((ol for ol in order.lines if ol.item_code == item_code), None)
                if order_line is None:
                    raise ImportFailure(
                        ERR_ORDER_LINE_NOT_FOUND,
                        f"订单「{order_no}」中找不到物料「{item_code}」。", "item_code")
                if order_line.id in matched_line_ids:
                    raise ImportFailure(
                        ERR_ORDER_LINE_NOT_FOUND,
                        f"收货单「{receipt_no}」内物料「{item_code}」重复。", "item_code")
                matched_line_ids.add(order_line.id)

                quantity = _dec(d.get("quantity"))
                if quantity is None:
                    raise ImportFailure(ERR_INVALID_QUANTITY, "缺少收货数量。", "quantity")
                if quantity <= 0:
                    raise ImportFailure(ERR_INVALID_QUANTITY, f"收货数量「{quantity}」非法。", "quantity")
                if quantity + order_line.received_qty > order_line.quantity:
                    raise ImportFailure(
                        ERR_INVALID_QUANTITY,
                        f"物料「{item_code}」收货数量超限：可收 "
                        f"{order_line.quantity - order_line.received_qty}，本次 {quantity}。",
                        "quantity",
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
            all_received = all(line.received_qty >= line.quantity for line in order.lines)
            order.status = ORDER_RECEIVED if all_received else ORDER_PARTIALLY_RECEIVED

        ok, errs = await _commit_group(session, group, write_receipt)
        success += ok
        failures.extend(errs)
        await on_progress(processed)

    return success, failures


# ---------------------------------------------------------------- invoice

async def _import_invoices(
    session: AsyncSession, rows: list[ImportStagingRow], on_progress=None
) -> tuple[int, list[dict]]:
    success = 0
    failures: list[dict] = []
    groups = _group_by(rows, "invoice_no")
    processed = 0

    for invoice_no, group in groups.items():
        processed += 1
        async def write_invoice(r: list[ImportStagingRow]) -> None:
            first = r[0].mapped_data or {}
            supplier_code = str(first.get("supplier_code", "")).strip()
            supplier = await session.scalar(select(Supplier).where(Supplier.code == supplier_code))
            if supplier is None:
                raise ImportFailure(ERR_SUPPLIER_NOT_FOUND, f"供应商编码「{supplier_code}」不存在。", "supplier_code")

            order: PurchaseOrder | None = None
            order_no = first.get("order_no")
            if order_no:
                order = await session.scalar(
                    select(PurchaseOrder)
                    .options(selectinload(PurchaseOrder.lines))
                    .where(PurchaseOrder.order_no == str(order_no).strip())
                )
                if order is None:
                    raise ImportFailure(ERR_ORDER_NOT_FOUND, f"采购订单「{order_no}」不存在。", "order_no")

            existing = await session.scalar(
                select(PurchaseInvoice).where(PurchaseInvoice.invoice_no == invoice_no)
            )
            if existing is not None:
                raise ImportFailure(ERR_DUPLICATE_KEY, f"发票号「{invoice_no}」已存在。", "invoice_no")

            invoice_date = _date(first.get("invoice_date"))
            if invoice_date is None:
                raise ImportFailure(
                    ERR_BUSINESS_CONFLICT, f"发票「{invoice_no}」缺少有效开票日期。", "invoice_date")

            invoice = PurchaseInvoice(
                invoice_no=invoice_no,
                order_id=order.id if order else None,
                supplier_id=supplier.id,
                order=order,
                supplier=supplier,
                invoice_date=invoice_date,
                status="posted",
                currency="CNY",
                remark=first.get("remark"),
            )
            session.add(invoice)

            amount_list: list[Decimal] = []
            tax_list: list[Decimal] = []
            pre_invoiced = False
            for index, row in enumerate(r, start=1):
                d = row.mapped_data or {}
                item_name = str(d.get("item_name", "")).strip()
                quantity = _dec(d.get("quantity"))
                unit_price = _dec(d.get("unit_price"))
                tax_rate = _dec(d.get("tax_rate")) or Decimal("0")
                if quantity is None or unit_price is None:
                    raise ImportFailure(ERR_BUSINESS_CONFLICT, f"发票「{invoice_no}」明细缺少数量或单价。")

                resolved_order_line: PurchaseOrderLine | None = None
                if order is not None:
                    candidate = next((ol for ol in order.lines if ol.item_name == item_name), None)
                    if candidate is not None:
                        if candidate.invoiced_qty + quantity > candidate.quantity:
                            raise ImportFailure(
                                ERR_INVALID_INVOICE_QTY,
                                f"物料「{item_name}」开票数量超限：可开 "
                                f"{candidate.quantity - candidate.invoiced_qty}，本次 {quantity}。",
                                "quantity",
                            )
                        if quantity > candidate.received_qty:
                            pre_invoiced = True
                        candidate.invoiced_qty = candidate.invoiced_qty + quantity
                        resolved_order_line = candidate

                amount = line_amount(quantity, unit_price)
                tax = money(amount * tax_rate)
                amount_list.append(amount)
                tax_list.append(tax)
                invoice.lines.append(
                    PurchaseInvoiceLine(
                        line_no=index,
                        order_line_id=resolved_order_line.id if resolved_order_line else None,
                        item_name=item_name,
                        quantity=quantity,
                        unit_price=unit_price,
                        amount=amount,
                    )
                )

            invoice.total_amount = total_amount(amount_list)
            invoice.tax_amount = total_amount(tax_list)
            if pre_invoiced:
                invoice.status = "pending_verification"

        ok, errs = await _commit_group(session, group, write_invoice)
        success += ok
        failures.extend(errs)
        await on_progress(processed)

    return success, failures
