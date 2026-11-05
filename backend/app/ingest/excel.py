"""Excel / CSV 解析：识别表头、推断字段类型、清洗单元格。

不依赖固定 schema：每个 Sheet 都会被转换成一个独立的列描述，
后续由 services.ingest 负责建表。
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import pandas as pd
from pandas.api.types import is_datetime64_any_dtype, is_numeric_dtype

DATE_PATTERN = re.compile(r"^\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?$")
TIME_PATTERN = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}[ T]\d{1,2}:\d{2}")
NUMERIC_TEXT = re.compile(r"^[¥$￥]?\s*-?[\d,]+(\.\d+)?\s*[%％]?$")
BAD_IDENTIFIER_CHARS = re.compile(r"[\s()（）\[\]{}.,/\\%\-—:：;；'\"`|+*]+")
UNNAMED = re.compile(r"^Unnamed:\s*\d+$")


@dataclass
class ColumnSpec:
    physical: str
    display: str
    sql_type: str  # double precision | text | date | timestamp
    kind: str  # number | text | date
    sample: str = ""
    invalid: int = 0  # 非空但无法按推断类型解析的单元格数


@dataclass
class ParsedSheet:
    sheet_name: str
    columns: list[ColumnSpec]
    rows: list[list[Any]] = field(default_factory=list)
    source_row_count: int = 0
    blank_row_count: int = 0
    duplicate_row_count: int = 0
    issues: list[str] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def display_columns(self) -> list[str]:
        return [column.display for column in self.columns]

    @property
    def invalid_cells(self) -> int:
        return sum(column.invalid for column in self.columns)

    def quality(self) -> dict[str, Any]:
        """导入质量摘要，供前端预览与上传响应展示。"""
        issues = list(self.issues)
        for column in self.columns:
            if column.invalid:
                issues.append(
                    f"字段「{column.display}」有 {column.invalid} 个值无法解析为"
                    f"{'日期' if column.kind == 'date' else '数字'}，已按空值导入。"
                )
        return {
            "source_rows": self.source_row_count or self.row_count,
            "imported_rows": self.row_count,
            "blank_rows": self.blank_row_count,
            "duplicate_rows": self.duplicate_row_count,
            "invalid_cells": self.invalid_cells,
            "issues": issues[:10],
        }


def _clean_header(value: Any, index: int) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return f"列{index + 1}"
    text = str(value).strip()
    if not text or UNNAMED.match(text):
        return f"列{index + 1}"
    return text


def _physical_name(display: str, index: int) -> str:
    text = BAD_IDENTIFIER_CHARS.sub("_", display)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        text = f"col_{index + 1}"
    if text[0].isdigit() or text.startswith("_"):
        text = f"c_{text}"
    # PostgreSQL 标识符上限 63 字节，中文占 3 字节，保守截断。
    return text[:20]


def _unique_names(headers: list[str]) -> tuple[list[str], list[str]]:
    displays: list[str] = []
    physicals: list[str] = []
    used_display: set[str] = set()
    used_physical: set[str] = set()

    for index, raw in enumerate(headers):
        display = _clean_header(raw, index)
        base = display
        suffix = 2
        while display.lower() in used_display:
            display = f"{base}_{suffix}"
            suffix += 1
        used_display.add(display.lower())
        displays.append(display)

        base_physical = _physical_name(display, index)
        physical = base_physical
        suffix = 2
        while physical.lower() in used_physical:
            physical = f"{base_physical[:18]}_{suffix}"
            suffix += 1
        used_physical.add(physical.lower())
        physicals.append(physical)

    return displays, physicals


def _sample(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()[:10]
    return str(value).strip()[:60]


def _normalize_date_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        parsed = pd.to_datetime(str(value).replace("年", "-").replace("月", "-").replace("日", ""), errors="coerce")
    except Exception:
        return None
    if parsed is pd.NaT or pd.isna(parsed):
        return None
    return parsed.date()


def _invalid_count(series: pd.Series, converted: pd.Series) -> int:
    """统计非空但转换失败的值，用于导入质量报告。"""
    return max(int(series.notna().sum()) - int(converted.notna().sum()), 0)


def _analyze_column(series: pd.Series, physical: str, display: str, index: int) -> tuple[ColumnSpec, pd.Series]:
    """返回列描述以及转换后的值序列。"""
    non_null = series.dropna()
    sample = _sample(non_null.iloc[0]) if len(non_null) else ""

    if is_numeric_dtype(series) and len(non_null) > 0:
        numeric = pd.to_numeric(series, errors="coerce")
        converted = numeric.map(lambda v: None if pd.isna(v) else float(v))
        return (
            ColumnSpec(
                physical, display, "double precision", "number", sample, _invalid_count(series, converted)
            ),
            converted,
        )

    if is_datetime64_any_dtype(series):
        converted = series.map(_normalize_date_value)
        return (
            ColumnSpec(physical, display, "date", "date", sample[:10], _invalid_count(series, converted)),
            converted,
        )

    if len(non_null) and isinstance(non_null.iloc[0], (datetime, date)):
        converted = series.map(_normalize_date_value)
        return (
            ColumnSpec(physical, display, "date", "date", sample[:10], _invalid_count(series, converted)),
            converted,
        )

    text_values = non_null.astype(str).str.strip()
    if len(text_values) > 0:
        inspected = text_values.head(200)
        date_hits = sum(1 for value in inspected if DATE_PATTERN.match(value))
        if date_hits >= 0.6 * len(inspected):
            converted = series.map(_normalize_date_value)
            if converted.notna().sum() >= 0.6 * len(non_null):
                return (
                    ColumnSpec(
                        physical, display, "date", "date", sample[:10], _invalid_count(series, converted)
                    ),
                    converted,
                )

        numeric_hits = sum(1 for value in inspected if NUMERIC_TEXT.match(value))
        if numeric_hits >= 0.8 * len(inspected):
            cleaned = series.map(
                lambda value: None
                if value is None or (isinstance(value, float) and pd.isna(value))
                else str(value).replace(",", "").replace("¥", "").replace("￥", "")
                .replace("$", "").replace("%", "").replace("％", "").strip()
            )
            numeric = pd.to_numeric(cleaned, errors="coerce")
            if numeric.notna().sum() >= 0.8 * len(non_null):
                converted = numeric.map(lambda value: None if pd.isna(value) else float(value))
                return (
                    ColumnSpec(
                        physical,
                        display,
                        "double precision",
                        "number",
                        sample,
                        _invalid_count(series, converted),
                    ),
                    converted,
                )

    def to_text(value: Any) -> str | None:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        if isinstance(value, (datetime, date, pd.Timestamp)):
            return value.isoformat()
        text = str(value).strip()
        return text or None

    return ColumnSpec(physical, display, "text", "text", sample), series.map(to_text)


def _build_sheet(name: str, frame: pd.DataFrame) -> ParsedSheet:
    source_rows = int(len(frame))
    non_blank = frame.dropna(how="all")
    blank_rows = source_rows - int(len(non_blank))
    duplicate_rows = int(non_blank.duplicated().sum()) if len(non_blank) else 0
    frame = non_blank.reset_index(drop=True)
    if frame.empty or len(frame.columns) == 0:
        return ParsedSheet(
            sheet_name=name,
            columns=[],
            rows=[],
            source_row_count=source_rows,
            blank_row_count=blank_rows,
            duplicate_row_count=duplicate_rows,
        )

    displays, physicals = _unique_names([str(column) for column in frame.columns])
    columns: list[ColumnSpec] = []
    converted_series: list[pd.Series] = []

    for index, (display, physical) in enumerate(zip(displays, physicals, strict=True)):
        spec, converted = _analyze_column(frame.iloc[:, index], physical, display, index)
        columns.append(spec)
        converted_series.append(converted.reset_index(drop=True))

    rows: list[list[Any]] = []
    for row_index in range(len(frame)):
        row: list[Any] = []
        for converted in converted_series:
            value = converted.iloc[row_index]
            if value is None or (isinstance(value, float) and pd.isna(value)):
                row.append(None)
            elif isinstance(value, pd.Timestamp):
                row.append(value.date())
            elif isinstance(value, (float, int)) and not isinstance(value, bool):
                row.append(float(value))
            else:
                row.append(value)
        rows.append(row)

    issues: list[str] = []
    if blank_rows:
        issues.append(f"已跳过 {blank_rows} 个全空行。")
    if duplicate_rows:
        issues.append(f"发现 {duplicate_rows} 行完全重复的记录（未自动删除，请确认是否为重复入账）。")

    return ParsedSheet(
        sheet_name=name,
        columns=columns,
        rows=rows,
        source_row_count=source_rows,
        blank_row_count=blank_rows,
        duplicate_row_count=duplicate_rows,
        issues=issues,
    )


def parse_upload(filename: str, content: bytes) -> ParsedSheet:
    """解析上传文件，返回首个非空 Sheet。"""
    lower = filename.lower()
    if lower.endswith(".csv"):
        frame = None
        for encoding in ("utf-8-sig", "utf-8", "gbk"):
            try:
                frame = pd.read_csv(io.BytesIO(content), encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        if frame is None:
            raise ValueError("无法识别 CSV 编码，请另存为 UTF-8 后重试。")
        sheet = _build_sheet("CSV", frame)
        if not sheet.columns:
            raise ValueError("文件中没有可识别的数据。")
        return sheet

    try:
        sheets = pd.read_excel(io.BytesIO(content), sheet_name=None)
    except ImportError as exc:  # pragma: no cover - 缺少 openpyxl 时给出明确提示
        raise ValueError("缺少 Excel 解析依赖，请先安装 openpyxl。") from exc

    for sheet_name, frame in sheets.items():
        sheet = _build_sheet(str(sheet_name), frame)
        if sheet.columns:
            return sheet

    raise ValueError("Excel 中没有找到含表头的数据 Sheet。")
