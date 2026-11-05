"""报表汇总。

不依赖固定表结构：从已注册数据集中按字段语义找出「账单」和「配额」表，
再用反射出的物理列名拼出只读聚合 SQL。换一份同义表头的 Excel 也能直接出报表。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from typing import Any

from app.api.v1.schemas import (
    ReportBudgetOut,
    ReportCatalogOut,
    ReportChartOut,
    ReportDatasetOut,
    ReportInsightOut,
    ReportKpiOut,
    ReportMomOut,
    ReportPurchasingOut,
    ReportSummaryOut,
    TableOut,
)
from app.core.config import get_settings
from app.db.sql import qualified, quote_ident
from app.services.datasets import DatasetMeta, ReflectedColumn
from app.services.query import execute_readonly, validate_readonly_sql

_STRIP = re.compile(r"[\s_()（）\[\]【】/\\·.\-]+")
_YEAR = re.compile(r"20\d{2}")

BILL_COLUMNS = {
    "amount": ("金额_元", "金额(元)", "金额", "费用", "成本", "amount", "cost"),
    "date": ("账期", "日期", "月份", "统计日期", "bill_date", "date", "month"),
    "provider": ("供应商", "厂商", "服务商", "provider", "vendor"),
    "app": ("应用", "应用名称", "业务线", "场景", "app"),
    "model": ("模型", "模型名称", "model"),
    "input_tokens": ("输入token", "输入tokens", "input_tokens", "prompt_tokens"),
    "output_tokens": ("输出token", "输出tokens", "output_tokens", "completion_tokens"),
    "currency": ("币种", "货币", "currency", "币别"),
}
BILL_HINTS = ("bill", "账单", "采购", "成本", "cost")

QUOTA_COLUMNS = {
    "provider": ("供应商", "厂商", "服务商", "provider", "vendor"),
    "committed": ("承诺金额_元", "承诺金额(元)", "承诺金额", "合同金额", "quota"),
    "used": ("已用金额_元", "已用金额(元)", "已用金额", "已使用金额", "used"),
    "usage": ("使用率", "使用比例", "usage_rate"),
    "expiry": ("到期日", "合同到期日", "有效期至", "expiry"),
}
QUOTA_HINTS = ("quota", "配额", "合同", "contract")

CATALOG_COLUMNS = {
    "provider": ("供应商", "厂商", "provider"),
    "model_id": ("模型标识", "模型ID", "模型id", "model_id", "model"),
    "display": ("显示名称", "模型名称", "名称", "display_name"),
    "status": ("状态", "status"),
}
CATALOG_HINTS = ("catalog", "模型清单", "model")

PRICE_COLUMNS = {
    "provider": ("供应商", "厂商", "provider"),
    "model_id": ("模型标识", "模型ID", "模型id", "model_id", "model"),
    "price_type": ("价格类型", "price_type"),
    "input_usd": ("折算输入价_USD", "输入价_USD", "input_usd"),
    "output_usd": ("折算输出价_USD", "输出价_USD", "output_usd"),
    "effective_end": ("生效结束", "effective_end"),
}
PRICE_HINTS = ("price", "价格", "报价")

BUDGET_COLUMNS = {
    "provider": ("供应商", "厂商", "服务商", "provider", "vendor"),
    "annual": ("年度预算", "年度预算金额", "预算金额", "预算", "annual_budget", "budget"),
}
BUDGET_HINTS = ("budget", "预算")

QUOTE_COLUMNS = {
    "provider": ("供应商", "厂商", "服务商", "provider", "vendor"),
    "model": ("模型", "模型名称", "model"),
    "input_price": ("输入单价", "输入价", "input_price", "input_usd"),
    "output_price": ("输出单价", "输出价", "output_price", "output_usd"),
    "discount": ("商务折扣", "折扣", "discount"),
    "valid_until": ("有效期至", "报价有效期", "有效期", "valid_until"),
}
QUOTE_HINTS = ("quote", "报价")

HIGH_RISK_USAGE = 0.85
BUDGET_WARN_USAGE = 0.9


class ReportDataError(ValueError):
    """没有可用于生成报表的数据集。"""


class ReportFilterError(ValueError):
    """报表筛选条件不合法（例如开始日期晚于结束日期）。"""


@dataclass
class _Picked:
    dataset: DatasetMeta
    columns: dict[str, ReflectedColumn | None]


def _norm(value: str) -> str:
    return _STRIP.sub("", value).lower()


def _find_column(
    dataset: DatasetMeta, candidates: tuple[str, ...]
) -> ReflectedColumn | None:
    wanted = {_norm(item) for item in candidates}
    for column in dataset.columns:
        if _norm(column.display) in wanted:
            return column

    # 子串匹配时优先更具体的候选词：真实供应商导出里常同时出现
    # 「Input Cost / Output Cost / Amount」，金额维度应选 Amount 而不是第一列 Cost。
    matches: list[tuple[int, int, int, ReflectedColumn]] = []
    for index, column in enumerate(dataset.columns):
        key = _norm(column.display)
        lengths = [len(item) for item in wanted if item and item in key]
        if not lengths:
            continue
        # 候选词越长越具体；同分时列名越短越像合计列；再同分则保持原列顺序。
        matches.append((max(lengths), -len(key), -index, column))
    if not matches:
        return None
    matches.sort(key=lambda entry: entry[:3], reverse=True)
    return matches[0][3]


def _pick_dataset(
    datasets: list[DatasetMeta],
    spec: dict[str, tuple[str, ...]],
    required: tuple[str, ...],
    hints: tuple[str, ...],
) -> _Picked | None:
    best: tuple[tuple[int, int], _Picked] | None = None
    for dataset in datasets:
        columns = {key: _find_column(dataset, candidates) for key, candidates in spec.items()}
        if any(columns.get(key) is None for key in required):
            continue

        name = dataset.name.lower()
        hinted = int(any(hint in name for hint in hints))
        score = (hinted, dataset.row_count)
        if best is None or score > best[0]:
            best = (score, _Picked(dataset=dataset, columns=columns))
    return best[1] if best else None


def _q(column: ReflectedColumn | None, fallback: str = "NULL") -> str:
    return quote_ident(column.physical) if column else fallback


def _numeric(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _wan(value: float) -> float:
    return round(value / 10000, 2)


def _fmt(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}"


def _pct(part: float, whole: float) -> str:
    if not whole:
        return "0.0%"
    return f"{part / whole * 100:.1f}%"


def _sp(name: str) -> str:
    """中文名后不加空格，英文名后留一个空格，避免「火山引擎 已用」这类排版。"""
    return f"{name} " if name and name[-1].isascii() and name[-1].isalnum() else name


def _as_date_text(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")


def _period_where(
    date_col: ReflectedColumn | None,
    start_date: date | None,
    end_date: date | None,
) -> str:
    """按账期过滤的 SQL 片段。

    文本列先取前 10 位再比较，避免脏数据里出现无法 CAST 的值导致整条 SQL 失败；
    真正的 date / timestamp 列则用 CAST 保留日期语义。
    """
    if date_col is None or (start_date is None and end_date is None):
        return ""

    if date_col.kind == "date":
        compared = f"CAST({_q(date_col)} AS date)"
        start_literal = f"DATE '{start_date.isoformat()}'" if start_date else ""
        end_literal = f"DATE '{end_date.isoformat()}'" if end_date else ""
    else:
        compared = f"SUBSTRING(CAST({_q(date_col)} AS text) FROM 1 FOR 10)"
        start_literal = f"'{start_date.isoformat()}'" if start_date else ""
        end_literal = f"'{end_date.isoformat()}'" if end_date else ""

    conditions = []
    if start_literal:
        conditions.append(f"{compared} >= {start_literal}")
    if end_literal:
        conditions.append(f"{compared} <= {end_literal}")
    return f"WHERE {' AND '.join(conditions)}"


def _literal(value: str) -> str:
    """把用户输入拼进字面量时转义单引号。"""
    return "'" + value.replace("'", "''") + "'"


def _amount_expr(columns: dict[str, ReflectedColumn | None]) -> str:
    """账单金额表达式：检测到币种列时把 USD 折算为人民币。"""
    amount = _q(columns.get("amount"))
    currency = columns.get("currency")
    if currency is None:
        return amount
    rate = get_settings().fx_usd_cny
    flags = f"UPPER(COALESCE(CAST({_q(currency)} AS text), ''))"
    return (
        f"(CASE WHEN {flags} IN ('USD', 'US$', '$', '美元') "
        f"THEN COALESCE({amount}, 0) * {rate:.6g} "
        f"ELSE COALESCE({amount}, 0) END)"
    )


def _currency_note(columns: dict[str, ReflectedColumn | None]) -> str | None:
    if columns.get("currency") is None:
        return None
    rate = get_settings().fx_usd_cny
    return f"账单中的 USD 金额已按 1 USD = {rate:g} CNY 折算为人民币，其余币种按原值统计。"


def _provider_where(
    provider_col: ReflectedColumn | None, provider: str | None
) -> str:
    if provider_col is None or not provider:
        return ""
    return f"WHERE {_q(provider_col)} = {_literal(provider)}"


def _combine_where(*parts: str) -> str:
    conditions = [part[6:].strip() for part in parts if part]
    conditions = [condition for condition in conditions if condition]
    return f"WHERE {' AND '.join(conditions)}" if conditions else ""


def previous_period(start: date, end: date) -> tuple[date, date]:
    """返回与 [start, end] 等长的上一个期间。"""
    length = (end - start).days + 1
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=length - 1)
    return previous_start, previous_end


def period_label(start: str, end: str) -> str:
    """把实际账期格式化成「2026 年 1-9 月」这类可读标签。"""
    start = (start or "")[:10]
    end = (end or "")[:10]
    if not start and not end:
        return "本期"
    if not start or not end:
        return (start or end)[:7]

    start_year, start_month = start[:4], start[5:7]
    end_year, end_month = end[:4], end[5:7]
    if start_year and start_year == end_year:
        if start_month == "01" and end_month == "12":
            return f"{start_year} 年"
        if start[:7] == end[:7]:
            return f"{start_year} 年 {int(start_month)} 月"
        if start_month.isdigit() and end_month.isdigit():
            return f"{start_year} 年 {int(start_month)}-{int(end_month)} 月"
        return f"{start_year} 年"
    return f"{start} 至 {end}"


async def _aggregate(sql: str, allowed: set[str]) -> list[list[Any]]:
    checked = validate_readonly_sql(sql, allowed)
    result = await execute_readonly(checked)
    return result.rows


# 价目表 / 模型清单 / 配额表也可能带「供应商、成本、日期」等字段，
# 用这些强特征字段把它们排除在账单候选之外。
_BILL_EXCLUDE_COLUMNS = ("价格类型", "模型标识", "计价单位", "显示名称", "承诺金额")


def _bill_picked(dataset: DatasetMeta) -> _Picked | None:
    headers = {_norm(column.display) for column in dataset.columns}
    if headers.intersection({_norm(item) for item in _BILL_EXCLUDE_COLUMNS}):
        return None

    columns = {key: _find_column(dataset, candidates) for key, candidates in BILL_COLUMNS.items()}
    if any(columns.get(key) is None for key in ("amount", "date", "provider")):
        return None
    return _Picked(dataset=dataset, columns=columns)


async def _date_period(picked: _Picked) -> tuple[str, str]:
    date_col = _q(picked.columns["date"])
    table = qualified("ds", picked.dataset.physical_table)
    rows = await _aggregate(
        f"SELECT MIN({date_col}) AS start_date, MAX({date_col}) AS end_date FROM {table}",
        {picked.dataset.full_table},
    )
    if not rows:
        return "", ""
    start, end = rows[0]
    return _as_date_text(start), _as_date_text(end)


async def _ranked_bill_datasets(datasets: list[DatasetMeta]) -> list[tuple[_Picked, str, str]]:
    candidates = []
    for dataset in datasets:
        picked = _bill_picked(dataset)
        if picked is None:
            continue
        start, end = await _date_period(picked)
        candidates.append((picked, start, end))

    # 默认选账期最新的数据集；同账期时选行数更多的。
    candidates.sort(key=lambda item: (item[2], item[0].dataset.row_count), reverse=True)
    return candidates


async def list_bill_datasets(datasets: list[DatasetMeta]) -> list[dict[str, Any]]:
    ranked = await _ranked_bill_datasets(datasets)
    return [
        {
            "id": picked.dataset.id,
            "name": picked.dataset.name,
            "row_count": picked.dataset.row_count,
            "period_start": start,
            "period_end": end,
        }
        for picked, start, end in ranked
    ]


async def _resolve_bill_dataset(
    datasets: list[DatasetMeta], dataset_id: str | None
) -> _Picked | None:
    ranked = await _ranked_bill_datasets(datasets)
    if not ranked:
        return None
    if dataset_id:
        for picked, _start, _end in ranked:
            if picked.dataset.id == dataset_id:
                return picked
        return None
    return ranked[0][0]


async def build_report_summary(
    datasets: list[DatasetMeta],
    dataset_id: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    provider_filter: str | None = None,
) -> ReportSummaryOut:
    if start_date and end_date and start_date > end_date:
        raise ReportFilterError("开始日期不能晚于结束日期。")

    bills = await _resolve_bill_dataset(datasets, dataset_id)
    if bills is None:
        raise ReportDataError(
            "未找到可用的账单数据集。请上传包含「金额 / 账期 / 供应商」字段的 Excel。"
        )

    dataset = bills.dataset
    columns = bills.columns
    table = qualified("ds", dataset.physical_table)
    allowed = {dataset.full_table}
    provider_filter = (provider_filter or "").strip() or None
    where = _combine_where(
        _period_where(columns["date"], start_date, end_date),
        _provider_where(columns["provider"], provider_filter),
    )

    amount = _amount_expr(columns)
    date_col = columns["date"]
    provider = _q(columns["provider"], "'未标注'")
    app = _q(columns["app"], "'未标注'")
    model = _q(columns["model"])

    input_tokens = _q(columns["input_tokens"], "0")
    output_tokens = _q(columns["output_tokens"], "0")
    has_tokens = bool(columns["input_tokens"] or columns["output_tokens"])
    tokens_expr = f"(COALESCE({input_tokens}, 0) + COALESCE({output_tokens}, 0))"

    totals_sql = f"""
        SELECT COUNT(*) AS row_count,
               COALESCE(SUM({amount}), 0) AS total_amount,
               {"COALESCE(SUM(" + tokens_expr + "), 0)" if has_tokens else "0"} AS total_tokens,
               MIN({_q(date_col)}) AS min_date,
               MAX({_q(date_col)}) AS max_date,
               COUNT(DISTINCT {provider}) AS provider_count,
               {"COUNT(DISTINCT " + model + ")" if model else "0"} AS model_count,
               {"COUNT(DISTINCT " + app + ")" if columns["app"] else "0"} AS app_count
        FROM {table}
        {where}
    """
    totals = (await _aggregate(totals_sql, allowed))[0]

    row_count = int(totals[0] or 0)
    if row_count == 0:
        raise ReportDataError(
            f"供应商「{provider_filter}」在所选期间没有账单数据，请调整筛选条件。"
            if provider_filter
            else "所选期间没有账单数据，请调整日期范围。"
        )
    total_amount = _numeric(totals[1])
    total_tokens = _numeric(totals[2])
    period_start = _as_date_text(totals[3])
    period_end = _as_date_text(totals[4])
    provider_count = int(totals[5] or 0)
    model_count = int(totals[6] or 0)
    app_count = int(totals[7] or 0)

    providers = await _aggregate(
        f"""
        SELECT {provider} AS name, COALESCE(SUM({amount}), 0) AS amount
        FROM {table}
        {where}
        GROUP BY 1
        ORDER BY 2 DESC
        """,
        allowed,
    )
    provider_rows = [
        {"name": str(name or "未标注"), "amount": _numeric(value)} for name, value in providers
    ]

    app_rows: list[dict[str, Any]] = []
    if columns["app"] and app_count:
        apps = await _aggregate(
            f"""
            SELECT {app} AS name, COALESCE(SUM({amount}), 0) AS amount
            FROM {table}
            {where}
            GROUP BY 1
            ORDER BY 2 DESC
            """,
            allowed,
        )
        app_rows = [
            {"name": str(name or "未标注"), "amount": _numeric(value)} for name, value in apps
        ]

    month_expr = (
        f"to_char({_q(date_col)}, 'YYYY-MM')"
        if date_col and date_col.kind == "date"
        else f"substring(CAST({_q(date_col)} AS text) FROM 1 FOR 7)"
    )
    months = await _aggregate(
        f"""
        SELECT {month_expr} AS label, COALESCE(SUM({amount}), 0) AS amount
        FROM {table}
        {where}
        GROUP BY 1
        ORDER BY 1
        """,
        allowed,
    )
    month_rows = [
        {"label": str(label or ""), "amount": _numeric(value)}
        for label, value in months
        if label
    ]

    model_rows: list[dict[str, Any]] = []
    if model and (has_tokens or provider_filter):
        models = await _aggregate(
            f"""
            SELECT {model} AS name,
                   COALESCE(SUM({amount}), 0) AS amount,
                   COALESCE(SUM({tokens_expr}), 0) AS tokens
            FROM {table}
            {where}
            GROUP BY 1
            ORDER BY 2 DESC
            """,
            allowed,
        )
        model_rows = [
            {"name": str(name or "未标注"), "amount": _numeric(amount), "tokens": _numeric(tokens)}
            for name, amount, tokens in models
        ]

    quota_table, quota_rows = await _build_quota_table(datasets, period_start[:4])

    mom: ReportMomOut | None = None
    if start_date and end_date:
        previous_start, previous_end = previous_period(start_date, end_date)
        previous_where = _combine_where(
            _period_where(columns["date"], previous_start, previous_end),
            _provider_where(columns["provider"], provider_filter),
        )
        previous_rows = await _aggregate(
            f"SELECT COALESCE(SUM({amount}), 0) AS amount FROM {table} {previous_where}",
            allowed,
        )
        previous_amount = _numeric(previous_rows[0][0]) if previous_rows else 0.0
        change_pct = (
            (total_amount - previous_amount) / previous_amount * 100
            if previous_amount
            else None
        )
        mom = ReportMomOut(
            previous_start=previous_start.isoformat(),
            previous_end=previous_end.isoformat(),
            previous_amount=round(previous_amount, 2),
            change_pct=round(change_pct, 1) if change_pct is not None else None,
        )

    budget = await _build_budget_table(
        datasets, provider_rows, period_start[:4], provider_filter
    )
    purchasing = await _build_purchasing_summary(datasets)

    top_provider = provider_rows[0] if provider_rows else {"name": "—", "amount": 0.0}
    top_share = top_provider["amount"] / total_amount if total_amount else 0.0
    top_two_share = (
        sum(item["amount"] for item in provider_rows[:2]) / total_amount if total_amount else 0.0
    )
    top_model = model_rows[0] if model_rows else None
    focus_share = (
        top_model["amount"] / total_amount
        if provider_filter and top_model and total_amount
        else top_share
    )

    max_growth: dict[str, Any] | None = None
    for previous, current in pairwise(month_rows):
        if previous["amount"] > 0:
            growth = current["amount"] / previous["amount"] - 1
            if max_growth is None or growth > max_growth["growth"]:
                max_growth = {"label": current["label"], "growth": growth, "amount": current["amount"]}

    top_app = app_rows[0] if app_rows else None
    top_quota = quota_rows[0] if quota_rows else None

    cost_delta = []
    if mom is not None and mom.change_pct is not None:
        cost_delta.append(f"环比 {mom.change_pct:+.1f}%")
    if provider_filter:
        cost_delta.append(f"已筛选供应商「{provider_filter}」")
    else:
        cost_delta.append(f"覆盖 {provider_count} 家供应商 · {model_count} 个模型")

    kpis: list[dict[str, Any]] = [
        {
            "label": (
                f"{provider_filter} {period_label(period_start, period_end)}采购成本"
                if provider_filter
                else f"{period_label(period_start, period_end)}采购总成本"
            ),
            "value": _fmt(total_amount / 10000),
            "unit": "万元",
            "delta": " · ".join(cost_delta),
            "warn": focus_share >= 0.6,
        },
        {
            "label": "累计调用量",
            "value": f"{total_tokens / 1e8:.1f}" if total_tokens else "—",
            "unit": "亿 tokens",
            "delta": f"{period_start} 至 {period_end}" if period_start else "账单明细合计",
            "warn": False,
        },
        {
            "label": "平均综合单价",
            "value": f"{total_amount / total_tokens * 1000:.2f}" if total_tokens else "—",
            "unit": "元/千token",
            "delta": "账单金额 ÷（输入 + 输出 token）",
            "warn": False,
        },
        {
            "label": "高风险配额合同",
            "value": str(len([row for row in quota_rows if row["ratio"] >= HIGH_RISK_USAGE])),
            "unit": "份",
            "delta": (
                f"{_sp(top_quota['provider'])}已用 {_pct(top_quota['used'], top_quota['committed'])}"
                if top_quota
                else "未找到配额数据集"
            ),
            "warn": bool(top_quota and top_quota["ratio"] >= HIGH_RISK_USAGE),
        },
    ]

    insights: list[dict[str, str]] = []
    if provider_rows and total_amount:
        insights.append(
            {
                "title": f"{_sp(top_provider['name'])}占采购成本 {_pct(top_provider['amount'], total_amount)}",
                "meta": (
                    f"前两家供应商合计 {top_two_share * 100:.1f}%，"
                    f"金额 {_fmt(top_provider['amount'] / 10000)} 万元；"
                    "集中度偏高时建议保留第二供应商的议价空间。"
                ),
                "tag": "成本结构",
            }
        )

    if max_growth:
        month_label = max_growth["label"]
        display_month = (
            f"{int(month_label[5:7])} 月" if len(month_label) >= 7 else month_label
        )
        insights.append(
            {
                "title": f"{display_month}成本环比 +{max_growth['growth'] * 100:.1f}%",
                "meta": (
                    f"当月成本 {_fmt(max_growth['amount'] / 10000)} 万元，"
                    "为统计周期内最大单月增幅，建议结合调用量与单价变化归因。"
                ),
                "tag": "趋势变化",
            }
        )

    if top_quota:
        insights.append(
            {
                "title": f"{_sp(top_quota['provider'])}配额已用 {_pct(top_quota['used'], top_quota['committed'])}",
                "meta": (
                    f"已用 {_fmt(top_quota['used'] / 10000)} / "
                    f"{_fmt(top_quota['committed'] / 10000)} 万元，"
                    f"到期日 {top_quota['expiry'] or '未知'}；"
                    "已进入高风险区间时建议提前启动续约询价。"
                ),
                "tag": "配额风险",
            }
        )

    if mom is not None and mom.change_pct is not None:
        direction = "上升" if mom.change_pct >= 0 else "下降"
        insights.append(
            {
                "title": f"较上一周期{direction} {abs(mom.change_pct):.1f}%",
                "meta": (
                    f"本期 {_fmt(total_amount / 10000)} 万元，"
                    f"上一周期（{mom.previous_start} 至 {mom.previous_end}）"
                    f"{_fmt(mom.previous_amount / 10000)} 万元；"
                    "连续两个期间对比可快速发现采购节奏变化。"
                ),
                "tag": "环比变化",
            }
        )

    if provider_filter and top_model and total_amount:
        insights.append(
            {
                "title": (
                    f"{_sp(provider_filter)}下 {_sp(top_model['name'])}占成本 "
                    f"{_pct(top_model['amount'], total_amount)}"
                ),
                "meta": (
                    f"当前供应商共 {model_count} 个模型产生费用，"
                    f"成本最高的模型为 {top_model['name']}；"
                    "可进一步比较同类模型单价，评估替换或议价空间。"
                ),
                "tag": "下钻分析",
            }
        )

    if budget is not None and budget.usage_pct >= BUDGET_WARN_USAGE * 100:
        insights.append(
            {
                "title": f"年度预算已使用 {budget.usage_pct:.1f}%",
                "meta": (
                    f"所选期间实际支出 {_fmt(budget.used_total / 10000)} 万元，"
                    f"年度预算 {_fmt(budget.annual_total / 10000)} 万元；"
                    "已接近或超出预算，建议提前评估剩余期间的采购计划。"
                ),
                "tag": "预算预警",
            }
        )

    priced_models = [
        {
            **row,
            "unit_price": row["amount"] / row["tokens"] * 1000,
        }
        for row in model_rows
        if row["tokens"] > 0 and row["amount"] > 0
    ]
    if len(priced_models) >= 2:
        priced_models.sort(key=lambda row: row["unit_price"])
        cheapest = priced_models[0]
        priciest = priced_models[-1]
        ratio = cheapest["unit_price"] / priciest["unit_price"] if priciest["unit_price"] else 0
        insights.append(
            {
                "title": f"{_sp(cheapest['name'])}单位成本仅为 {_sp(priciest['name'])}的 {ratio * 100:.1f}%",
                "meta": (
                    f"{cheapest['name']} {cheapest['unit_price']:.2f} 元/千token，"
                    f"{priciest['name']} {priciest['unit_price']:.2f} 元/千token；"
                    "高成本模型应优先评估可替代的低价模型。"
                ),
                "tag": "比价建议",
            }
        )

    if provider_filter and model_rows:
        provider_chart = {
            "type": "bar",
            "title": f"{provider_filter} 各模型采购金额",
            "x": [row["name"] for row in model_rows],
            "series": [{"name": "采购金额", "data": [_wan(row["amount"]) for row in model_rows]}],
            "unit": "万元",
        }
    else:
        provider_chart = {
            "type": "bar",
            "title": "各供应商采购金额",
            "x": [row["name"] for row in provider_rows],
            "series": [
                {"name": "采购金额", "data": [_wan(row["amount"]) for row in provider_rows]}
            ],
            "unit": "万元",
        }

    app_chart = (
        {
            "type": "pie",
            "title": "成本按应用分布",
            "data": [{"name": row["name"], "value": _wan(row["amount"])} for row in app_rows],
            "unit": "万元",
        }
        if app_rows
        else None
    )

    year = period_start[:4]
    monthly_chart = (
        {
            "type": "line",
            "title": f"{year} 年月度采购成本",
            "x": [
                f"{int(row['label'][5:7])}月"
                if len(row["label"]) >= 7 and row["label"][5:7].isdigit()
                else row["label"]
                for row in month_rows
            ],
            "series": [{"name": "成本", "data": [_wan(row["amount"]) for row in month_rows]}],
            "unit": "万元",
        }
        if month_rows
        else None
    )

    return ReportSummaryOut(
        generated_at=datetime.now(UTC),
        dataset=ReportDatasetOut(
            id=dataset.id,
            name=dataset.name,
            source_file=dataset.source_file,
            row_count=row_count,
            period_start=period_start,
            period_end=period_end,
        ),
        kpis=[ReportKpiOut(**item) for item in kpis],
        provider_chart=ReportChartOut(**provider_chart),
        app_chart=ReportChartOut(**app_chart) if app_chart else None,
        monthly_chart=ReportChartOut(**monthly_chart) if monthly_chart else None,
        quota_table=TableOut(columns=quota_table["columns"], rows=quota_table["rows"]),
        catalog=await _build_catalog_summary(datasets),
        provider_summary=(
            (
                f"{_sp(provider_filter)}下 {_sp(top_model['name'])}占成本 "
                f"{_pct(top_model['amount'], total_amount)}，共 {model_count} 个模型产生费用"
                if top_model
                else f"已筛选供应商「{provider_filter}」，暂无模型维度数据"
            )
            if provider_filter
            else (
                f"{_sp(top_provider['name'])}占 {_pct(top_provider['amount'], total_amount)}，"
                f"前两家合计 {top_two_share * 100:.1f}%"
                if provider_rows
                else "暂无供应商数据"
            )
        ),
        app_summary=(
            f"{_sp(top_app['name'])}是最大成本中心，占 {_pct(top_app['amount'], total_amount)}"
            if top_app and total_amount
            else "暂无应用维度数据"
        ),
        monthly_summary=(
            f"{max_growth['label']} 环比 +{max_growth['growth'] * 100:.1f}%，为统计期内最大单月增幅"
            if max_growth
            else "暂无月度数据"
        ),
        quota_summary=(
            f"{_sp(top_quota['provider'])}已用 {_pct(top_quota['used'], top_quota['committed'])}，"
            f"{'已进入高风险区间' if top_quota['ratio'] >= HIGH_RISK_USAGE else '整体处于安全区间'}"
            if top_quota
            else "尚未上传合同配额数据"
        ),
        insights=[ReportInsightOut(**item) for item in insights],
        model_count=model_count,
        app_count=app_count,
        provider_filter=provider_filter,
        mom=mom,
        budget=budget,
        purchasing=purchasing,
        currency_note=_currency_note(columns),
    )


async def _build_budget_table(
    datasets: list[DatasetMeta],
    provider_rows: list[dict[str, Any]],
    bill_year: str,
    provider_filter: str | None,
) -> ReportBudgetOut | None:
    """年度预算 vs 所选期间实际支出。"""
    budget_like = [
        dataset
        for dataset in datasets
        if all(
            _find_column(dataset, BUDGET_COLUMNS[key]) is not None
            for key in ("provider", "annual")
        )
    ]
    scoped = budget_like
    if bill_year:
        matched = [dataset for dataset in budget_like if bill_year in _YEAR.findall(dataset.name)]
        neutral = [dataset for dataset in budget_like if not _YEAR.findall(dataset.name)]
        scoped = matched or neutral

    picked = _pick_dataset(
        scoped,
        BUDGET_COLUMNS,
        required=("provider", "annual"),
        hints=BUDGET_HINTS,
    )
    if picked is None:
        return None

    dataset = picked.dataset
    columns = picked.columns
    table = qualified("ds", dataset.physical_table)
    rows = await _aggregate(
        f"""
        SELECT {_q(columns["provider"], "'未标注'")} AS provider,
               COALESCE(SUM({_q(columns["annual"])}), 0) AS annual
        FROM {table}
        GROUP BY 1
        """,
        {dataset.full_table},
    )

    spent: dict[str, float] = {
        _norm(str(row["name"])): row["amount"] for row in provider_rows
    }
    entries: list[tuple[str, float, float, float]] = []
    annual_total = 0.0
    used_total = 0.0
    for name, annual_value in rows:
        provider_name = str(name or "未标注")
        if provider_filter and _norm(provider_name) != _norm(provider_filter):
            continue
        annual = _numeric(annual_value)
        used = spent.get(_norm(provider_name), 0.0)
        annual_total += annual
        used_total += used
        entries.append((provider_name, annual, used, used / annual if annual else 0.0))

    if not entries:
        return None

    entries.sort(key=lambda entry: entry[3], reverse=True)
    table_rows = [
        [name, _wan(annual), _wan(used), f"{usage * 100:.1f}%"]
        for name, annual, used, usage in entries
    ]
    usage_pct = used_total / annual_total * 100 if annual_total else 0.0
    over = len([entry for entry in entries if entry[3] >= BUDGET_WARN_USAGE])
    summary = (
        f"所选期间实际支出 {_fmt(used_total / 10000)} 万元，"
        f"对应年度预算 {_fmt(annual_total / 10000)} 万元，"
        f"整体使用率 {usage_pct:.1f}%；{over} 家供应商已超过 90% 预算。"
        if over
        else (
            f"所选期间实际支出 {_fmt(used_total / 10000)} 万元，"
            f"对应年度预算 {_fmt(annual_total / 10000)} 万元，整体使用率 {usage_pct:.1f}%。"
        )
    )

    return ReportBudgetOut(
        summary=summary,
        table=TableOut(
            columns=["供应商", "年度预算(万元)", "所选期间已用(万元)", "预算使用率"],
            rows=table_rows,
        ),
        annual_total=round(annual_total, 2),
        used_total=round(used_total, 2),
        usage_pct=round(usage_pct, 1),
    )


def _dataset_name_has(dataset: DatasetMeta, hints: Iterable[str]) -> bool:
    name = dataset.name.lower()
    return any(hint in name for hint in hints)


async def _build_purchasing_summary(
    datasets: list[DatasetMeta],
) -> ReportPurchasingOut | None:
    """报价单 / 套餐 / 限流规则等采购底表的出口。"""
    quotes = _pick_dataset(
        datasets,
        QUOTE_COLUMNS,
        required=("provider", "model", "input_price"),
        hints=QUOTE_HINTS,
    )
    plan_count = sum(
        dataset.row_count
        for dataset in datasets
        if _dataset_name_has(dataset, ("plan", "套餐", "订阅", "subscription"))
    )
    rate_limit_count = sum(
        dataset.row_count
        for dataset in datasets
        if _dataset_name_has(dataset, ("rate", "限流", "rate_limit"))
    )
    if quotes is None and not plan_count and not rate_limit_count:
        return None

    quote_table = {"columns": ["供应商", "模型", "输入价", "输出价", "商务折扣", "有效期"], "rows": []}
    quote_count = 0
    if quotes is not None:
        dataset = quotes.dataset
        columns = quotes.columns
        rows = await _aggregate(
            f"""
            SELECT {_q(columns["provider"], "'未标注'")} AS provider,
                   {_q(columns["model"], "'未标注'")} AS model,
                   {_q(columns["input_price"])} AS input_price,
                   {_q(columns["output_price"], "NULL")} AS output_price,
                   {_q(columns["discount"], "NULL")} AS discount,
                   {_q(columns["valid_until"], "NULL")} AS valid_until
            FROM {qualified("ds", dataset.physical_table)}
            """,
            {dataset.full_table},
        )
        quote_count = len(rows)
        rows = sorted(rows, key=lambda row: _numeric(row[2]), reverse=True)[:10]
        quote_table["rows"] = [
            [
                str(provider or "未标注"),
                str(model or "未标注"),
                round(_numeric(input_price), 4),
                round(_numeric(output_price), 4) if output_price is not None else "—",
                str(discount) if discount is not None else "—",
                _as_date_text(valid_until) if valid_until is not None else "—",
            ]
            for provider, model, input_price, output_price, discount, valid_until in rows
        ]

    parts = []
    if quote_count:
        parts.append(f"{quote_count} 条报价")
    if plan_count:
        parts.append(f"{plan_count} 个套餐")
    if rate_limit_count:
        parts.append(f"{rate_limit_count} 条限流规则")
    summary = "；".join(parts) + "。报价单按输入价从高到低展示前 10 条。" if parts else "暂无采购底表。"

    return ReportPurchasingOut(
        summary=summary,
        quote_table=TableOut(columns=quote_table["columns"], rows=quote_table["rows"]),
        plan_count=plan_count,
        rate_limit_count=rate_limit_count,
    )


async def _build_quota_table(
    datasets: list[DatasetMeta],
    bill_year: str = "",
) -> tuple[dict[str, list[Any]], list[dict[str, Any]]]:
    # 优先使用与账单同一年度的合同配额，避免 2025 账单搭配 2026 配额。
    quota_like = [
        dataset
        for dataset in datasets
        if all(
            _find_column(dataset, QUOTA_COLUMNS[key]) is not None
            for key in ("provider", "committed", "used")
        )
    ]
    scoped = quota_like
    if bill_year:
        matched = [dataset for dataset in quota_like if bill_year in _YEAR.findall(dataset.name)]
        neutral = [dataset for dataset in quota_like if not _YEAR.findall(dataset.name)]
        scoped = matched or neutral

    picked = _pick_dataset(
        scoped,
        QUOTA_COLUMNS,
        required=("provider", "committed", "used"),
        hints=QUOTA_HINTS,
    )
    empty = {"columns": ["供应商", "承诺金额(万元)", "已用金额(万元)", "使用率", "到期日"], "rows": []}
    if picked is None:
        return empty, []

    dataset = picked.dataset
    columns = picked.columns
    table = qualified("ds", dataset.physical_table)
    allowed = {dataset.full_table}

    expiry = _q(columns["expiry"], "''")
    usage_raw = _q(columns["usage"])
    sql = f"""
        SELECT {_q(columns["provider"], "'未标注'")} AS provider,
               COALESCE({_q(columns["committed"])}, 0) AS committed,
               COALESCE({_q(columns["used"])}, 0) AS used,
               {usage_raw if columns["usage"] else "NULL"} AS usage,
               {expiry} AS expiry
        FROM {table}
    """
    raw_rows = await _aggregate(sql, allowed)

    rows: list[dict[str, Any]] = []
    for provider, committed, used, usage, expiry_value in raw_rows:
        committed = _numeric(committed)
        used = _numeric(used)
        ratio = _numeric(usage) if usage is not None else (used / committed if committed else 0.0)
        # 兼容「0.92」与「92」两种使用率写法。
        if ratio > 1.5:
            ratio /= 100
        ratio = max(0.0, min(ratio, 1.0))
        rows.append(
            {
                "provider": str(provider or "未标注"),
                "committed": committed,
                "used": used,
                "ratio": ratio,
                "expiry": _as_date_text(expiry_value),
            }
        )

    rows.sort(key=lambda row: row["ratio"], reverse=True)
    table_rows = [
        [
            row["provider"],
            _wan(row["committed"]),
            _wan(row["used"]),
            f"{row['ratio'] * 100:.1f}%",
            row["expiry"] or "—",
        ]
        for row in rows
    ]
    return {"columns": empty["columns"], "rows": table_rows}, rows


_RETIRED_STATUS = {"legacy", "inactive", "retired", "archived", "停用", "下线", "废弃", "历史"}


def _model_key(provider: Any, model_id: Any) -> tuple[str, str]:
    return (_norm(str(provider or "")), _norm(str(model_id or "")))


async def _build_catalog_summary(
    datasets: list[DatasetMeta],
) -> ReportCatalogOut | None:
    """基于模型清单与价目表生成「当前在售模型价格」概览。

    两份表都通过表头语义识别，换成同义表头的新 Excel 也能继续工作。
    """
    catalog = _pick_dataset(
        datasets,
        CATALOG_COLUMNS,
        required=("provider", "model_id", "display"),
        hints=CATALOG_HINTS,
    )
    prices = _pick_dataset(
        datasets,
        PRICE_COLUMNS,
        required=("provider", "model_id", "input_usd", "output_usd"),
        hints=PRICE_HINTS,
    )
    if catalog is None or prices is None:
        return None

    catalog_table = qualified("ds", catalog.dataset.physical_table)
    catalog_rows = await _aggregate(
        f"""
        SELECT {_q(catalog.columns["provider"])} AS provider,
               {_q(catalog.columns["model_id"])} AS model_id,
               {_q(catalog.columns["display"])} AS display_name,
               {_q(catalog.columns["status"], "''")} AS status
        FROM {catalog_table}
        """,
        {catalog.dataset.full_table},
    )

    active: dict[tuple[str, str], tuple[str, str]] = {}
    for provider, model_id, display, status in catalog_rows:
        if not provider or not model_id:
            continue
        if str(status or "").strip().lower() in _RETIRED_STATUS:
            continue
        key = _model_key(provider, model_id)
        if not key[0] or not key[1]:
            continue
        active[key] = (str(provider).strip(), str(display or model_id).strip())

    if not active:
        return None

    price_table = qualified("ds", prices.dataset.physical_table)
    conditions = []
    if prices.columns["price_type"]:
        conditions.append(f"{_q(prices.columns['price_type'])} IS DISTINCT FROM '历史价'")
    effective_end = prices.columns["effective_end"]
    if effective_end and effective_end.kind == "date":
        conditions.append(
            f"({_q(effective_end)} IS NULL OR {_q(effective_end)} >= CURRENT_DATE)"
        )
    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    price_rows = await _aggregate(
        f"""
        SELECT {_q(prices.columns["provider"])} AS provider,
               {_q(prices.columns["model_id"])} AS model_id,
               {_q(prices.columns["input_usd"])} AS input_usd,
               {_q(prices.columns["output_usd"])} AS output_usd
        FROM {price_table}
        {where_sql}
        """,
        {prices.dataset.full_table},
    )

    # 同一模型可能有多档定价（批量 / 错峰 / 上下文区间），取总价最低的一档。
    best: dict[tuple[str, str], tuple[float, float]] = {}
    for provider, model_id, input_usd, output_usd in price_rows:
        key = _model_key(provider, model_id)
        if key not in active:
            continue
        if input_usd is None and output_usd is None:
            continue
        input_value = _numeric(input_usd)
        output_value = _numeric(output_usd)
        current = best.get(key)
        if current is None or (input_value + output_value, output_value) < (
            current[0] + current[1],
            current[1],
        ):
            best[key] = (input_value, output_value)

    if not best:
        return None

    ranked = sorted(
        best.items(),
        key=lambda item: (item[1][1], item[1][0], active[item[0]][0]),
        reverse=True,
    )
    table_rows = [
        [
            active[key][0],
            active[key][1],
            round(values[0], 4),
            round(values[1], 4),
        ]
        for key, values in ranked[:12]
    ]

    provider_count = len({key[0] for key in best})
    paid_inputs = [values[0] for values in best.values() if values[0] > 0]
    min_input = min(paid_inputs) if paid_inputs else 0.0
    max_output = max(values[1] for values in best.values())
    summary = (
        f"当前在售 {len(best)} 个模型、覆盖 {provider_count} 家供应商；"
        f"下表按输出价从高到低展示前 {len(table_rows)} 个，"
        f"最低付费输入价 ${min_input:g}/百万 token，最高输出价 ${max_output:g}/百万 token。"
    )

    return ReportCatalogOut(
        total_models=len(best),
        provider_count=provider_count,
        summary=summary,
        table=TableOut(
            columns=["供应商", "模型", "输入价(USD/百万)", "输出价(USD/百万)"],
            rows=table_rows,
        ),
    )
