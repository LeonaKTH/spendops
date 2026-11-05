"""报表导出：生成可直接分发的 Excel / PDF 文件。

导出基于已经汇总好的 ``ReportSummaryOut``，不重复查询数据库。
"""

from __future__ import annotations

import io
from typing import Literal

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.api.v1.schemas import ReportSummaryOut

ExportFormat = Literal["xlsx", "pdf"]

_FONT = "STSong-Light"
_HEADER_FILL = PatternFill("solid", fgColor="0F9D8A")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_TITLE_FONT = Font(bold=True, size=15, color="0F172A")
_MUTED_FONT = Font(color="64748B", size=9)
_THIN = Side(style="thin", color="E2E8F0")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)


def export_filename(summary: ReportSummaryOut, fmt: ExportFormat) -> str:
    start = summary.dataset.period_start[:10] or "start"
    end = summary.dataset.period_end[:10] or "end"
    return f"procurebi-report-{start}-{end}.{fmt}"


def build_export(summary: ReportSummaryOut, fmt: ExportFormat) -> tuple[bytes, str]:
    if fmt == "xlsx":
        return build_excel(summary), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return build_pdf(summary), "application/pdf"


# ---------------------------------------------------------------- Excel


def _write_title(ws, title: str, width: int) -> None:
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=width)
    cell = ws.cell(row=1, column=1, value=title)
    cell.font = _TITLE_FONT
    cell.alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 26


def _write_header(ws, row: int, headers: list[str]) -> None:
    for index, header in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=index, value=header)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = _BORDER


def _write_rows(ws, start_row: int, rows: list[list[object]]) -> int:
    row_index = start_row
    for row in rows:
        for column_index, value in enumerate(row, start=1):
            cell = ws.cell(row=row_index, column=column_index, value=value)
            cell.border = _BORDER
            cell.alignment = Alignment(
                vertical="center",
                horizontal="right" if isinstance(value, (int, float)) else "left",
            )
        row_index += 1
    return row_index


def _autosize(ws, widths: list[int]) -> None:
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width


