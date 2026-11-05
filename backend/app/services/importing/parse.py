"""SpendOps G2 文件解析：读取 CSV/XLSX 为「列名 + 原始行」。

与上游 ``app.ingest.excel`` 的差异：上游是「通用 BI 数据集」的容错式解析，
把解析失败的值静默转成空值并用 double precision 存金额。这里面向采购业务，
**保留原始单元格值**（金额用字符串转 Decimal，不做 float 累加），由字段校验层
严格解析并在失败时产出行级错误，而不是静默丢值。

安全约束：
- 不落盘，全部经内存 ``BytesIO`` 解析，无路径穿越风险。
- 编码探测按 utf-8-sig -> utf-8 -> gb18030 顺序，覆盖常见中文 CSV。
- 记录源文件行号（含表头），错误报告可定位到具体行。
"""

from __future__ import annotations

import io
from datetime import date, datetime
from typing import Any

import pandas as pd

MAX_COLUMNS = 200       # 列数上限（防异常宽表）
MAX_ROWS = 200_000      # 行数上限（防异常大文件，实测前不宣称更大规模）


def _norm_cell(value: Any) -> str | None:
    """把单元格值规范化为字符串（保留原始十进制文本）或 None（空值）。"""
    if value is None:
        return None
    if isinstance(value, float):
        if pd.isna(value):
            return None
        if value.is_integer():
            return str(int(value))
        # Python 的 str(float) 使用最短十进制表示，能无损还原 Excel 显示的数值。
        return str(value)
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def parse_tabular(filename: str, content: bytes) -> tuple[list[str], list[dict[str, Any]]]:
    """解析上传文件，返回 (列名列表, 行列表)。

    行列表每个元素为 {列名: 规范化字符串或 None}。返回的行已去除全空行，
    但保留源文件行号（通过外部逐行补行号，见 ``row_number`` 字段）。
    """
    lower = filename.lower()
    if lower.endswith(".csv"):
        frame = _read_csv(content)
    elif lower.endswith((".xlsx", ".xls")):
        frame = _read_excel(content)
    else:
        raise ValueError("仅支持 .csv / .xlsx / .xls 文件。")

    if frame.empty:
        raise ValueError("文件中没有可识别的数据。")
    if frame.shape[1] > MAX_COLUMNS:
        raise ValueError(f"列数 {frame.shape[1]} 超过上限 {MAX_COLUMNS}，请精简文件。")
    if frame.shape[0] > MAX_ROWS:
        raise ValueError(f"行数 {frame.shape[0]} 超过上限 {MAX_ROWS}，请分批导入。")

    # 列名规范化：去重、去空、去 Unnamed。
    headers: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(frame.columns):
        name = str(raw).strip()
        if not name or name.lower().startswith("unnamed:"):
            name = f"列{index + 1}"
        base = name
        suffix = 2
        while name.lower() in seen:
            name = f"{base}_{suffix}"
            suffix += 1
        seen.add(name.lower())
        headers.append(name)

    rows: list[dict[str, Any]] = []
    for _, series in frame.iterrows():
        row: dict[str, Any] = {}
        all_empty = True
        for header in headers:
            value = _norm_cell(series.get(header))
            row[header] = value
            if value is not None:
                all_empty = False
        if not all_empty:
            rows.append(row)

    if not rows:
        raise ValueError("文件中没有可用的数据行。")
    return headers, rows


def _read_csv(content: bytes) -> pd.DataFrame:
    last_err: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return pd.read_csv(io.BytesIO(content), encoding=encoding, dtype=str)
        except (UnicodeDecodeError, UnicodeError) as exc:
            last_err = exc
            continue
    raise ValueError(f"无法识别 CSV 编码（{last_err}），请另存为 UTF-8 后重试。")


def _read_excel(content: bytes) -> pd.DataFrame:
    try:
        sheets = pd.read_excel(io.BytesIO(content), sheet_name=None)
    except ImportError as exc:  # pragma: no cover
        raise ValueError("缺少 Excel 解析依赖，请先安装 openpyxl。") from exc
    except Exception as exc:
        raise ValueError(f"Excel 文件解析失败：{exc}") from exc

    for frame in sheets.values():
        if not frame.empty:
            return frame
    raise ValueError("Excel 中没有含数据的工作表。")
