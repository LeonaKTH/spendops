"""SpendOps G3 采购经营指标体系：统一指标口径 + 复杂 SQL 聚合。

指标口径（唯一权威，前端/后端不得各自重写计算公式）：

金额口径（全部未税，单币种 CNY，Decimal ROUND_HALF_UP 到分）：
- 采购订单金额 = Σ 订单明细.amount（数量×单价），排除已取消订单，时间按 order_date。
- 实际收货金额 = Σ 收货明细.amount（收货数量×订单单价），排除已取消收货单，时间按 receipt_date。
- 已开票金额 = Σ 发票.total_amount（未税）+ Σ 发票.tax_amount（税额），排除已取消发票，时间按 invoice_date。
- 待核对金额 = Σ 发票.total_amount（status=pending_verification），时间按 invoice_date。

三者是独立口径，绝不互相 JOIN 后求和（避免一个订单明细多次收货/开票导致金额重复放大）。

时间边界：闭区间 [start_date, end_date]（含当天）。

集中度：供应商金额占比 = 供应商采购订单金额 / 全部供应商采购订单金额（同一时间区间、同口径）。
Top N 集中度 = Top N 供应商金额之和 / 总金额。

交货及时率（仅统计约定交期非空的明细）：
- 可判定明细 = 已履约（received_qty >= quantity）或已逾期（当前日期 > expected_delivery_date 且未收满）。
- 及时 = 已履约 且 最后收货日期 <= expected_delivery_date。
- 及时率 = 及时明细数 / 可判定明细数。缺失交期、未到期未收货的明细不计入分母。
- 无交期数据时返回「不可计算」（rate=None），不默认 0% 或 100%。

品类：仅统计 category 非空的明细；空值归「未分类」，不虚构分类。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# 公共 SQL 片段（值用参数绑定，条件存在性用 f-string 拼接）
# ---------------------------------------------------------------------------

_SUPPLIER_FILTER = "AND po.supplier_id = :supplier_id"
_STATUS_FILTER = "AND po.status = :order_status"

# 采购订单金额（未税）：只在订单明细粒度聚合，不 JOIN 收货/发票。
_ORDER_AMOUNT_SQL = """
SELECT COALESCE(SUM(pol.amount), 0)::numeric(18,2) AS v
FROM purchase_order_lines pol
JOIN purchase_orders po ON po.id = pol.order_id
WHERE po.status <> 'cancelled'
  AND po.order_date >= :start AND po.order_date <= :end
"""

# 实际收货金额（未税）：只在收货明细粒度聚合。
_RECEIPT_AMOUNT_SQL = """
SELECT COALESCE(SUM(grl.amount), 0)::numeric(18,2) AS v
FROM goods_receipt_lines grl
JOIN goods_receipts gr ON gr.id = grl.receipt_id
WHERE gr.status <> 'cancelled'
  AND gr.receipt_date >= :start AND gr.receipt_date <= :end
"""

# 发票金额（未税/税额/待核对）：只在发票头粒度聚合。
_INVOICE_AMOUNT_SQL = """
SELECT
  COALESCE(SUM(CASE WHEN pi.status <> 'cancelled' THEN pi.total_amount ELSE 0 END), 0)::numeric(18,2) AS total_amount,
  COALESCE(SUM(CASE WHEN pi.status <> 'cancelled' THEN pi.tax_amount ELSE 0 END), 0)::numeric(18,2) AS tax_amount,
  COALESCE(SUM(CASE WHEN pi.status = 'pending_verification' THEN pi.total_amount ELSE 0 END), 0)::numeric(18,2) AS pending_amount
