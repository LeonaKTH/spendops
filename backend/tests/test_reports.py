import asyncio
from datetime import UTC, date, datetime

import pytest

from app.services import reports
from app.services.datasets import DatasetMeta, ReflectedColumn


def make_dataset(
    name: str,
    row_count: int,
    columns: list[tuple[str, str]],
    dataset_id: str = "ds-1",
) -> DatasetMeta:
    return DatasetMeta(
        id=dataset_id,
        name=name,
        physical_table=f"t_{name}",
        source_file=f"{name}.xlsx",
        sheet_name="Sheet1",
        row_count=row_count,
        created_at=datetime.now(UTC),
        status="active",
        columns=[
            ReflectedColumn(
                physical=physical,
                display=display,
                sql_type="double precision",
                kind="number",
                sample="",
            )
            for display, physical in columns
        ],
    )


BILLS = make_dataset(
    "bills_2025",
    26280,
    [
        ("账期", "账期"),
        ("供应商", "供应商"),
        ("金额_元", "金额_元"),
        ("应用", "应用"),
        ("模型", "模型"),
        ("输入token", "输入token"),
        ("输出token", "输出token"),
    ],
)

DIRTY_BILLS = make_dataset(
    "bills_dirty_sample",
    30,
    [("日期", "日期"), ("供应商", "供应商"), ("金额(元)", "金额_元")],
    dataset_id="ds-2",
)

QUOTAS = make_dataset(
    "quotas",
    5,
    [
        ("供应商", "供应商"),
        ("承诺金额_元", "承诺金额_元"),
        ("已用金额_元", "已用金额_元"),
        ("使用率", "使用率"),
        ("到期日", "到期日"),
    ],
    dataset_id="ds-3",
)

QUOTAS_2026 = make_dataset(
    "quotas_2026",
    10,
    [
        ("供应商", "供应商"),
        ("承诺金额_元", "承诺金额_元"),
        ("已用金额_元", "已用金额_元"),
        ("使用率", "使用率"),
        ("到期日", "到期日"),
    ],
    dataset_id="ds-4",
)

BILLS_2026 = make_dataset(
    "bills_2026",
    39312,
    [
        ("账期", "账期"),
        ("供应商", "供应商"),
        ("金额_元", "金额_元"),
        ("应用", "应用"),
        ("模型", "模型"),
    ],
    dataset_id="ds-5",
)

MODEL_CATALOG = make_dataset(
    "model_catalog",
    3,
    [
        ("供应商", "供应商"),
        ("模型标识", "模型标识"),
        ("显示名称", "显示名称"),
        ("状态", "状态"),
    ],
    dataset_id="ds-6",
)

PRICE_BOOK = make_dataset(
    "price_book",
    4,
    [
        ("供应商", "供应商"),
        ("模型标识", "模型标识"),
        ("价格类型", "价格类型"),
        ("折算输入价_USD", "折算输入价_USD"),
        ("折算输出价_USD", "折算输出价_USD"),
        ("生效结束", "生效结束"),
    ],
    dataset_id="ds-7",
)


def test_column_normalization_matches_synonyms():
    assert reports._norm("金额(元)") == reports._norm("金额_元")
    assert reports._norm(" 输入 Token ") == "输入token"


def test_dataset_picker_prefers_hinted_and_larger_table():
    picked = reports._pick_dataset(
        [DIRTY_BILLS, QUOTAS, BILLS],
        reports.BILL_COLUMNS,
        required=("amount", "date", "provider"),
        hints=reports.BILL_HINTS,
    )
    assert picked is not None
    assert picked.dataset.name == "bills_2025"
    assert picked.columns["amount"] is not None
    assert picked.columns["model"] is not None


def test_dataset_picker_accepts_synonym_headers():
    picked = reports._pick_dataset(
        [DIRTY_BILLS],
        reports.BILL_COLUMNS,
        required=("amount", "date", "provider"),
        hints=reports.BILL_HINTS,
    )
    assert picked is not None
    assert picked.dataset.name == "bills_dirty_sample"
    assert picked.columns["date"] is not None


