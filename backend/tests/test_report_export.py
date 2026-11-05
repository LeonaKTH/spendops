from datetime import UTC, datetime
from io import BytesIO

from openpyxl import load_workbook

from app.api.v1.schemas import (
    ReportCatalogOut,
    ReportChartOut,
    ReportDatasetOut,
    ReportDatumOut,
    ReportInsightOut,
    ReportKpiOut,
    ReportSeriesOut,
    ReportSummaryOut,
    TableOut,
)
from app.services.report_export import build_excel, build_pdf, export_filename


def make_summary() -> ReportSummaryOut:
    return ReportSummaryOut(
        generated_at=datetime(2026, 10, 21, 12, 0, tzinfo=UTC),
        dataset=ReportDatasetOut(
            id="ds-1",
            name="bills_2026",
            source_file="bills_2026.xlsx",
            row_count=13248,
            period_start="2026-07-01",
            period_end="2026-09-30",
        ),
        kpis=[
            ReportKpiOut(
                label="2026 年 7-9 月采购总成本",
                value="297.19",
                unit="万元",
                delta="覆盖 10 家供应商 · 16 个模型",
                warn=True,
            ),
            ReportKpiOut(
                label="累计调用量",
                value="952.4",
                unit="亿 tokens",
                delta="2026-07-01 至 2026-09-30",
                warn=False,
            ),
        ],
        provider_chart=ReportChartOut(
            type="bar",
            title="各供应商采购金额",
            x=["OpenAI", "Anthropic"],
            series=[ReportSeriesOut(name="采购金额", data=[78.76, 105.77])],
            unit="万元",
        ),
        app_chart=ReportChartOut(
            type="pie",
            title="成本按应用分布",
            data=[ReportDatumOut(name="智能客服", value=153.38)],
            unit="万元",
        ),
        monthly_chart=ReportChartOut(
            type="line",
            title="2026 年月度采购成本",
            x=["7月", "8月", "9月"],
            series=[ReportSeriesOut(name="成本", data=[98.09, 97.21, 101.89])],
            unit="万元",
        ),
        quota_table=TableOut(
            columns=["供应商", "承诺金额(万元)", "已用金额(万元)", "使用率", "到期日"],
            rows=[["火山引擎", 25, 22.65, "90.6%", "2027-07-28"]],
        ),
        catalog=ReportCatalogOut(
            total_models=2,
            provider_count=2,
            summary="当前在售 2 个模型。",
            table=TableOut(
                columns=["供应商", "模型", "输入价(USD/百万)", "输出价(USD/百万)"],
                rows=[["OpenAI", "GPT-6 Astra", 10, 50]],
            ),
        ),
        provider_summary="Anthropic 占 35.6%",
        app_summary="智能客服是最大成本中心",
        monthly_summary="9 月环比 +4.8%",
        quota_summary="火山引擎已用 90.6%",
        insights=[
            ReportInsightOut(
                title="Anthropic 占采购成本 35.6%",
                meta="前两家供应商合计 62.1%。",
                tag="成本结构",
            )
        ],
        model_count=16,
        app_count=3,
    )


def test_excel_export_contains_chinese_sheets_and_tables():
    content = build_excel(make_summary())

    assert content.startswith(b"PK")
    workbook = load_workbook(BytesIO(content))
    assert workbook.sheetnames == ["报表概览", "供应商", "应用", "月度", "模型价格", "合同配额"]
    overview = workbook["报表概览"]
    assert overview["A1"].value == "ProcureBI 大模型采购分析报告"
    assert any(
        cell.value == "2026 年 7-9 月采购总成本"
        for row in overview.iter_rows()
        for cell in row
    )
    assert workbook["合同配额"]["A1"].value == "合同配额使用情况"


def test_pdf_export_is_valid_pdf_with_chinese_text():
    content = build_pdf(make_summary())

    assert content.startswith(b"%PDF-")
    assert len(content) > 2000

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "ProcureBI 大模型采购分析报告" in text
    assert "2026 年 7-9 月采购总成本" in text
    assert "Anthropic" in text


def test_export_filename_uses_actual_period():
    assert (
        export_filename(make_summary(), "xlsx")
        == "procurebi-report-2026-07-01-2026-09-30.xlsx"
    )
