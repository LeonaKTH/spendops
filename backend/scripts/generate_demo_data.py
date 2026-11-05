"""SpendOps G3 合成业务数据生成脚本（演示库）。

生成一套真实关系的采购数据：多供应商、多订单、多收货、多发票，覆盖 6 个月，
包含部分收货、延期交付、提前开票、取消订单、跨月交付等场景。

数据严格符合 G1/G2 业务规则：金额用 domain.line_amount（Decimal），
状态正确，约束满足，received_qty/invoiced_qty 与收货/发票一致。

随机种子固定，可复现。用法：python scripts/generate_demo_data.py [--reset]
"""

from __future__ import annotations

import asyncio
import random
import sys
from datetime import date, timedelta
from decimal import Decimal

# 把 backend 目录加入 sys.path，使脚本可从任意位置运行。
import os

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
from app.db.session import SessionLocal  # noqa: E402
from app.services.purchasing.domain import (  # noqa: E402
    ORDER_CANCELLED,
    ORDER_PARTIALLY_RECEIVED,
    ORDER_RECEIVED,
    ORDER_SUBMITTED,
    line_amount,
    money,
)

# 清空业务库需 DDL 权限。为安全，重置连接必须由环境变量显式提供，
# 不设默认值、不硬编码任何数据库密码；且只允许清空专用库（_demo/_test/_perf 结尾）。
RESET_URL = os.environ.get("SPENDOPS_RESET_URL", "")

_ALLOWED_RESET_SUFFIXES = ("_demo", "_test", "_perf")
_FORBIDDEN_DB = ("spendops", "spendops_test", "postgres")


def _validate_reset_target(url: str) -> str:
    """校验清空目标：必须是明确指定的专用库，防止误清生产/演示数据。"""
    from urllib.parse import urlparse

    db_name = urlparse(url).path.lstrip("/")
    if not db_name:
        raise ValueError("SPENDOPS_RESET_URL 缺少数据库名。")
    if db_name in _FORBIDDEN_DB:
        raise ValueError(
            f"拒绝清空数据库「{db_name}」：这是受保护的主/演示/自动化测试库。"
        )
    if not db_name.endswith(_ALLOWED_RESET_SUFFIXES):
        raise ValueError(
            f"拒绝清空数据库「{db_name}」：库名必须以 _demo/_test/_perf 结尾，"
            "这是防止误清其他项目数据库的保护。"
        )
    return db_name

SEED = 20261105
CATEGORIES = ["电子", "机械", "办公", "原材料", "包装"]
SUPPLIERS = [
    ("SUP-01", "华东电子", "电子"),
    ("SUP-02", "华南精密", "机械"),
    ("SUP-03", "京华办公", "办公"),
    ("SUP-04", "北方原料", "原材料"),
    ("SUP-05", "绿源包装", "包装"),
    ("SUP-06", "中州机电", "机械"),
    ("SUP-07", "东海元件", "电子"),
    ("SUP-08", "西岭材料", "原材料"),
]


async def _seed_suppliers(rng, session):
    suppliers = []
    for code, name, cat in SUPPLIERS:
        s = Supplier(code=code, name=name, status="active")
        session.add(s)
        suppliers.append((s, cat))
    await session.flush()
    return suppliers


