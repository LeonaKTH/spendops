"""把查询结果转换成前端 ECharts 可渲染的图表配置。

LLM 只负责建议图表类型和维度，真正的数据结构由后端按结果确定性生成，
避免把任意代码或不可控配置传给前端。
"""

from __future__ import annotations

import re
from typing import Any

SUPPORTED_TYPES = {"bar", "line", "pie"}
UNIT_PATTERN = re.compile(r"[（(]\s*([^()（）]{1,8})\s*[)）]\s*$")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _numeric_columns(columns: list[str], rows: list[list[Any]]) -> list[str]:
    numeric: list[str] = []
    for index, name in enumerate(columns):
        values = [row[index] for row in rows if index < len(row) and row[index] is not None]
        if values and all(_is_number(value) for value in values[:50]):
            numeric.append(name)
    return numeric


def _detect_unit(columns: list[str], series: list[str]) -> str:
    for name in series + columns:
        match = UNIT_PATTERN.search(name)
        if match:
            return match.group(1)
    for candidate in ("万元", "元", "%", "token", "次", "小时"):
        if any(candidate in name for name in columns):
            return candidate
    return ""


def build_chart(
    plan: dict[str, Any] | None,
    columns: list[str],
    rows: list[list[Any]],
) -> dict[str, Any] | None:
    if not rows or not columns:
        return None

    plan = plan or {}
    numeric = _numeric_columns(columns, rows)
    if not numeric:
        return None

    non_numeric = [name for name in columns if name not in numeric]

    x_name = plan.get("x")
    if not isinstance(x_name, str) or x_name not in columns or x_name in numeric:
        x_name = non_numeric[0] if non_numeric else None

    planned_series = [
        name
        for name in (plan.get("series") or [])
        if isinstance(name, str) and name in numeric
    ]
    series = planned_series or numeric[:3]

    chart_type = plan.get("type")
    if chart_type not in SUPPORTED_TYPES:
        looks_like_time = bool(x_name and any(token in x_name for token in ("日期", "时间", "月", "date", "time")))
        chart_type = "line" if looks_like_time and len(rows) > 8 else "bar"
    if chart_type == "pie" and len(series) != 1:
        chart_type = "bar"

    title = str(plan.get("title") or "查询结果")
    unit = str(plan.get("unit") or "") or _detect_unit(columns, series)

    def cell(row: list[Any], name: str) -> Any:
        return row[columns.index(name)]

    if chart_type == "pie":
        name_index = non_numeric[0] if non_numeric else None
        series_name = series[0]
        data = []
        for row in rows[:10]:
            label = cell(row, name_index) if name_index else str(len(data) + 1)
            value = cell(row, series_name)
            data.append({"name": str(label), "value": round(float(value), 4)})
        return {"type": "pie", "title": title, "data": data, "unit": unit}

    x_values = (
        [str(cell(row, x_name)) for row in rows]
        if x_name
        else [str(index + 1) for index in range(len(rows))]
    )
    chart_series = []
    for name in series:
        values = []
        for row in rows:
            value = cell(row, name)
            values.append(round(float(value), 4) if _is_number(value) else None)
        chart_series.append({"name": name, "data": values})

    return {
        "type": chart_type,
        "title": title,
        "x": x_values,
        "series": chart_series,
        "unit": unit,
    }
