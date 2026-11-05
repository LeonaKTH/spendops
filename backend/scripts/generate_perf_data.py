"""SpendOps G4 大规模性能数据生成脚本（专用 perf 库）。

生成真实采购关系的大规模数据：供应商、订单、明细、部分收货、多次开票、
品类、跨月、延期、待核对、取消。金额 Decimal（domain.line_amount），
状态/约束符合 G1/G2 业务规则。

用法：
  DATABASE_URL=postgresql+asyncpg://spendops_app:...@127.0.0.1:5433/spendops_perf \
  python scripts/generate_perf_data.py --orders 10000 --seed 20261105

记录：随机种子、各表记录数、耗时、数据库体积。
"""

from __future__ import annotations

import asyncio
import argparse
import os
import random
import sys
import time
from datetime import date, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.db.models import (  # noqa: E402
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseInvoice,
    PurchaseInvoiceLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
)
from app.services.purchasing.domain import line_amount  # noqa: E402

CATEGORIES = ["电子", "机械", "办公", "原材料", "包装"]
MONTHS = 6  # 业务时间跨度


def _make_suppliers(n: int) -> list[tuple[str, str, str]]:
    return [
        (f"SUP-{i:04d}", f"供应商{i:04d}", CATEGORIES[i % len(CATEGORIES)])
        for i in range(n)
    ]


async def _bulk_insert(conn, rows: list):
    """用 executemany 高效批量插入。"""
    if not rows:
        return
    table = rows[0].__table__
    await conn.execute(table.insert(), [r._asdict() if hasattr(r, "_asdict") else {
        c.name: getattr(r, c.name) for c in table.columns
        if c.name in r.__dict__
    } for r in rows])