FROM purchase_invoices pi
WHERE pi.invoice_date >= :start AND pi.invoice_date <= :end
"""


def _filter(sql: str, supplier_id: str | None, order_status: str | None) -> str:
    """把可选的供应商/状态条件拼进 SQL（值仍用参数绑定）。"""
    parts = [sql]
    if supplier_id:
        parts.append(_SUPPLIER_FILTER)
    if order_status:
        parts.append(_STATUS_FILTER)
    return "\n".join(parts)


async def _scalar(session: AsyncSession, sql: str, params: dict) -> Decimal | None:
    row = (await session.execute(text(sql), params)).scalar()
    return row if row is None else Decimal(str(row))


async def _rows(session: AsyncSession, sql: str, params: dict) -> list[dict]:
    result = await session.execute(text(sql), params)
    keys = list(result.keys())
    return [dict(zip(keys, row)) for row in result.fetchall()]


# ---------------------------------------------------------------------------
# 1. 经营总览 KPI
# ---------------------------------------------------------------------------

async def overview(
    session: AsyncSession,
    start: date,
    end: date,
    supplier_id: str | None = None,
    order_status: str | None = None,
) -> dict:
    # 采购订单金额（supplier/status 过滤经 po）
    order_amount = await _scalar(
        session,
        _filter(_ORDER_AMOUNT_SQL, supplier_id, order_status),
        {"start": start, "end": end} | _p(supplier_id, order_status),
    )

    # 收货金额（supplier 过滤在 goods_receipts）
    receipt_sql = _RECEIPT_AMOUNT_SQL
    receipt_params: dict = {"start": start, "end": end}
    if supplier_id:
        receipt_sql = _RECEIPT_AMOUNT_SQL.replace(
            "WHERE gr.status", "WHERE gr.supplier_id = :supplier_id AND gr.status"
        )
        receipt_params["supplier_id"] = supplier_id
    receipt_amount = await _scalar(session, receipt_sql, receipt_params)

    # 发票金额（supplier 过滤在 purchase_invoices）
    invoice_sql = _INVOICE_AMOUNT_SQL
    invoice_params: dict = {"start": start, "end": end}
    if supplier_id:
        invoice_sql = _INVOICE_AMOUNT_SQL.replace(
            "WHERE pi.invoice_date", "WHERE pi.supplier_id = :supplier_id AND pi.invoice_date"
        )
        invoice_params["supplier_id"] = supplier_id
    inv_row = (await session.execute(text(invoice_sql), invoice_params)).one()

    supplier_count = await _scalar(session, "SELECT COUNT(*) FROM suppliers", {})
    delivery = await delivery_performance(session, start, end, supplier_id)

    return {
        "orderAmount": order_amount,
        "receiptAmount": receipt_amount,
        "invoiceAmount": Decimal(str(inv_row.total_amount)),
        "invoiceTaxAmount": Decimal(str(inv_row.tax_amount)),
        "pendingVerificationAmount": Decimal(str(inv_row.pending_amount)),
        "supplierCount": int(supplier_count) if supplier_count is not None else 0,
        "deliveryRate": delivery["rate"],
        "deliveryOntimeCount": delivery["ontime"],
        "deliveryJudgedCount": delivery["judged"],
    }


def _p(supplier_id: str | None, order_status: str | None) -> dict:
    params: dict = {}
    if supplier_id:
        params["supplier_id"] = supplier_id
    if order_status:
        params["order_status"] = order_status
    return params


# ---------------------------------------------------------------------------
# 2. 供应商采购金额 Top N + 集中度
# ---------------------------------------------------------------------------

_SUPPLIER_RANK_SQL = """
SELECT s.code AS code, s.name AS name,
       SUM(pol.amount)::numeric(18,2) AS amount
FROM purchase_order_lines pol
JOIN purchase_orders po ON po.id = pol.order_id
JOIN suppliers s ON s.id = po.supplier_id
WHERE po.status <> 'cancelled'
  AND po.order_date >= :start AND po.order_date <= :end
GROUP BY s.id, s.code, s.name
ORDER BY amount DESC, s.code
"""


async def supplier_ranking(
    session: AsyncSession, start: date, end: date, top_n: int = 10
) -> dict:
    params = {"start": start, "end": end, "top_n": top_n}
    rows = await _rows(session, _SUPPLIER_RANK_SQL, params)
    ranking = [
        {"code": r["code"], "name": r["name"], "amount": Decimal(str(r["amount"]))}
        for r in rows[:top_n]
    ]
    total = sum((r["amount"] for r in ranking), Decimal("0"))
    # 全部供应商总金额（用于占比）
    all_total = await _scalar(
        session,
        "SELECT COALESCE(SUM(pol.amount),0)::numeric(18,2) FROM purchase_order_lines pol "
        "JOIN purchase_orders po ON po.id=pol.order_id "
        "WHERE po.status <> 'cancelled' AND po.order_date >= :start AND po.order_date <= :end",
        {"start": start, "end": end},
    )
    for r in ranking:
        r["share"] = (r["amount"] / all_total) if all_total else Decimal("0")
    concentration = (total / all_total) if all_total else Decimal("0")
    return {
        "ranking": ranking,
        "topAmount": total,
        "totalAmount": all_total,
        "concentration": concentration,
    }


# ---------------------------------------------------------------------------
# 3. 月度趋势（订单/收货/发票三种金额，独立聚合）
# ---------------------------------------------------------------------------

_TREND_ORDER_SQL = """
SELECT to_char(date_trunc('month', po.order_date), 'YYYY-MM') AS month,
       SUM(pol.amount)::numeric(18,2) AS amount