async def _gen(session, rng) -> dict:
    suppliers = await _seed_suppliers(rng, session)

    orders = []
    order_lines = []
    receipts = []
    invoices = []

    # 6 个月：2026-01 ~ 2026-06
    order_seq = 1
    receipt_seq = 1
    invoice_seq = 1

    for month in range(1, 7):
        # 每月 6~9 个订单
        n_orders = rng.randint(6, 9)
        for _ in range(n_orders):
            supplier, default_cat = rng.choice(suppliers)
            order_date = date(2026, month, rng.randint(1, 28))
            n_lines = rng.randint(1, 3)

            po = PurchaseOrder(
                order_no=f"PO-{order_seq:04d}",
                supplier_id=supplier.id,
                supplier=supplier,
                order_date=order_date,
                status=ORDER_SUBMITTED,
                currency="CNY",
                remark=None,
            )
            session.add(po)
            order_seq += 1

            amount_list = []
            lines = []
            for li in range(1, n_lines + 1):
                item_code = f"ITEM-{rng.randint(1000, 9999)}"
                item_name = f"物料{order_seq-1}-{li}"
                quantity = Decimal(str(rng.randint(1, 50)))
                unit_price = Decimal(str(rng.randint(10, 2000))) / Decimal("10")
                category = default_cat if rng.random() < 0.85 else rng.choice(CATEGORIES)
                # 20% 明细不设约定交期
                due = None
                if rng.random() >= 0.2:
                    due = order_date + timedelta(days=rng.randint(5, 20))
                amount = line_amount(quantity, unit_price)
                amount_list.append(amount)
                line = PurchaseOrderLine(
                    order_id=po.id, line_no=li, item_code=item_code, item_name=item_name,
                    category=category, expected_delivery_date=due,
                    quantity=quantity, unit="件", unit_price=unit_price,
                    tax_rate=Decimal("0"), amount=amount,
                    received_qty=Decimal("0"), invoiced_qty=Decimal("0"),
                )
                session.add(line)
                lines.append(line)
            po.total_amount = sum(amount_list, Decimal("0"))
            po.lines = lines
            orders.append(po)
            order_lines.extend(lines)

    await session.flush()

    # 为每个订单明细生成收货（70% 概率，部分收货、延期、跨月）
    for line in order_lines:
        if rng.random() > 0.7:
            continue  # 30% 无收货
        po = next(o for o in orders if o.id == line.order_id)
        if rng.random() < 0.05:
            po.status = ORDER_CANCELLED
            continue  # 5% 取消订单（无收货）

        # 是否部分收货
        full = rng.random() > 0.3
        receive_qty = line.quantity if full else Decimal(str(rng.randint(1, max(1, int(line.quantity) - 1))))

        # 收货日期：交期前后浮动（延期/及时），跨月
        base = po.order_date + timedelta(days=rng.randint(3, 12))
        if line.expected_delivery_date and rng.random() < 0.3:
            # 30% 延期：交期之后 1~10 天
            base = line.expected_delivery_date + timedelta(days=rng.randint(1, 10))
        receipt_date = base

        gr = GoodsReceipt(
            receipt_no=f"GR-{receipt_seq:04d}",
            order_id=po.id, supplier_id=po.supplier_id, order=po, supplier=po.supplier,
            receipt_date=receipt_date, status="posted",
            total_quantity=receive_qty,
            total_amount=money(receive_qty * line.unit_price),
        )
        gr.lines = [GoodsReceiptLine(
            order_line_id=line.id, line_no=1, quantity=receive_qty,
            unit_price=line.unit_price, amount=money(receive_qty * line.unit_price),
        )]
        session.add(gr)
        receipt_seq += 1
        receipts.append(gr)
        line.received_qty = receive_qty

        # 更新订单状态
        if po.status != ORDER_CANCELLED:
            all_received = all(l.received_qty >= l.quantity for l in po.lines)
            po.status = ORDER_RECEIVED if all_received else ORDER_PARTIALLY_RECEIVED

    await session.flush()

    # 为已收货明细生成发票（60% 概率，部分提前开票）
    for line in order_lines:
        if line.received_qty <= 0 or rng.random() > 0.6:
            continue
        po = next(o for o in orders if o.id == line.order_id)
        invoice_qty = line.received_qty
        tax_rate = Decimal("0.13")
        invoice_date = po.order_date + timedelta(days=rng.randint(5, 25))

        # 提前开票：开票日期早于收货日期
        receipt = next((r for r in receipts if r.order_id == po.id), None)
        pre_invoiced = False
        if receipt and rng.random() < 0.25:
            invoice_date = receipt.receipt_date - timedelta(days=rng.randint(1, 5))
            pre_invoiced = True

        amount = line_amount(invoice_qty, line.unit_price)
        tax = money(amount * tax_rate)
        inv = PurchaseInvoice(
            invoice_no=f"INV-{invoice_seq:04d}",
            order_id=po.id, supplier_id=po.supplier_id, order=po, supplier=po.supplier,
            invoice_date=invoice_date,
            status="pending_verification" if pre_invoiced else "posted",
            currency="CNY", total_amount=amount, tax_amount=tax,
        )
        inv.lines = [PurchaseInvoiceLine(
            order_line_id=line.id, line_no=1, item_name=line.item_name,
            quantity=invoice_qty, unit_price=line.unit_price, amount=amount,
        )]
        session.add(inv)
        invoice_seq += 1
        invoices.append(inv)
        line.invoiced_qty = invoice_qty

    await session.commit()
    return {
        "suppliers": len(suppliers),
        "orders": len([o for o in orders if o.status != ORDER_CANCELLED]),
        "cancelled": len([o for o in orders if o.status == ORDER_CANCELLED]),
        "receipts": len(receipts),
        "invoices": len(invoices),
        "pre_invoiced": len([i for i in invoices if i.status == "pending_verification"]),
    }


async def main(reset: bool, confirmed: bool) -> int:
    if reset:
        if not confirmed:
            raise ValueError("--reset 是破坏性操作，必须同时传 --yes 确认。")
        if not RESET_URL:
            raise ValueError(
                "--reset 需要显式设置 SPENDOPS_RESET_URL（专用库连接串）。"
                "为安全不提供默认值、不硬编码数据库密码。"
            )
        db_name = _validate_reset_target(RESET_URL)
        engine = create_async_engine(RESET_URL)
        async with engine.begin() as conn:
            await conn.execute(text(
                "TRUNCATE purchase_invoices, purchase_invoice_lines, goods_receipts, "
                "goods_receipt_lines, purchase_orders, purchase_order_lines, suppliers CASCADE"
            ))
        await engine.dispose()
        print(f"已清空专用库 {db_name} 的采购表。")

    async with SessionLocal() as session:
        rng = random.Random(SEED)
        stats = await _gen(session, rng)
    print("合成数据生成完成（随机种子 %d）：" % SEED)
    for k, v in stats.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--reset" in sys.argv, "--yes" in sys.argv)))