async def generate(db_url: str, orders_n: int, seed: int, supplier_n: int) -> dict:
    engine = create_async_engine(db_url)
    rng = random.Random(seed)
    t0 = time.time()

    async with engine.begin() as conn:
        # 1. 供应商
        sup_rows = [
            Supplier(code=c, name=n, status="active")
            for c, n, _cat in _make_suppliers(supplier_n)
        ]
        await conn.execute(text(
            "INSERT INTO suppliers (id, code, name, status, created_at, updated_at) "
            "VALUES (gen_random_uuid(), :code, :name, 'active', now(), now())"
        ), [{"code": s.code, "name": s.name} for s in sup_rows])
        sup_ids = list((await conn.execute(text(
            "SELECT id, code FROM suppliers ORDER BY code"
        ))).all())
        id_by_code = {code: sid for sid, code in sup_ids}

        # 2. 订单 + 明细（分批）
        order_rows = []
        line_rows = []
        start = date(2026, 1, 1)
        for oi in range(orders_n):
            code = f"SUP-{rng.randint(0, supplier_n - 1):04d}"
            sid = id_by_code[code]
            order_date = start + timedelta(days=rng.randint(0, MONTHS * 30 - 1))
            n_lines = rng.randint(1, 4)
            # 5% 取消
            status = "cancelled" if rng.random() < 0.05 else "submitted"
            order_rows.append({
                "order_no": f"PO-{oi + 1:06d}", "supplier_id": sid,
                "order_date": order_date, "status": status, "currency": "CNY",
                "total_amount": None, "remark": None,
            })
            for li in range(1, n_lines + 1):
                qty = Decimal(str(rng.randint(1, 50)))
                price = Decimal(str(rng.randint(10, 2000))) / Decimal("10")
                cat = CATEGORIES[rng.randint(0, len(CATEGORIES) - 1)]
                due = None
                if rng.random() >= 0.2:
                    due = order_date + timedelta(days=rng.randint(5, 20))
                line_rows.append({
                    "order_no": f"PO-{oi + 1:06d}", "line_no": li,
                    "item_code": f"ITEM-{rng.randint(1000, 9999)}",
                    "item_name": f"物料{rng.randint(1, 99999)}",
                    "category": cat, "expected_delivery_date": due,
                    "quantity": qty, "unit": "件", "unit_price": price,
                    "tax_rate": Decimal("0"), "amount": line_amount(qty, price),
                    "received_qty": Decimal("0"), "invoiced_qty": Decimal("0"),
                })

        # 插入订单（拿 order_no -> id）
        await conn.execute(text(
            "INSERT INTO purchase_orders (id, order_no, supplier_id, order_date, status, "
            "currency, total_amount, remark, created_at, updated_at) "
            "VALUES (gen_random_uuid(), :order_no, :supplier_id, :order_date, :status, "
            "'CNY', 0, NULL, now(), now())"
        ), order_rows)
        order_id_by_no = dict((await conn.execute(text(
            "SELECT order_no, id FROM purchase_orders"
        ))).all())

        # 插入明细（关联 order_id + 算订单总额）
        line_insert = []
        for lr in line_rows:
            oid = order_id_by_no[lr["order_no"]]
            line_insert.append({
                "order_id": oid, "line_no": lr["line_no"], "item_code": lr["item_code"],
                "item_name": lr["item_name"], "category": lr["category"],
                "expected_delivery_date": lr["expected_delivery_date"],
                "quantity": lr["quantity"], "unit": "件", "unit_price": lr["unit_price"],
                "tax_rate": Decimal("0"), "amount": lr["amount"],
                "received_qty": Decimal("0"), "invoiced_qty": Decimal("0"),
            })
        await conn.execute(text(
            "INSERT INTO purchase_order_lines (id, order_id, line_no, item_code, item_name, "
            "category, expected_delivery_date, quantity, unit, unit_price, tax_rate, amount, "
            "received_qty, invoiced_qty) "
            "VALUES (gen_random_uuid(), :order_id, :line_no, :item_code, :item_name, :category, "
            ":expected_delivery_date, :quantity, :unit, :unit_price, :tax_rate, :amount, "
            ":received_qty, :invoiced_qty)"
        ), line_insert)

        # 更新订单总额（按明细求和）
        await conn.execute(text(
            "UPDATE purchase_orders po SET total_amount = COALESCE(("
            "SELECT SUM(pol.amount) FROM purchase_order_lines pol WHERE pol.order_id = po.id"
            "), 0)"
        ))

        # 3. 收货 + 发票（逐明细，70% 收货，60% 收货开票）
        line_ids = list((await conn.execute(text(
            "SELECT pol.id, pol.order_id, pol.quantity, pol.unit_price, po.order_date, "
            "po.supplier_id, po.status, pol.expected_delivery_date "
            "FROM purchase_order_lines pol JOIN purchase_orders po ON po.id = pol.order_id"
        ))).all())

        receipt_rows = []
        receipt_line_rows = []
        invoice_rows = []
        invoice_line_rows = []
        received_updates = []
        invoiced_updates = []
        order_status_updates = {}

        receipt_seq = 1
        invoice_seq = 1
        for (lid, oid, qty, price, odate, sid, ostatus, due) in line_ids:
            if ostatus == "cancelled":
                continue
            if rng.random() > 0.7:
                continue  # 30% 无收货

            full = rng.random() > 0.3
            recv_qty = qty if full else Decimal(str(rng.randint(1, max(1, int(qty) - 1))))

            base = odate + timedelta(days=rng.randint(3, 12))
            if due and rng.random() < 0.3:
                base = due + timedelta(days=rng.randint(1, 10))  # 延期
            rdate = base

            rno = f"GR-{receipt_seq:07d}"
            receipt_seq += 1
            ramt = (recv_qty * price).quantize(Decimal("0.01"))
            receipt_rows.append({
                "receipt_no": rno, "order_id": oid, "supplier_id": sid,
                "receipt_date": rdate, "status": "posted",
                "total_quantity": recv_qty, "total_amount": ramt, "remark": None,
            })
            receipt_line_rows.append({
                "receipt_no": rno, "order_line_id": lid, "line_no": 1,
                "quantity": recv_qty, "unit_price": price, "amount": ramt,
            })
            received_updates.append({"line_id": lid, "recv_qty": recv_qty})

            # 60% 收货开票
            if rng.random() <= 0.6:
                inv_qty = recv_qty
                tax_rate = Decimal("0.13")
                pre = False
                idate = odate + timedelta(days=rng.randint(5, 25))
                if rng.random() < 0.2:
                    idate = rdate - timedelta(days=rng.randint(1, 5))  # 提前开票
                    pre = True
                ino = f"INV-{invoice_seq:07d}"
                invoice_seq += 1
                amt = line_amount(inv_qty, price)
                tax = (amt * tax_rate).quantize(Decimal("0.01"))
                invoice_rows.append({
                    "invoice_no": ino, "order_id": oid, "supplier_id": sid,
                    "invoice_date": idate, "status": "pending_verification" if pre else "posted",
                    "currency": "CNY", "total_amount": amt, "tax_amount": tax, "remark": None,
                })
                invoice_line_rows.append({
                    "invoice_no": ino, "order_line_id": lid, "line_no": 1,
                    "item_name": f"物料{rng.randint(1, 99999)}", "quantity": inv_qty,
                    "unit_price": price, "amount": amt,
                })
                invoiced_updates.append({"line_id": lid, "inv_qty": inv_qty})

        # 插入收货
        if receipt_rows:
            await conn.execute(text(
                "INSERT INTO goods_receipts (id, receipt_no, order_id, supplier_id, receipt_date, "
                "status, total_quantity, total_amount, remark, created_at) "
                "VALUES (gen_random_uuid(), :receipt_no, :order_id, :supplier_id, :receipt_date, "
                ":status, :total_quantity, :total_amount, NULL, now())"
            ), receipt_rows)
            rid_by_no = dict((await conn.execute(text(
                "SELECT receipt_no, id FROM goods_receipts"
            ))).all())
            rl_insert = [{
                "receipt_id": rid_by_no[r["receipt_no"]], "order_line_id": r["order_line_id"],
                "line_no": 1, "quantity": r["quantity"], "unit_price": r["unit_price"],
                "amount": r["amount"],
            } for r in receipt_line_rows]
            await conn.execute(text(
                "INSERT INTO goods_receipt_lines (id, receipt_id, order_line_id, line_no, "
                "quantity, unit_price, amount) "
                "VALUES (gen_random_uuid(), :receipt_id, :order_line_id, :line_no, :quantity, "
                ":unit_price, :amount)"
            ), rl_insert)

        # 插入发票
        if invoice_rows:
            await conn.execute(text(
                "INSERT INTO purchase_invoices (id, invoice_no, order_id, supplier_id, invoice_date, "
                "status, currency, total_amount, tax_amount, remark, created_at) "
                "VALUES (gen_random_uuid(), :invoice_no, :order_id, :supplier_id, :invoice_date, "
                ":status, 'CNY', :total_amount, :tax_amount, NULL, now())"
            ), invoice_rows)
            iid_by_no = dict((await conn.execute(text(
                "SELECT invoice_no, id FROM purchase_invoices"
            ))).all())
            il_insert = [{
                "invoice_id": iid_by_no[i["invoice_no"]], "order_line_id": i["order_line_id"],
                "line_no": 1, "item_name": i["item_name"], "quantity": i["quantity"],
                "unit_price": i["unit_price"], "amount": i["amount"],
            } for i in invoice_line_rows]
            await conn.execute(text(
                "INSERT INTO purchase_invoice_lines (id, invoice_id, order_line_id, line_no, "
                "item_name, quantity, unit_price, amount) "
                "VALUES (gen_random_uuid(), :invoice_id, :order_line_id, :line_no, :item_name, "
                ":quantity, :unit_price, :amount)"
            ), il_insert)

        # 更新累计收货/开票数量（用 SQL 聚合，避免逐行更新）
        await conn.execute(text(
            "UPDATE purchase_order_lines pol SET received_qty = COALESCE(("
            "SELECT SUM(grl.quantity) FROM goods_receipt_lines grl WHERE grl.order_line_id = pol.id"
            "), 0)"
        ))
        await conn.execute(text(
            "UPDATE purchase_order_lines pol SET invoiced_qty = COALESCE(("
            "SELECT SUM(pil.quantity) FROM purchase_invoice_lines pil WHERE pil.order_line_id = pol.id"
            "), 0)"
        ))
        # 更新订单状态（按是否收满）
        await conn.execute(text(
            "UPDATE purchase_orders po SET status = CASE "
            "WHEN status = 'cancelled' THEN 'cancelled' "
            "WHEN (SELECT COUNT(*) FROM purchase_order_lines pol WHERE pol.order_id = po.id "
            "      AND pol.received_qty < pol.quantity) = 0 "
            "     AND (SELECT COUNT(*) FROM purchase_order_lines pol WHERE pol.order_id = po.id) > 0 "
            "THEN 'received' "
            "WHEN (SELECT COUNT(*) FROM purchase_order_lines pol WHERE pol.order_id = po.id "
            "      AND pol.received_qty > 0) > 0 THEN 'partially_received' "
            "ELSE 'submitted' END"
        ))

    elapsed = time.time() - t0

    # 统计
    async with engine.connect() as conn:
        counts = {}
        for t in ("suppliers", "purchase_orders", "purchase_order_lines",
                  "goods_receipts", "goods_receipt_lines",
                  "purchase_invoices", "purchase_invoice_lines"):
            counts[t] = (await conn.execute(text(f"SELECT count(*) FROM {t}"))).scalar()
        size = (await conn.execute(text(
            "SELECT pg_size_pretty(pg_database_size(current_database()))"
        ))).scalar()

    await engine.dispose()
    return {"elapsed": elapsed, "counts": counts, "db_size": size}


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--orders", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20261105)
    parser.add_argument("--suppliers", type=int, default=50)
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("错误：请设置 DATABASE_URL 环境变量指向专用性能库（如 spendops_perf）。", file=sys.stderr)
        return 2
    stats = await generate(db_url, args.orders, args.seed, args.suppliers)
    print(f"规模：{args.orders} 订单，种子 {args.seed}，{args.suppliers} 供应商")
    print(f"生成耗时：{stats['elapsed']:.2f}s")
    print("各表记录数：")
    for k, v in stats["counts"].items():
        print(f"  {k}: {v}")
    print(f"数据库体积：{stats['db_size']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