FROM purchase_order_lines pol
JOIN purchase_orders po ON po.id = pol.order_id
WHERE po.status <> 'cancelled'
  AND po.order_date >= :start AND po.order_date <= :end
GROUP BY 1 ORDER BY 1
"""

_TREND_RECEIPT_SQL = """
SELECT to_char(date_trunc('month', gr.receipt_date), 'YYYY-MM') AS month,
       SUM(grl.amount)::numeric(18,2) AS amount
FROM goods_receipt_lines grl
JOIN goods_receipts gr ON gr.id = grl.receipt_id
WHERE gr.status <> 'cancelled'
  AND gr.receipt_date >= :start AND gr.receipt_date <= :end
GROUP BY 1 ORDER BY 1
"""

_TREND_INVOICE_SQL = """
SELECT to_char(date_trunc('month', pi.invoice_date), 'YYYY-MM') AS month,
       SUM(pi.total_amount)::numeric(18,2) AS amount
FROM purchase_invoices pi
WHERE pi.status <> 'cancelled'
  AND pi.invoice_date >= :start AND pi.invoice_date <= :end
GROUP BY 1 ORDER BY 1
"""


async def monthly_trend(
    session: AsyncSession, start: date, end: date, supplier_id: str | None = None
) -> dict:
    params = {"start": start, "end": end}
    order_rows = await _rows(session, _TREND_ORDER_SQL, params)
    receipt_rows = await _rows(session, _TREND_RECEIPT_SQL, params)
    invoice_rows = await _rows(session, _TREND_INVOICE_SQL, params)

    def to_map(rows: list[dict]) -> dict[str, Decimal]:
        return {r["month"]: Decimal(str(r["amount"])) for r in rows}

    order_map = to_map(order_rows)
    receipt_map = to_map(receipt_rows)
    invoice_map = to_map(invoice_rows)

    # 生成完整月份序列（含无数据月份补 0）
    months: list[str] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1

    series = [
        {
            "month": mo,
            "orderAmount": order_map.get(mo, Decimal("0")),
            "receiptAmount": receipt_map.get(mo, Decimal("0")),
            "invoiceAmount": invoice_map.get(mo, Decimal("0")),
        }
        for mo in months
    ]
    return {"months": months, "series": series}


# ---------------------------------------------------------------------------
# 4. 交货及时率
# ---------------------------------------------------------------------------

_DELIVERY_SQL = """
WITH d AS (
    SELECT pol.quantity AS quantity,
           pol.received_qty AS received,
           pol.expected_delivery_date AS due,
           MAX(gr.receipt_date) AS last_receipt
    FROM purchase_order_lines pol
    JOIN purchase_orders po ON po.id = pol.order_id
    LEFT JOIN goods_receipt_lines grl ON grl.order_line_id = pol.id
    LEFT JOIN goods_receipts gr ON gr.id = grl.receipt_id AND gr.status <> 'cancelled'
    WHERE po.status <> 'cancelled'
      AND pol.expected_delivery_date IS NOT NULL
      AND po.order_date >= :start AND po.order_date <= :end
    GROUP BY pol.id, pol.quantity, pol.received_qty, pol.expected_delivery_date
)
SELECT
    COUNT(*) FILTER (WHERE received >= quantity AND last_receipt <= due) AS ontime,
    COUNT(*) FILTER (WHERE (received >= quantity AND last_receipt > due)
                          OR (received < quantity AND due < CURRENT_DATE)) AS late,
    COUNT(*) FILTER (WHERE received >= quantity OR due < CURRENT_DATE) AS judged,
    COUNT(*) FILTER (WHERE received < quantity AND due >= CURRENT_DATE) AS excluded
