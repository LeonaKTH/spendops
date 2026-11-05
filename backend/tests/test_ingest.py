import io
from datetime import date

import pandas as pd

from app.ingest.excel import (
    _clean_header,
    _physical_name,
    _unique_names,
    parse_upload,
)

CSV = """账期,供应商,金额(元),输入token,使用率
2025-01-01,DeepSeek,"1,234.50",1200,92%
2025-01-02,OpenAI,$2000,800,45%
"""


def test_csv_type_inference_and_value_cleaning():
    sheet = parse_upload("bills.csv", CSV.encode("utf-8"))

    assert sheet.sheet_name == "CSV"
    assert sheet.display_columns == ["账期", "供应商", "金额(元)", "输入token", "使用率"]
    assert [column.kind for column in sheet.columns] == [
        "date",
        "text",
        "number",
        "number",
        "number",
    ]
    assert sheet.row_count == 2

    first = sheet.rows[0]
    assert first[0] == date(2025, 1, 1)
    assert first[1] == "DeepSeek"
    assert first[2] == 1234.5
    assert first[3] == 1200.0
    assert first[4] == 92.0
    assert sheet.rows[1][2] == 2000.0


def test_excel_parse_skips_empty_first_sheet():
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame().to_excel(writer, sheet_name="空表", index=False)
        pd.DataFrame(
            {
                "供应商": ["Anthropic"],
                "金额_元": [100.5],
                "账期": ["2025/3/5"],
            }
        ).to_excel(writer, sheet_name="账单", index=False)

    sheet = parse_upload("bills.xlsx", buffer.getvalue())

    assert sheet.sheet_name == "账单"
    assert sheet.row_count == 1
    assert sheet.rows[0][2] == date(2025, 3, 5)


def test_headers_are_cleaned_and_deduplicated():
    assert _clean_header(None, 0) == "列1"
    assert _clean_header("Unnamed: 2", 2) == "列3"
    assert _clean_header(" 供应商 ", 0) == "供应商"

    displays, physicals = _unique_names(["金额", "金额", "a b", "a_b"])
    assert displays == ["金额", "金额_2", "a b", "a_b"]
    assert len(set(physicals)) == 4


def test_physical_name_is_safe_for_postgres():
    assert _physical_name("金额(元)", 0) == "金额_元"
    assert _physical_name("2025 年金额", 0).startswith("c_")
    assert not _physical_name("   ", 0).startswith("_")
    assert len(_physical_name("很" * 40, 0)) <= 20


def test_all_null_rows_are_dropped():
    content = "供应商,金额\nDeepSeek,10\n,\nOpenAI,20\n"
    sheet = parse_upload("bills.csv", content.encode("utf-8"))
    assert sheet.row_count == 2


def test_quality_report_counts_blank_duplicate_and_invalid_rows():
    content = (
        "账期,供应商,金额\n"
        "2025-01-01,DeepSeek,10\n"
        "2025-01-02,OpenAI,20\n"
        "2025-01-03,Anthropic,30\n"
        "2025-01-04,Moonshot,40\n"
        "not-a-date,DeepSeek,50\n"
        "2025-01-05,OpenAI,20\n"
        "2025-01-02,OpenAI,20\n"
        ",,\n"
    )
    sheet = parse_upload("bills.csv", content.encode("utf-8"))

    assert sheet.row_count == 7
    assert sheet.source_row_count == 8
    assert sheet.blank_row_count == 1
    assert sheet.duplicate_row_count == 1
    assert sheet.invalid_cells == 1

    quality = sheet.quality()
    assert quality["imported_rows"] == 7
    assert quality["source_rows"] == 8
    assert quality["blank_rows"] == 1
    assert quality["duplicate_rows"] == 1
    assert quality["invalid_cells"] == 1
    assert any("全空行" in issue for issue in quality["issues"])
    assert any("重复" in issue for issue in quality["issues"])
    assert any("账期" in issue for issue in quality["issues"])
