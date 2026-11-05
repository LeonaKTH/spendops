"""G2 数据接入单元测试：文件解析、字段映射、值校验、Decimal 精度。"""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal

import pytest

from app.services.importing.mappings import auto_map, get_fields, match_field
from app.services.importing.parse import parse_tabular
from app.services.importing.validate import parse_date, parse_decimal, validate_row


# ---------------------------------------------------------------- 解析

def test_parse_csv_utf8_chinese_columns():
    content = "供应商编码,供应商名称,联系人\nS001,供应商甲,张三\nS002,供应商乙,李四\n".encode("utf-8")
    headers, rows = parse_tabular("s.csv", content)
    assert headers == ["供应商编码", "供应商名称", "联系人"]
    assert len(rows) == 2
    assert rows[0]["供应商编码"] == "S001"
    assert rows[0]["供应商名称"] == "供应商甲"


def test_parse_csv_gbk_encoding():
    content = "供应商编码,供应商名称\nS001,供应商甲\n".encode("gbk")
    headers, rows = parse_tabular("s.csv", content)
    assert rows[0]["供应商名称"] == "供应商甲"


def test_parse_csv_utf8_bom():
    content = b"\xef\xbb\xbf\xe4\xbe\x9b\xe5\xba\x94\xe5\x95\x86,\xe5\x90\x8d\xe7\xa7\xb0\nS001,\xe7\x94\xb2\n"
    headers, rows = parse_tabular("s.csv", content)
    assert headers[0] == "供应商"
    assert rows[0]["供应商"] == "S001"


def test_parse_skips_blank_rows():
    content = "供应商编码,供应商名称\nS001,甲\n\nS002,乙\n".encode("utf-8")
    _headers, rows = parse_tabular("s.csv", content)
    assert len(rows) == 2  # 全空行被跳过


def test_parse_xlsx_chinese():
    import pandas as pd

    frame = pd.DataFrame({"物料编码": ["A1", "A2"], "数量": [10, 20], "单价": ["1.50", "2.25"]})
    buf = io.BytesIO()
    frame.to_excel(buf, index=False)
    headers, rows = parse_tabular("po.xlsx", buf.getvalue())
    assert headers == ["物料编码", "数量", "单价"]
    assert rows[0]["单价"] == "1.5" or rows[0]["单价"] == "1.50"


def test_parse_rejects_unknown_extension():
    with pytest.raises(ValueError):
        parse_tabular("x.pdf", b"not a table")


# ---------------------------------------------------------------- 值校验

def test_parse_decimal_preserves_precision():
    # Decimal 精度：0.1 不丢失为 float
    assert parse_decimal("0.1") == Decimal("0.1")
    assert parse_decimal("123.45") == Decimal("123.45")
    assert parse_decimal("1,234.56") == Decimal("1234.56")
    assert parse_decimal("¥99.90") == Decimal("99.90")
    assert parse_decimal("￥1,000.00") == Decimal("1000.00")


def test_parse_decimal_sum_exact():
    # 关键：0.1 + 0.2 必须精确为 0.3，而非 float 误差
    total = parse_decimal("0.1") + parse_decimal("0.2")
    assert total == Decimal("0.3")


def test_parse_decimal_invalid_returns_none():
    assert parse_decimal("abc") is None
    assert parse_decimal("") is None
    assert parse_decimal(None) is None


def test_parse_date_formats():
    assert parse_date("2026-01-15") == date(2026, 1, 15)
    assert parse_date("2026/01/15") == date(2026, 1, 15)
    assert parse_date("2026年1月15日") == date(2026, 1, 15)
    assert parse_date("2026-1-5") == date(2026, 1, 5)
    assert parse_date("abc") is None
    assert parse_date("") is None


# ---------------------------------------------------------------- 映射

def test_auto_map_chinese_columns():
    headers = ["供应商编码", "供应商名称", "联系人", "备注"]
    mapping = auto_map(headers, "supplier")
    assert mapping["供应商编码"] == "code"
    assert mapping["供应商名称"] == "name"
    assert mapping["联系人"] == "contact_name"
    assert mapping["备注"] == "remark"


def test_auto_map_order_columns():
    headers = ["采购订单号", "供应商编码", "下单日期", "物料编码", "物料名称", "数量", "单价"]
    mapping = auto_map(headers, "purchase_order")
    assert mapping["采购订单号"] == "order_no"
    assert mapping["下单日期"] == "order_date"
    assert mapping["物料编码"] == "item_code"
    assert mapping["数量"] == "quantity"
    assert mapping["单价"] == "unit_price"


def test_match_field_contains_alias():
    fields = get_fields("supplier")
    # 列名包含别名也能匹配
    assert match_field("供应商编码（唯一）", fields).key == "code"


# ---------------------------------------------------------------- 行校验

def test_validate_row_required_missing():
    fields = get_fields("supplier")
    mapping = {"供应商编码": "code", "供应商名称": "name"}
    mapped, errors = validate_row({"供应商编码": "S001", "供应商名称": None}, mapping, fields)
    assert any(e.error_type == "missing_required" and e.field == "name" for e in errors)


def test_validate_row_decimal_invalid():
    fields = get_fields("purchase_order")
    mapping = {"数量": "quantity", "单价": "unit_price"}
    mapped, errors = validate_row({"数量": "abc", "单价": "10"}, mapping, fields)
    assert any(e.error_type == "invalid_format" and e.field == "quantity" for e in errors)


def test_validate_row_decimal_values():
    fields = get_fields("purchase_order")
    mapping = auto_map(
        ["采购订单号", "供应商编码", "下单日期", "物料编码", "物料名称", "数量", "单价"],
        "purchase_order",
    )
    raw = {
        "采购订单号": "PO-1", "供应商编码": "S001", "下单日期": "2026-01-01",
        "物料编码": "A1", "物料名称": "物料A", "数量": "10", "单价": "1.50",
    }
    mapped, errors = validate_row(raw, mapping, fields)
    assert not errors
    assert mapped["quantity"] == Decimal("10")
    assert mapped["unit_price"] == Decimal("1.50")