def build_excel(summary: ReportSummaryOut) -> bytes:
    workbook = Workbook()
    overview = workbook.active
    overview.title = "报表概览"
    _write_title(overview, "ProcureBI 大模型采购分析报告", 5)

    meta = [
        ("数据集", summary.dataset.name),
        ("源文件", summary.dataset.source_file),
        ("统计期间", f"{summary.dataset.period_start} 至 {summary.dataset.period_end}"),
        ("账单行数", summary.dataset.row_count),
        ("生成时间", summary.generated_at.strftime("%Y-%m-%d %H:%M:%S")),
    ]
    if summary.provider_filter:
        meta.append(("供应商筛选", summary.provider_filter))
    if summary.currency_note:
        meta.append(("币种口径", summary.currency_note))
    row = 3
    for label, value in meta:
        overview.cell(row=row, column=1, value=label).font = _MUTED_FONT
        overview.cell(row=row, column=2, value=value)
        row += 1

    row += 1
    overview.cell(row=row, column=1, value="核心指标").font = Font(bold=True, size=12)
    row += 1
    _write_header(overview, row, ["指标", "数值", "单位", "说明"])
    row += 1
    row = _write_rows(
        overview,
        row,
        [[item.label, item.value, item.unit, item.delta] for item in summary.kpis],
    )

    row += 1
    overview.cell(row=row, column=1, value="自动洞察").font = Font(bold=True, size=12)
    row += 1
    _write_header(overview, row, ["类型", "洞察", "说明"])
    row += 1
    _write_rows(
        overview,
        row,
        [[item.tag, item.title, item.meta] for item in summary.insights],
    )
    _autosize(overview, [18, 34, 12, 62])

    # 供应商
    provider_sheet = workbook.create_sheet("供应商")
    dimension = "模型" if summary.provider_filter else "供应商"
    _write_title(provider_sheet, summary.provider_chart.title, 3)
    _write_header(provider_sheet, 3, [dimension, "采购金额(万元)", "占比"])
    chart_x = summary.provider_chart.x or []
    series = summary.provider_chart.series[0].data if summary.provider_chart.series else []
    total = sum(series) or 0
    provider_rows = [
        [name, amount, amount / total if total else 0]
        for name, amount in zip(chart_x, series, strict=False)
    ]
    end_row = _write_rows(provider_sheet, 4, provider_rows)
    for index in range(4, end_row):
        provider_sheet.cell(row=index, column=2).number_format = "#,##0.00"
        provider_sheet.cell(row=index, column=3).number_format = "0.0%"
    _autosize(provider_sheet, [26, 18, 12])
    if provider_rows:
        chart = BarChart()
        chart.title = f"{summary.provider_chart.title}（万元）"
        chart.y_axis.title = "万元"
        data = Reference(
            provider_sheet, min_col=2, min_row=3, max_row=3 + len(provider_rows)
        )
        categories = Reference(
            provider_sheet, min_col=1, min_row=4, max_row=3 + len(provider_rows)
        )
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(categories)
        chart.height = 7
        chart.width = 16
        provider_sheet.add_chart(chart, "E3")

    # 应用
    app_sheet = workbook.create_sheet("应用")
    _write_title(app_sheet, "成本按应用分布", 2)
    _write_header(app_sheet, 3, ["应用", "采购金额(万元)"])
    app_data = summary.app_chart.data if summary.app_chart and summary.app_chart.data else []
    app_end = _write_rows(app_sheet, 4, [[item.name, item.value] for item in app_data])
    for index in range(4, app_end):
        app_sheet.cell(row=index, column=2).number_format = "#,##0.00"
    _autosize(app_sheet, [28, 18])

    # 月度
    month_sheet = workbook.create_sheet("月度")
    _write_title(month_sheet, "月度采购成本", 2)
    _write_header(month_sheet, 3, ["月份", "采购金额(万元)"])
    month_x = summary.monthly_chart.x or [] if summary.monthly_chart else []
    month_series = (
        summary.monthly_chart.series[0].data
        if summary.monthly_chart and summary.monthly_chart.series
        else []
    )
    month_end = _write_rows(
        month_sheet,
        4,
        [[label, value] for label, value in zip(month_x, month_series, strict=False)],
    )
    for index in range(4, month_end):
        month_sheet.cell(row=index, column=2).number_format = "#,##0.00"
    _autosize(month_sheet, [16, 18])
    if month_x:
        chart = LineChart()
        chart.title = "月度采购成本趋势（万元）"
        chart.y_axis.title = "万元"
        data = Reference(month_sheet, min_col=2, min_row=3, max_row=3 + len(month_x))
        categories = Reference(month_sheet, min_col=1, min_row=4, max_row=3 + len(month_x))
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(categories)
        chart.height = 7
        chart.width = 16
        month_sheet.add_chart(chart, "D3")

    # 模型价格
    if summary.catalog:
        catalog_sheet = workbook.create_sheet("模型价格")
        _write_title(catalog_sheet, "当前在售模型价格结构", 4)
        catalog_sheet.cell(row=3, column=1, value=summary.catalog.summary).font = _MUTED_FONT
        _write_header(catalog_sheet, 5, summary.catalog.table.columns)
        _write_rows(catalog_sheet, 6, summary.catalog.table.rows)
        _autosize(catalog_sheet, [24, 30, 20, 20])

    # 配额
    quota_sheet = workbook.create_sheet("合同配额")
    _write_title(quota_sheet, "合同配额使用情况", 5)
    _write_header(quota_sheet, 3, summary.quota_table.columns)
    if summary.quota_table.rows:
        _write_rows(quota_sheet, 4, summary.quota_table.rows)
    else:
        quota_sheet.cell(row=4, column=1, value="尚未上传合同配额数据")
    _autosize(quota_sheet, [24, 20, 20, 12, 16])

    # 预算执行
    if summary.budget:
        budget_sheet = workbook.create_sheet("预算执行")
        _write_title(budget_sheet, "年度预算执行情况", 4)
        budget_sheet.cell(row=3, column=1, value=summary.budget.summary).font = _MUTED_FONT
        _write_header(budget_sheet, 5, summary.budget.table.columns)
        _write_rows(budget_sheet, 6, summary.budget.table.rows)
        _autosize(budget_sheet, [24, 18, 22, 14])

    # 采购底表
    if summary.purchasing:
        purchasing_sheet = workbook.create_sheet("采购底表")
        _write_title(purchasing_sheet, "报价单与采购底表", 6)
        purchasing_sheet.cell(row=3, column=1, value=summary.purchasing.summary).font = _MUTED_FONT
        _write_header(purchasing_sheet, 5, summary.purchasing.quote_table.columns)
        if summary.purchasing.quote_table.rows:
            _write_rows(purchasing_sheet, 6, summary.purchasing.quote_table.rows)
        else:
            purchasing_sheet.cell(row=6, column=1, value="未检测到报价单数据集")
        _autosize(purchasing_sheet, [20, 28, 14, 14, 12, 14])

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------- PDF