def test_quota_ratios_support_fraction_and_percent(monkeypatch):
    async def fake_aggregate(sql: str, allowed: set[str]):
        return [
            ("火山引擎", 5_740_000, 5_285_263.43, None, "2026-09-28"),
            ("DeepSeek", 6_348_000, 4_951_609.15, 78, "2026-05-28"),
        ]

    monkeypatch.setattr(reports, "_aggregate", fake_aggregate)

    table, rows = asyncio.run(reports._build_quota_table([QUOTAS]))

    assert rows[0]["provider"] == "火山引擎"
    assert round(rows[0]["ratio"], 4) == 0.9208
    assert rows[1]["ratio"] == 0.78
    assert table["rows"][0][3] == "92.1%"
    assert table["rows"][0][2] == 528.53


def test_quota_table_is_empty_without_quota_dataset():
    table, rows = asyncio.run(reports._build_quota_table([BILLS]))
    assert rows == []
    assert table["rows"] == []


def test_quota_table_matches_bill_year(monkeypatch):
    async def fake_aggregate(sql: str, allowed: set[str]):
        if "t_quotas_2026" in sql:
            return [("OpenAI", 1_000_000, 500_000, 0.5, "2027-01-28")]
        return [("火山引擎", 5_740_000, 5_285_263.43, 0.92, "2026-09-28")]

    monkeypatch.setattr(reports, "_aggregate", fake_aggregate)

    table_2025, rows_2025 = asyncio.run(
        reports._build_quota_table([QUOTAS, QUOTAS_2026], "2025")
    )
    table_2026, rows_2026 = asyncio.run(
        reports._build_quota_table([QUOTAS, QUOTAS_2026], "2026")
    )

    assert rows_2025[0]["provider"] == "火山引擎"
    assert table_2025["rows"][0][0] == "火山引擎"
    assert rows_2026[0]["provider"] == "OpenAI"
    assert table_2026["rows"][0][0] == "OpenAI"


def test_ranked_bill_datasets_prefers_latest_period(monkeypatch):
    async def fake_aggregate(sql: str, allowed: set[str]):
        if "t_bills_2026" in sql:
            return [("2026-01-01", "2026-09-30")]
        return [("2025-01-01", "2025-12-31")]

    monkeypatch.setattr(reports, "_aggregate", fake_aggregate)

    ranked = asyncio.run(reports._ranked_bill_datasets([BILLS, BILLS_2026]))
    options = asyncio.run(reports.list_bill_datasets([BILLS, BILLS_2026]))

    assert ranked[0][0].dataset.name == "bills_2026"
    assert options[0]["name"] == "bills_2026"
    assert options[0]["period_end"] == "2026-09-30"
    assert options[1]["name"] == "bills_2025"


def test_price_and_quota_tables_are_not_treated_as_bills():
    price_like = make_dataset(
        "price_book",
        84,
        [
            ("供应商", "供应商"),
            ("模型标识", "模型标识"),
            ("价格类型", "价格类型"),
            ("计价单位", "计价单位"),
            ("核实日期", "核实日期"),
            ("示例成本_USD", "示例成本_USD"),
        ],
        dataset_id="ds-price",
    )

    assert reports._bill_picked(BILLS) is not None
    assert reports._bill_picked(price_like) is None
    assert reports._bill_picked(QUOTAS) is None


def test_catalog_summary_uses_active_models_and_lowest_price(monkeypatch):
    async def fake_aggregate(sql: str, allowed: set[str]):
        if "display_name" in sql:
            return [
                ("OpenAI", "gpt-6-astra", "GPT-6 Astra", "active"),
                ("Anthropic", "claude-fable-5-1", "Claude Fable 5.1", "active"),
                ("Anthropic", "claude-legacy", "Claude Legacy", "legacy"),
            ]
        return [
            ("OpenAI", "gpt-6-astra", 10, 50),
            ("OpenAI", "gpt-6-astra", 20, 75),
            ("Anthropic", "claude-fable-5-1", 10, 50),
            ("Anthropic", "claude-legacy", 1, 1),
        ]

    monkeypatch.setattr(reports, "_aggregate", fake_aggregate)

    catalog = asyncio.run(reports._build_catalog_summary([MODEL_CATALOG, PRICE_BOOK]))

    assert catalog is not None
    assert catalog.total_models == 2
    assert catalog.provider_count == 2
    assert "2 个模型" in catalog.summary
    assert catalog.table.columns == [
        "供应商",
        "模型",
        "输入价(USD/百万)",
        "输出价(USD/百万)",
    ]
    assert ["OpenAI", "GPT-6 Astra", 10.0, 50.0] in catalog.table.rows
    assert all(row[0] != "Anthropic" or row[1] != "Claude Legacy" for row in catalog.table.rows)