FROM d
"""


async def delivery_performance(
    session: AsyncSession, start: date, end: date, supplier_id: str | None = None
) -> dict:
    sql = _DELIVERY_SQL
    if supplier_id:
        sql = sql.replace(
            "WHERE po.status <> 'cancelled'",
            "WHERE po.status <> 'cancelled'\n      AND po.supplier_id = :supplier_id",
        )
    params = {"start": start, "end": end}
    if supplier_id:
        params["supplier_id"] = supplier_id
    row = (await session.execute(text(sql), params)).one()

    ontime = int(row.ontime or 0)
    late = int(row.late or 0)
    judged = int(row.judged or 0)
    excluded = int(row.excluded or 0)

    rate = (Decimal(ontime) / Decimal(judged)) if judged else None
    return {
        "ontime": ontime,
        "late": late,
        "judged": judged,
        "excluded": excluded,
        "rate": rate,
    }


# ---------------------------------------------------------------------------
# 5. 品类采购分析
# ---------------------------------------------------------------------------

_CATEGORY_SQL = """
SELECT COALESCE(NULLIF(pol.category, ''), '未分类') AS category,
       SUM(pol.amount)::numeric(18,2) AS amount
FROM purchase_order_lines pol
JOIN purchase_orders po ON po.id = pol.order_id
WHERE po.status <> 'cancelled'
  AND po.order_date >= :start AND po.order_date <= :end
GROUP BY 1 ORDER BY amount DESC
"""


async def category_breakdown(session: AsyncSession, start: date, end: date) -> dict:
    rows = await _rows(session, _CATEGORY_SQL, {"start": start, "end": end})
    total = sum((Decimal(str(r["amount"])) for r in rows), Decimal("0"))
    items = [
        {"category": r["category"], "amount": Decimal(str(r["amount"])),
         "share": (Decimal(str(r["amount"])) / total) if total else Decimal("0")}
        for r in rows
    ]
    return {"total": total, "items": items}


# ---------------------------------------------------------------------------
# 6. 三单差异分析
# ---------------------------------------------------------------------------

_DISCREPANCY_SQL = """
WITH receipt_agg AS (
    SELECT grl.order_line_id, SUM(grl.amount) AS amount
    FROM goods_receipt_lines grl
    JOIN goods_receipts gr ON gr.id = grl.receipt_id AND gr.status <> 'cancelled'
    GROUP BY grl.order_line_id
),
invoice_agg AS (
    SELECT pil.order_line_id, SUM(pil.amount) AS amount
    FROM purchase_invoice_lines pil
    JOIN purchase_invoices pi ON pi.id = pil.invoice_id AND pi.status <> 'cancelled'
    GROUP BY pil.order_line_id
)
SELECT po.order_no AS order_no,
       s.code AS supplier_code,
       pol.item_name AS item_name,
       pol.quantity AS quantity,
       pol.received_qty AS received_qty,
       pol.invoiced_qty AS invoiced_qty,
       pol.amount AS order_amount,
       COALESCE(ra.amount, 0)::numeric(18,2) AS receipt_amount,
       COALESCE(ia.amount, 0)::numeric(18,2) AS invoice_amount,
       po.status AS order_status
FROM purchase_order_lines pol
JOIN purchase_orders po ON po.id = pol.order_id
JOIN suppliers s ON s.id = po.supplier_id
LEFT JOIN receipt_agg ra ON ra.order_line_id = pol.id
LEFT JOIN invoice_agg ia ON ia.order_line_id = pol.id
WHERE po.status <> 'cancelled'
  AND po.order_date >= :start AND po.order_date <= :end
ORDER BY po.order_no, pol.line_no
"""


# ---------------------------------------------------------------------------
# 7. 延期订单明细（供受控问数「哪些订单交付延期」使用）
# ---------------------------------------------------------------------------

_LATE_ORDERS_SQL = """
SELECT po.order_no AS order_no,
       s.code AS supplier_code,
       pol.item_name AS item_name,
       pol.quantity AS quantity,
       pol.received_qty AS received_qty,
       pol.expected_delivery_date AS due
FROM purchase_order_lines pol
JOIN purchase_orders po ON po.id = pol.order_id
JOIN suppliers s ON s.id = po.supplier_id
WHERE po.status <> 'cancelled'
  AND pol.expected_delivery_date IS NOT NULL
  AND pol.received_qty < pol.quantity
  AND pol.expected_delivery_date < CURRENT_DATE
  AND po.order_date >= :start AND po.order_date <= :end
