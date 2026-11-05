"""SpendOps G2 字段映射与校验定义。

为四类采购业务数据定义「中文列名 -> 业务字段」的映射规则，以及每个字段的
类型、必填性与校验方式。自动映射按列名精确/包含匹配别名；映射结果与错误
统一进入暂存表，前端可展示与确认。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.db.importing import (
    IMPORT_GOODS_RECEIPT,
    IMPORT_PURCHASE_INVOICE,
    IMPORT_PURCHASE_ORDER,
    IMPORT_SUPPLIER,
)

# 字段类型。
KIND_TEXT = "text"
KIND_DATE = "date"
KIND_DECIMAL = "decimal"
KIND_INT = "int"


@dataclass(frozen=True)
class FieldDef:
    key: str                      # 业务字段名（snake_case）
    aliases: tuple[str, ...]      # 中文列名别名（用于自动映射）
    required: bool = False
    kind: str = KIND_TEXT
    is_group_key: bool = False    # 是否为分组键（如 order_no，用于聚合成单据）


def _f(key: str, aliases: tuple[str, ...], *, required=False, kind=KIND_TEXT, group=False) -> FieldDef:
    return FieldDef(key=key, aliases=aliases, required=required, kind=kind, is_group_key=group)


# 供应商
SUPPLIER_FIELDS = [
    _f("code", ("供应商编码", "供应商代码", "编码", "供应商编号", "code"), required=True),
    _f("name", ("供应商名称", "名称", "供应商", "name"), required=True),
    _f("contact_name", ("联系人", "联系人姓名", "contact_name")),
    _f("contact_phone", ("联系电话", "电话", "手机", "contact_phone")),
    _f("email", ("邮箱", "电子邮箱", "email")),
    _f("address", ("地址", "供应商地址", "address")),
    _f("remark", ("备注", "说明", "remark")),
]

# 采购订单（宽表：每行一个明细，按 order_no 聚合）
PURCHASE_ORDER_FIELDS = [
    _f("order_no", ("采购订单号", "订单号", "采购单号", "order_no"), required=True, group=True),
    _f("supplier_code", ("供应商编码", "供应商代码", "供应商编号", "supplier_code"), required=True),
    _f("order_date", ("下单日期", "订单日期", "采购日期", "order_date"), required=True, kind=KIND_DATE),
    _f("item_code", ("物料编码", "物料代码", "物品编码", "item_code"), required=True),
    _f("item_name", ("物料名称", "物品名称", "品名", "item_name"), required=True),
    _f("category", ("品类", "物料品类", "物料类别", "分类", "category")),
    _f("expected_delivery_date", ("约定交期", "约定交货日期", "交货日期", "交期", "expected_delivery_date"), kind=KIND_DATE),
    _f("quantity", ("数量", "采购数量", "quantity"), required=True, kind=KIND_DECIMAL),
    _f("unit", ("单位", "计量单位", "unit")),
    _f("unit_price", ("单价", "采购单价", "unit_price"), required=True, kind=KIND_DECIMAL),
    _f("tax_rate", ("税率", "增值税率", "tax_rate"), kind=KIND_DECIMAL),
    _f("remark", ("备注", "说明", "remark")),
]

# 收货记录（宽表：每行一个收货明细，按 receipt_no 聚合，用 order_no+item_code 定位明细）
GOODS_RECEIPT_FIELDS = [
    _f("receipt_no", ("收货单号", "收货单编号", "receipt_no"), required=True, group=True),
    _f("order_no", ("采购订单号", "订单号", "关联订单号", "order_no"), required=True),
    _f("item_code", ("物料编码", "物料代码", "物品编码", "item_code"), required=True),
    _f("receipt_date", ("收货日期", "到货日期", "receipt_date"), required=True, kind=KIND_DATE),
    _f("quantity", ("收货数量", "数量", "quantity"), required=True, kind=KIND_DECIMAL),
    _f("remark", ("备注", "说明", "remark")),
]

# 采购发票（宽表：每行一个发票明细，按 invoice_no 聚合）
PURCHASE_INVOICE_FIELDS = [
    _f("invoice_no", ("发票号", "发票号码", "invoice_no"), required=True, group=True),
    _f("order_no", ("采购订单号", "订单号", "关联订单号", "order_no")),
    _f("supplier_code", ("供应商编码", "供应商代码", "供应商编号", "supplier_code"), required=True),
    _f("invoice_date", ("开票日期", "发票日期", "invoice_date"), required=True, kind=KIND_DATE),
    _f("item_name", ("物料名称", "物品名称", "品名", "item_name"), required=True),
    _f("quantity", ("数量", "开票数量", "quantity"), required=True, kind=KIND_DECIMAL),
    _f("unit_price", ("单价", "含税单价", "unit_price"), required=True, kind=KIND_DECIMAL),
    _f("tax_rate", ("税率", "增值税率", "tax_rate"), kind=KIND_DECIMAL),
    _f("remark", ("备注", "说明", "remark")),
]


FIELD_SETS: dict[str, list[FieldDef]] = {
    IMPORT_SUPPLIER: SUPPLIER_FIELDS,
    IMPORT_PURCHASE_ORDER: PURCHASE_ORDER_FIELDS,
    IMPORT_GOODS_RECEIPT: GOODS_RECEIPT_FIELDS,
    IMPORT_PURCHASE_INVOICE: PURCHASE_INVOICE_FIELDS,
}


def get_fields(task_type: str) -> list[FieldDef]:
    if task_type not in FIELD_SETS:
        raise ValueError(f"未知的导入类型：{task_type}")
    return FIELD_SETS[task_type]


def match_field(column_name: str, fields: list[FieldDef]) -> FieldDef | None:
    """按列名匹配字段：先精确匹配别名，再包含匹配（列名含别名）。"""
    normalized = str(column_name).strip()
    if not normalized:
        return None
    lowered = normalized.lower()
    for f in fields:
        for alias in f.aliases:
            if lowered == alias.lower():
                return f
    for f in fields:
        for alias in f.aliases:
            if alias.lower() in lowered:
                return f
    return None


def auto_map(headers: list[str], task_type: str) -> dict[str, str]:
    """自动映射：返回 {列名 -> 业务字段 key}。无法匹配的列忽略。"""
    fields = get_fields(task_type)
    mapping: dict[str, str] = {}
    for header in headers:
        matched = match_field(header, fields)
        if matched is not None and matched.key not in mapping.values():
            mapping[header] = matched.key
    return mapping
