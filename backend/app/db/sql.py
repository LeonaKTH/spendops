from __future__ import annotations

import json
from typing import Any


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def qualified(schema: str, table: str) -> str:
    return f"{quote_ident(schema)}.{quote_ident(table)}"


def comment_payload(display: str, sample: str) -> str:
    """列注释里保存原始表头与样例值，供前端展示和 NL2SQL 提示词使用。"""
    return json.dumps({"display": display, "sample": sample}, ensure_ascii=False)


def parse_comment(value: Any, fallback: str) -> tuple[str, str]:
    if not value:
        return fallback, ""
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return str(value), ""
    if not isinstance(payload, dict):
        return fallback, ""
    return str(payload.get("display") or fallback), str(payload.get("sample") or "")