ORDER BY pol.expected_delivery_date, po.order_no
"""


async def late_orders(
    session: AsyncSession, start: date, end: date, supplier_id: str | None = None
) -> list[dict]:
    """已逾期未收满的订单明细（确定性事实：交期早于今天且未收满）。"""
    sql = _LATE_ORDERS_SQL
    if supplier_id:
        sql = sql.replace(
            "AND pol.expected_delivery_date IS NOT NULL",
            "AND pol.expected_delivery_date IS NOT NULL\n  AND po.supplier_id = :supplier_id",
        )
    params = {"start": start, "end": end}
    if supplier_id:
        params["supplier_id"] = supplier_id
    rows = await _rows(session, sql, params)
    return [
        {
            "orderNo": r["order_no"],
            "supplierCode": r["supplier_code"],
            "itemName": r["item_name"],
            "quantity": Decimal(str(r["quantity"])),
            "receivedQty": Decimal(str(r["received_qty"])),
            "due": r["due"].isoformat() if r["due"] else None,
            "shortfall": Decimal(str(r["quantity"])) - Decimal(str(r["received_qty"])),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# 8. 待核对发票（供受控问数「多少待核对发票」使用）
# ---------------------------------------------------------------------------

_PENDING_INVOICE_SQL = """
SELECT pi.invoice_no AS invoice_no,
       s.code AS supplier_code,
       pi.total_amount AS total_amount,
       pi.invoice_date AS invoice_date
FROM purchase_invoices pi
JOIN suppliers s ON s.id = pi.supplier_id
WHERE pi.status = 'pending_verification'
  AND pi.invoice_date >= :start AND pi.invoice_date <= :end
ORDER BY pi.invoice_date, pi.invoice_no
"""


async def pending_invoices(
    session: AsyncSession, start: date, end: date, supplier_id: str | None = None
) -> dict:
    """待核对发票：返回数量、金额合计与明细列表。"""
    sql = _PENDING_INVOICE_SQL
    if supplier_id:
        sql = sql.replace(
            "WHERE pi.status = 'pending_verification'",
            "WHERE pi.status = 'pending_verification'\n  AND pi.supplier_id = :supplier_id",
        )
    params = {"start": start, "end": end}
    if supplier_id:
        params["supplier_id"] = supplier_id
    rows = await _rows(session, sql, params)
    items = [
        {
            "invoiceNo": r["invoice_no"],
            "supplierCode": r["supplier_code"],
            "amount": Decimal(str(r["total_amount"])),
            "invoiceDate": r["invoice_date"].isoformat() if r["invoice_date"] else None,
        }
        for r in rows
    ]
    total = sum((i["amount"] for i in items), Decimal("0"))
    return {"count": len(items), "total": total, "items": items}


async def discrepancies(session: AsyncSession, start: date, end: date) -> list[dict]:
    rows = await _rows(session, _DISCREPANCY_SQL, {"start": start, "end": end})
    result = []
    for r in rows:
        qty = Decimal(str(r["quantity"]))
        recv = Decimal(str(r["received_qty"]))
        inv = Decimal(str(r["invoiced_qty"]))
        item = {
            "orderNo": r["order_no"],
            "supplierCode": r["supplier_code"],
            "itemName": r["item_name"],
            "quantity": qty,
            "receivedQty": recv,
            "invoicedQty": inv,
            "orderAmount": Decimal(str(r["order_amount"])),
            "receiptAmount": Decimal(str(r["receipt_amount"])),
            "invoiceAmount": Decimal(str(r["invoice_amount"])),
        }
        kinds = []
        if recv == 0:
            kinds.append("unreceived")  # 已下单未收货
        elif recv < qty:
            kinds.append("partial_received")  # 部分收货
        if recv > inv:
            kinds.append("received_not_invoiced")  # 已收货未开票
        if inv > recv:
            kinds.append("pre_invoiced")  # 提前开票
        item["discrepancyKinds"] = kinds
        item["quantityDiff"] = qty - recv
        item["amountDiff"] = Decimal(str(r["order_amount"])) - Decimal(str(r["receipt_amount"]))
        result.append(item)
    return result
