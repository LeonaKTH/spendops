"""G5 受控问数：意图解析单元测试（无数据库依赖）。"""

from __future__ import annotations

from datetime import date

from app.services import analysis

SUPPLIERS = [
    {"id": "id-1", "code": "SUP-01", "name": "华东电子"},
    {"id": "id-2", "code": "SUP-02", "name": "华南精密"},
]

TODAY = date(2026, 11, 5)


def _parse(q):
    return analysis.parse_intent(q, SUPPLIERS, TODAY)


def test_overview_intent_default_year():
    i = _parse("采购订单金额是多少？")
    assert i["intent"] == analysis.INTENT_OVERVIEW
    assert i["start"] == date(2026, 1, 1)
    assert i["end"] == date(2026, 12, 31)
    assert i["timeNote"] is not None  # 未指定时间，标注默认


def test_supplier_ranking_intent():
    i = _parse("哪些供应商采购金额最高？")
    assert i["intent"] == analysis.INTENT_SUPPLIER_RANKING


def test_recent_n_months_chinese_numeral():
    i = _parse("最近三个月哪些供应商采购金额最高？")
    assert i["start"] == date(2026, 8, 1)
    assert i["end"] == TODAY


def test_supplier_trend_by_name():
    i = _parse("华东电子今年采购金额变化如何？")
    assert i["intent"] == analysis.INTENT_SUPPLIER_TREND
    assert i["supplier"]["name"] == "华东电子"


def test_delivery_intent():
    assert _parse("哪些订单存在交付延期？")["intent"] == analysis.INTENT_DELIVERY


def test_pending_invoice_intent():
    assert _parse("当前有多少待核对发票？")["intent"] == analysis.INTENT_PENDING_INVOICES


def test_discrepancy_intent():
    assert _parse("哪些订单存在收货与开票差异？")["intent"] == analysis.INTENT_DISCREPANCIES


def test_specific_month():
    i = _parse("2026年3月采购金额为什么变化？")
    assert i["start"] == date(2026, 3, 1)
    assert i["end"] == date(2026, 3, 31)


def test_top_n_parsed():
    i = _parse("排名前5的供应商")
    assert i["topN"] == 5


def test_top_n_clamped():
    i = _parse("排名前999的供应商")
    assert i["topN"] == 50


def test_unknown_supplier_ignored():
    # 未提及具体供应商名（泛化「供应商」），允许整体趋势。
    i = _parse("供应商整体的采购金额变化如何？")
    assert i["supplier"] is None
    assert i["intent"] == analysis.INTENT_MONTHLY_TREND


def test_named_supplier_not_found_flagged():
    """明确指定某供应商但未找到：标记 supplierUnmatched，由上层澄清而非静默降级。"""
    i = _parse("某某科技今年采购金额变化如何？")
    assert i["supplierUnmatched"] is True
    assert i["supplier"] is None


def test_ambiguous_supplier_flagged():
    """多个供应商匹配时标记歧义。"""
    sup = [
        {"id": "a", "code": "SUP-1", "name": "甲"},
        {"id": "b", "code": "SUP-12", "name": "乙"},
    ]
    i = analysis.parse_intent("SUP-12 的采购金额变化如何？", sup, TODAY)
    assert i["supplierAmbiguous"] is True
    assert i["supplier"] is None


def test_exact_supplier_code_no_ambiguity():
    sup = [
        {"id": "a", "code": "SUP-1", "name": "甲"},
        {"id": "b", "code": "SUP-12", "name": "乙"},
    ]
    i = analysis.parse_intent("SUP-1 的采购金额变化如何？", sup, TODAY)
    # 「SUP-1」在问题中不包含「SUP-12」，仅匹配一个供应商。
    assert i["supplierAmbiguous"] is False
    assert i["supplier"] is not None and i["supplier"]["code"] == "SUP-1"
