"""SpendOps 采购领域纯单元测试（不依赖数据库）。

覆盖：金额计算（Decimal 精度）、状态常量、明细金额与汇总。
"""

from __future__ import annotations

from decimal import Decimal

from app.services.purchasing.domain import (
    line_amount,
    money,
    qty,
    total_amount,
)


def test_money_rounds_half_up_to_cent():
    assert money("1.005") == Decimal("1.01")  # 四舍五入到分
    assert money("1.004") == Decimal("1.00")
    assert money("0.1") == Decimal("0.10")


def test_line_amount_multiplies_quantity_by_price():
    # 100 件 × 1.2345 元 = 123.45 元
    assert line_amount(Decimal("100"), Decimal("1.2345")) == Decimal("123.45")


def test_line_amount_uses_decimal_not_float():
    # 0.1 + 0.2 的浮点陷阱在 Decimal 下不成立
    assert line_amount(Decimal("0.1"), Decimal("1")) == Decimal("0.10")
    assert line_amount(Decimal("0.2"), Decimal("1")) == Decimal("0.20")


def test_line_amount_with_fractional_quantity():
    # 1.5 公斤 × 20.00 元 = 30.00 元
    assert line_amount(Decimal("1.5"), Decimal("20.00")) == Decimal("30.00")


def test_total_amount_sums_lines():
    assert total_amount([Decimal("1.10"), Decimal("2.20"), Decimal("3.30")]) == Decimal("6.60")


def test_total_amount_empty_is_zero():
    assert total_amount([]) == Decimal("0.00")


def test_qty_rounds_to_three_decimals():
    assert qty("1.2345") == Decimal("1.235")
    assert qty("1.2344") == Decimal("1.234")


def test_request_fingerprint_is_stable_and_order_independent():
    from app.services.purchasing.idempotency import request_fingerprint

    a = request_fingerprint({"code": "S001", "name": "供应商", "contact_name": "张三"})
    b = request_fingerprint({"name": "供应商", "code": "S001", "contact_name": "张三"})
    c = request_fingerprint({"code": "S001", "name": "供应商", "contact_name": "李四"})
    assert a == b  # 字段顺序无关
    assert a != c  # 内容不同指纹不同