def test_catalog_summary_requires_both_tables():
    assert asyncio.run(reports._build_catalog_summary([MODEL_CATALOG])) is None
    assert asyncio.run(reports._build_catalog_summary([PRICE_BOOK])) is None


def test_amount_column_prefers_total_over_input_cost():
    # 真实供应商导出（OpenAI / Anthropic）常同时有 Input Cost、Output Cost、Amount，
    # 报表总额必须取 Amount，而不是第一列 Cost。
    dataset = make_dataset(
        "openai_usage_2026-09",
        270,
        [
            ("Date", "Date"),
            ("Vendor", "Vendor"),
            ("Model", "Model"),
            ("Input Tokens", "Input_Tokens"),
            ("Output Tokens", "Output_Tokens"),
            ("Input Cost (USD)", "Input_Cost_USD"),
            ("Output Cost (USD)", "Output_Cost_USD"),
            ("Amount (USD)", "Amount_USD"),
        ],
    )

    column = reports._find_column(dataset, reports.BILL_COLUMNS["amount"])

    assert column is not None
    assert column.display == "Amount (USD)"


def test_period_filter_is_applied_to_every_bill_query(monkeypatch):
    sqls: list[str] = []
    results = iter(
        [
            [(100, 500_000, 1_000_000, "2026-07-01", "2026-09-30", 2, 3, 1)],
            [("OpenAI", 300_000), ("Anthropic", 200_000)],
            [("智能客服", 400_000)],
            [("2026-07", 200_000), ("2026-08", 150_000), ("2026-09", 150_000)],
            [("gpt-6", 500_000, 1_000_000)],
            [(400_000,)],
        ]
    )

    async def fake_aggregate(sql: str, allowed: set[str]):
        if "AS start_date" in sql:
            return [("2026-01-01", "2026-09-30")]
        sqls.append(sql)
        return next(results)

    monkeypatch.setattr(reports, "_aggregate", fake_aggregate)

    summary = asyncio.run(
        reports.build_report_summary(
            [BILLS],
            "ds-1",
            date(2026, 7, 1),
            date(2026, 9, 30),
        )
    )

    assert len(sqls) == 6
    assert all("2026-07-01" in sql and "2026-09-30" in sql for sql in sqls[:5])
    # 第 6 条是等长上一周期的环比查询。
    assert "2026-03-31" in sqls[5] and "2026-06-30" in sqls[5]
    assert summary.mom is not None
    assert summary.mom.previous_amount == 400_000
    assert summary.mom.change_pct == 25.0
    assert summary.kpis[0].label == "2026 年 7-9 月采购总成本"
    assert summary.dataset.period_start == "2026-07-01"
    assert summary.dataset.row_count == 100
    assert summary.monthly_chart is not None
    assert summary.monthly_chart.x == ["7月", "8月", "9月"]


def test_period_filter_rejects_reversed_range():
    with pytest.raises(reports.ReportFilterError):
        asyncio.run(
            reports.build_report_summary(
                [BILLS],
                "ds-1",
                date(2026, 9, 30),
                date(2026, 7, 1),
            )
        )


def test_period_filter_without_rows_raises(monkeypatch):
    async def fake_aggregate(sql: str, allowed: set[str]):
        if "AS start_date" in sql:
            return [("2026-01-01", "2026-09-30")]
        return [(0, 0, 0, None, None, 0, 0, 0)]

    monkeypatch.setattr(reports, "_aggregate", fake_aggregate)

    with pytest.raises(reports.ReportDataError, match="所选期间没有账单数据"):
        asyncio.run(
            reports.build_report_summary(
                [BILLS],
                "ds-1",
                date(2026, 7, 1),
                date(2026, 7, 31),
            )
        )


