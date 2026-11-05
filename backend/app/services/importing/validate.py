"""SpendOps G2 字段映射与值校验。

把原始行按字段映射转换为业务字段值，并对每个字段做类型/必填校验。
校验失败产出行级错误（含字段名、错误类型、修复建议），不静默跳过。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.importing.errors import (
    ERR_INVALID_FORMAT,
    ERR_MISSING_REQUIRED,
    RowError,
)
from app.services.importing.mappings import (
    KIND_DATE,
    KIND_DECIMAL,
    KIND_INT,
    FieldDef,
)

_CURRENCY_CHARS = "¥￥$€£,"


def to_json_compatible(value):
    """把 Python 对象转为 JSONB 可序列化值（date/Decimal -> 字符串）。"""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def mapped_to_json(mapped: dict[str, Any]) -> dict[str, Any]:
    return {k: to_json_compatible(v) for k, v in mapped.items()}


def parse_decimal(value: str | None) -> Decimal | None:
    """解析金额/数量为 Decimal。支持货币符号、千分位逗号。失败返回 None。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for ch in _CURRENCY_CHARS:
        text = text.replace(ch, "")
    text = text.strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def parse_date(value: str | None) -> date | None:
    """解析日期：支持 YYYY-MM-DD、YYYY/MM/DD、YYYY年MM月DD日、Excel 数字日期。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Excel 序列日期（纯数字，如 45678）
    if text.isdigit() and len(text) >= 5:
        try:
            return _excel_serial_to_date(int(text))
        except (ValueError, OverflowError):
            return None
    normalized = (
        text.replace("年", "-").replace("月", "-").replace("日", "")
        .replace("/", "-").replace(".", "-")
    )
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue
    return None


def _excel_serial_to_date(serial: int) -> date:
    """Excel 日期序列号（1900 起）转 date。"""
    from datetime import timedelta

    base = date(1899, 12, 30)
    if serial < 60:
        # 1900 闰年 bug 之前的日期。
        base = date(1899, 12, 31)
    return base + timedelta(days=serial)


def parse_value(field: FieldDef, value: str | None):
    """按字段类型解析值。解析失败抛出 ValueError（由调用方转为行级错误）。"""
    if value is None:
        return None
    if field.kind == KIND_DATE:
        parsed = parse_date(value)
        if parsed is None:
            raise ValueError(f"无法解析日期「{value}」，请使用 YYYY-MM-DD 格式。")
        return parsed
    if field.kind == KIND_DECIMAL:
        parsed = parse_decimal(value)
        if parsed is None:
            raise ValueError(f"无法解析数字「{value}」。")
        return parsed
    if field.kind == KIND_INT:
        parsed = parse_int(value)
        if parsed is None:
            raise ValueError(f"无法解析整数「{value}」。")
        return parsed
    return str(value).strip()


def validate_row(
    raw_row: dict[str, Any],
    mapping: dict[str, str],
    fields: list[FieldDef],
) -> tuple[dict[str, Any], list[RowError]]:
    """校验单行，返回 (映射后的业务字段, 错误列表)。"""
    mapped: dict[str, Any] = {}
    errors: list[RowError] = []

    # 先按映射解析每个字段值。
    for field in fields:
        # 找到映射到该字段的源列。
        source_col = next((col for col, key in mapping.items() if key == field.key), None)
        if source_col is None:
            if field.required:
                errors.append(
                    RowError(0, ERR_MISSING_REQUIRED, field.key,
                             f"缺少必填字段「{field.aliases[0]}」，请检查列名映射。")
                )
            continue
        raw_value = raw_row.get(source_col)
        if raw_value is None or str(raw_value).strip() == "":
            if field.required:
                errors.append(
                    RowError(0, ERR_MISSING_REQUIRED, field.key,
                             f"必填字段「{field.aliases[0]}」为空。")
                )
            else:
                mapped[field.key] = None
            continue
        try:
            mapped[field.key] = parse_value(field, raw_value)
        except ValueError as exc:
            errors.append(RowError(0, ERR_INVALID_FORMAT, field.key, str(exc)))

    return mapped, errors