def _pdf_styles() -> dict[str, ParagraphStyle]:
    pdfmetrics.registerFont(UnicodeCIDFont(_FONT))
    base = getSampleStyleSheet()["Normal"]
    return {
        "title": ParagraphStyle(
            "ProcureBITitle",
            parent=base,
            fontName=_FONT,
            fontSize=19,
            leading=25,
            textColor=colors.HexColor("#0F172A"),
            spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "ProcureBISubtitle",
            parent=base,
            fontName=_FONT,
            fontSize=9,
            leading=14,
            textColor=colors.HexColor("#64748B"),
        ),
        "heading": ParagraphStyle(
            "ProcureBIHeading",
            parent=base,
            fontName=_FONT,
            fontSize=12.5,
            leading=18,
            textColor=colors.HexColor("#0F9D8A"),
            spaceBefore=12,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "ProcureBIBody",
            parent=base,
            fontName=_FONT,
            fontSize=9.5,
            leading=14,
            alignment=TA_LEFT,
        ),
        "cell": ParagraphStyle(
            "ProcureBICell",
            parent=base,
            fontName=_FONT,
            fontSize=8.5,
            leading=12,
        ),
    }


def _pdf_table(rows: list[list[str]], widths: list[float], styles) -> Table:
    data = [[Paragraph(str(cell), styles["cell"]) for cell in row] for row in rows]
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F9D8A")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), _FONT),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E2E8F0")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def build_pdf(summary: ReportSummaryOut) -> bytes:
    styles = _pdf_styles()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=15 * mm,
        title="ProcureBI 大模型采购分析报告",
        author="ProcureBI",
    )
    width = A4[0] - 32 * mm
    story: list[object] = []

    story.append(Paragraph("ProcureBI 大模型采购分析报告", styles["title"]))
    story.append(
        Paragraph(
            f"数据集：{summary.dataset.name}　|　"
            f"统计期间：{summary.dataset.period_start} 至 {summary.dataset.period_end}　|　"
            f"账单行数：{summary.dataset.row_count:,}",
            styles["subtitle"],
        )
    )
    story.append(
        Paragraph(
            f"源文件：{summary.dataset.source_file}　|　"
            f"生成时间：{summary.generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
            styles["subtitle"],
        )
    )
    story.append(Spacer(1, 8))
    story.append(Paragraph("核心指标", styles["heading"]))
    kpi_rows = [["指标", "数值", "单位", "说明"]]
    kpi_rows += [
        [item.label, item.value, item.unit, item.delta] for item in summary.kpis
    ]
    story.append(_pdf_table(kpi_rows, [width * 0.3, width * 0.16, width * 0.13, width * 0.41], styles))

    story.append(Paragraph("供应商采购结构", styles["heading"]))
    story.append(Paragraph(summary.provider_summary + "。", styles["body"]))
    story.append(Spacer(1, 4))
    provider_x = summary.provider_chart.x or []
    provider_values = (
        summary.provider_chart.series[0].data if summary.provider_chart.series else []
    )
    provider_total = sum(provider_values) or 0
    provider_rows = [["模型" if summary.provider_filter else "供应商", "采购金额(万元)", "占比"]]
    provider_rows += [
        [
            name,
            f"{value:,.2f}",
            f"{(value / provider_total * 100) if provider_total else 0:.1f}%",
        ]
        for name, value in zip(provider_x[:12], provider_values[:12], strict=False)
    ]
    story.append(_pdf_table(provider_rows, [width * 0.5, width * 0.3, width * 0.2], styles))

    if summary.app_chart and summary.app_chart.data:
        story.append(Paragraph("成本按应用分布", styles["heading"]))
        story.append(Paragraph(summary.app_summary + "。", styles["body"]))
        story.append(Spacer(1, 4))
        app_rows = [["应用", "采购金额(万元)"]]
        app_rows += [
            [item.name, f"{item.value:,.2f}"] for item in summary.app_chart.data[:12]
        ]
        story.append(_pdf_table(app_rows, [width * 0.65, width * 0.35], styles))

    if summary.monthly_chart and summary.monthly_chart.x:
        story.append(Paragraph("月度成本趋势", styles["heading"]))
        story.append(Paragraph(summary.monthly_summary + "。", styles["body"]))
        story.append(Spacer(1, 4))
        month_values = (
            summary.monthly_chart.series[0].data if summary.monthly_chart.series else []
        )
        month_rows = [["月份", "采购金额(万元)"]]
        month_rows += [
            [label, f"{value:,.2f}"]
            for label, value in zip(
                summary.monthly_chart.x, month_values, strict=False
            )
        ]
        story.append(_pdf_table(month_rows, [width * 0.4, width * 0.6], styles))

    story.append(Paragraph("自动洞察", styles["heading"]))
    for index, item in enumerate(summary.insights, start=1):
        story.append(
            Paragraph(
                f"{index}. <b>{item.title}</b>（{item.tag}）<br/>{item.meta}",
                styles["body"],
            )
        )
        story.append(Spacer(1, 3))

    if summary.catalog:
        story.append(PageBreak())
        story.append(Paragraph("当前在售模型价格结构", styles["heading"]))
        story.append(Paragraph(summary.catalog.summary, styles["body"]))
        story.append(Spacer(1, 4))
        catalog_rows = [list(summary.catalog.table.columns)]
        catalog_rows += [
            [str(cell) if cell is not None else "" for cell in row]
            for row in summary.catalog.table.rows
        ]
        story.append(
            _pdf_table(
                catalog_rows,
                [width * 0.24, width * 0.34, width * 0.21, width * 0.21],
                styles,
            )
        )

    story.append(Paragraph("合同配额使用情况", styles["heading"]))
    story.append(Paragraph(summary.quota_summary + "。", styles["body"]))
    story.append(Spacer(1, 4))
    if summary.quota_table.rows:
        quota_rows = [list(summary.quota_table.columns)]
        quota_rows += [
            [str(cell) if cell is not None else "" for cell in row]
            for row in summary.quota_table.rows
        ]
        story.append(
            _pdf_table(
                quota_rows,
                [width * 0.25, width * 0.2, width * 0.2, width * 0.15, width * 0.2],
                styles,
            )
        )
    else:
        story.append(Paragraph("尚未上传合同配额数据。", styles["body"]))

    if summary.budget:
        story.append(Paragraph("年度预算执行", styles["heading"]))
        story.append(Paragraph(summary.budget.summary, styles["body"]))
        story.append(Spacer(1, 4))
        budget_rows = [list(summary.budget.table.columns)]
        budget_rows += [
            [str(cell) if cell is not None else "" for cell in row]
            for row in summary.budget.table.rows
        ]
        story.append(
            _pdf_table(
                budget_rows,
                [width * 0.28, width * 0.22, width * 0.3, width * 0.2],
                styles,
            )
        )

    if summary.purchasing:
        story.append(Paragraph("报价单与采购底表", styles["heading"]))
        story.append(Paragraph(summary.purchasing.summary, styles["body"]))
        story.append(Spacer(1, 4))
        if summary.purchasing.quote_table.rows:
            quote_rows = [list(summary.purchasing.quote_table.columns)]
            quote_rows += [
                [str(cell) if cell is not None else "" for cell in row]
                for row in summary.purchasing.quote_table.rows
            ]
            story.append(
                _pdf_table(
                    quote_rows,
                    [width * 0.18, width * 0.26, width * 0.14, width * 0.14, width * 0.13, width * 0.15],
                    styles,
                )
            )

    story.append(Spacer(1, 14))
    footnote = (
        "说明：本报告由 ProcureBI 根据已上传账单自动汇总"
        + (f"；{summary.currency_note}" if summary.currency_note else "，金额单位以账单原始币种为准，未做汇率换算")
        + "；合同配额取自同期配额表。仅供内部经营分析参考。"
    )
    story.append(Paragraph(footnote, styles["subtitle"]))
    document.build(story)
    return buffer.getvalue()