def test_period_label_variants():
    assert reports.period_label("2026-01-01", "2026-12-31") == "2026 年"
    assert reports.period_label("2026-01-01", "2026-09-30") == "2026 年 1-9 月"
    assert reports.period_label("2026-09-01", "2026-09-30") == "2026 年 9 月"
    assert reports.period_label("2025-09-01", "2026-09-30") == "2025-09-01 至 2026-09-30"
    assert reports.period_label("", "") == "本期"


def test_period_where_uses_cast_for_date_and_substring_for_text():
    date_column = ReflectedColumn(
        physical="bill_date",
        display="账单日期",
        sql_type="date",
        kind="date",
        sample="",
    )
    text_column = ReflectedColumn(
        physical="账期",
        display="账期",
        sql_type="text",
        kind="text",
        sample="",
    )

    date_sql = reports._period_where(date_column, date(2026, 7, 1), date(2026, 9, 30))
    text_sql = reports._period_where(text_column, date(2026, 7, 1), None)

    assert "CAST(\"bill_date\" AS date)" in date_sql
    assert "DATE '2026-07-01'" in date_sql
    assert "DATE '2026-09-30'" in date_sql
    assert "SUBSTRING(CAST(\"账期\" AS text) FROM 1 FOR 10) >= '2026-07-01'" in text_sql
    assert "<= " not in text_sql
    assert reports._period_where(text_column, None, None) == ""


def _column(display: str, physical: str, kind: str = "number") -> ReflectedColumn:
    return ReflectedColumn(
        physical=physical, display=display, sql_type="double precision", kind=kind
    )


def test_amount_expression_converts_usd_to_cny():
    columns = {
        "amount": _column("金额", "金额"),
        "currency": _column("币种", "币种", "text"),
    }

    expression = reports._amount_expr(columns)

    assert "USD" in expression
    assert "* 7.2" in expression
    assert "1 USD = 7.2 CNY" in reports._currency_note(columns)
    assert reports._currency_note({"amount": columns["amount"]}) is None


def test_provider_drilldown_filters_queries_and_switches_chart(monkeypatch):
    sqls: list[str] = []
    results = iter(
        [
            [(50, 300_000, 1_000_000, "2026-07-01", "2026-09-30", 1, 2, 0)],
            [("Anthropic", 300_000)],
            [("2026-07", 100_000), ("2026-08", 100_000), ("2026-09", 100_000)],
            [("claude-fable-5-1", 200_000, 700_000), ("claude-opus-5-5", 100_000, 300_000)],
        ]
    )

    async def fake_aggregate(sql: str, allowed: set[str]):
        if "AS start_date" in sql:
            return [("2026-01-01", "2026-09-30")]
        sqls.append(sql)
        return next(results)

    monkeypatch.setattr(reports, "_aggregate", fake_aggregate)

    summary = asyncio.run(
        reports.build_report_summary([BILLS], "ds-1", provider_filter="Anthropic")
    )

    assert sqls
    assert all('"供应商" = \'Anthropic\'' in sql for sql in sqls)
    assert summary.provider_filter == "Anthropic"
    assert summary.provider_chart.title == "Anthropic 各模型采购金额"
    assert summary.provider_chart.x == ["claude-fable-5-1", "claude-opus-5-5"]
    assert "Anthropic" in summary.kpis[0].label


def test_budget_table_compares_period_spend(monkeypatch):
    budgets = make_dataset(
        "budgets_2026",
        2,
        [("供应商", "供应商"), ("年度预算", "年度预算")],
        dataset_id="ds-budget",
    )
    sqls: list[str] = []

    async def fake_aggregate(sql: str, allowed: set[str]):
        sqls.append(sql)
        return [("Anthropic", 2_000_000), ("OpenAI", 1_000_000)]

    monkeypatch.setattr(reports, "_aggregate", fake_aggregate)

    budget = asyncio.run(
        reports._build_budget_table(
            [budgets],
            [
                {"name": "Anthropic", "amount": 1_900_000},
                {"name": "OpenAI", "amount": 200_000},
            ],
            "2026",
            None,
        )
    )

    assert budget is not None
    assert budget.annual_total == 3_000_000
    assert budget.used_total == 2_100_000
    assert budget.usage_pct == 70.0
    assert budget.table.rows[0][0] == "Anthropic"
    assert budget.table.rows[0][3] == "95.0%"
    assert "2026" in sqls[0] or "budgets" in sqls[0]
