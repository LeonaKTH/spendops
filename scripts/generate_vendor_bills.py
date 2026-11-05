"""生成「真实样式」的大模型供应商月度账单，用于上传测试。

说明：真实供应商账单属于客户私有数据，网上没有可直接下载的完整样例。
这里按照 OpenAI / Anthropic / Azure OpenAI / 阿里云百炼 / DeepSeek 公开的
用量导出与发票字段格式，构造金额、token 自洽的模拟账单（2026 年 9 月）。

输出目录 sample_data/vendor_bills/：
  openai_usage_2026-09.csv            OpenAI 用量导出风格（USD）
  anthropic_usage_2026-09.csv         Anthropic Console 用量风格（USD，含 cache）
  azure_openai_cost_2026-09.csv       Azure Cost Management 导出风格（USD）
  aliyun_bailian_bill_2026-09.csv     阿里云百炼账单明细（CNY）
  deepseek_bill_2026-09.csv           DeepSeek 开放平台账单（CNY）
  llm_consolidated_invoice_2026-09.xlsx  六家供应商合并账单（CNY，适合直接出 BI 报表）

结果可复现，固定随机种子。
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "sample_data" / "vendor_bills"
SEED = 20260930
RNG = random.Random(SEED)
USD_CNY = 7.2

START = date(2026, 9, 1)
DAYS = [START + timedelta(days=offset) for offset in range(30)]

# (模型, 输入 USD/百万 token, 输出 USD/百万 token, 单应用日均输入 token)
OPENAI_MODELS = [
    ("gpt-6-astra", 10.0, 50.0, 6_000_000),
    ("gpt-6.1-sol", 2.0, 10.0, 15_000_000),
    ("gpt-6-luna", 0.1, 0.5, 30_000_000),
]
ANTHROPIC_MODELS = [
    ("claude-fable-5-1", 10.0, 50.0, 5_000_000),
    ("claude-opus-5-5", 4.0, 20.0, 8_000_000),
    ("claude-sonnet-5-5", 2.0, 10.0, 20_000_000),
]
AZURE_MODELS = [
    ("gpt-6-astra", 10.0, 50.0, 4_000_000),
    ("gpt-6.1-sol", 2.0, 10.0, 9_000_000),
]
ALIYUN_MODELS = [
    # (模型, 输入 元/百万, 输出 元/百万, 单应用日均输入 token)
    ("qwen3.8-max", 14.4, 43.2, 20_000_000),
    ("qwen3.7-plus", 2.88, 11.52, 60_000_000),
]
DEEPSEEK_MODELS = [
    ("deepseek-v4-pro", 6.0, 18.0, 80_000_000),
    ("deepseek-chat", 2.0, 8.0, 35_000_000),
]

EN_APPS = ["Customer Support", "Code Assistant", "Doc Summary"]
ZH_APPS = ["智能客服", "代码助手", "文档摘要"]


def jitter(base: int, spread: float = 0.22) -> int:
    return max(0, int(base * (1 + RNG.uniform(-spread, spread))))


def tokens_for(base_input: int) -> tuple[int, int]:
    input_tokens = jitter(base_input)
    output_tokens = jitter(int(input_tokens * RNG.uniform(0.18, 0.38)))
    return input_tokens, output_tokens


def money(value: float) -> float:
    return round(value, 2)


def write_csv(path: Path, header: list[str], rows: list[list[object]], bom: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoding = "utf-8-sig" if bom else "utf-8"
    with path.open("w", newline="", encoding=encoding) as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def openai_invoice() -> None:
    header = [
        "Date",
        "Vendor",
        "Project",
        "Application",
        "Model",
        "Input Tokens",
        "Cached Input Tokens",
        "Output Tokens",
        "Input Cost (USD)",
        "Output Cost (USD)",
        "Amount (USD)",
        "Invoice Number",
        "Billing Period",
    ]
    rows: list[list[object]] = []
    for day in DAYS:
        for app in EN_APPS:
            for model, input_price, output_price, base in OPENAI_MODELS:
                input_tokens, output_tokens = tokens_for(base)
                cached = jitter(int(input_tokens * 0.28)) if model != "gpt-6-luna" else 0
                input_cost = (input_tokens - cached) / 1e6 * input_price + cached / 1e6 * input_price * 0.25
                output_cost = output_tokens / 1e6 * output_price
                rows.append(
                    [
                        day.isoformat(),
                        "OpenAI",
                        f"proj-{app.lower().replace(' ', '-')}",
                        app,
                        model,
                        input_tokens,
                        cached,
                        output_tokens,
                        money(input_cost),
                        money(output_cost),
                        money(input_cost + output_cost),
                        "INV-2026-09-4821",
                        "2026-09-01 ~ 2026-09-30",
                    ]
                )
    write_csv(OUT / "openai_usage_2026-09.csv", header, rows)


def anthropic_invoice() -> None:
    header = [
        "Date",
        "Vendor",
        "Workspace",
        "Application",
        "Model",
        "Input Tokens",
        "Cache Creation Input Tokens",
        "Cache Read Input Tokens",
        "Output Tokens",
        "Input Cost (USD)",
        "Output Cost (USD)",
        "Amount (USD)",
        "Invoice Number",
    ]
    rows: list[list[object]] = []
    for day in DAYS:
        for app in EN_APPS:
            for model, input_price, output_price, base in ANTHROPIC_MODELS:
                input_tokens, output_tokens = tokens_for(base)
                cache_read = jitter(int(input_tokens * 0.35))
                cache_write = jitter(int(input_tokens * 0.08))
                uncached = max(0, input_tokens - cache_read - cache_write)
                input_cost = (
                    uncached / 1e6 * input_price
                    + cache_write / 1e6 * input_price * 1.25
                    + cache_read / 1e6 * input_price * 0.1
                )
                output_cost = output_tokens / 1e6 * output_price
                rows.append(
                    [
                        day.isoformat(),
                        "Anthropic",
                        "workspace-prod",
                        app,
                        model,
                        input_tokens,
                        cache_write,
                        cache_read,
                        output_tokens,
                        money(input_cost),
                        money(output_cost),
                        money(input_cost + output_cost),
                        "INV-ANTH-2026-09-0917",
                    ]
                )
    write_csv(OUT / "anthropic_usage_2026-09.csv", header, rows)


def azure_invoice() -> None:
    header = [
        "Date",
        "Vendor",
        "Subscription",
        "Resource Group",
        "Application",
        "Model",
        "Quantity (1K Tokens)",
        "Unit Price (USD)",
        "Cost In Billing Currency",
        "Billing Currency",
        "Invoice Number",
    ]
    rows: list[list[object]] = []
    for day in DAYS:
        for app in EN_APPS[:2]:
            for model, input_price, _output_price, base in AZURE_MODELS:
                input_tokens, _ = tokens_for(base)
                quantity = round(input_tokens / 1000, 3)
                unit_price = round(input_price / 1000, 6)
                rows.append(
                    [
                        day.isoformat(),
                        "Azure OpenAI",
                        "sub-prod-ai-01",
                        "rg-llm-prod",
                        app,
                        model,
                        quantity,
                        unit_price,
                        money(quantity * unit_price),
                        "USD",
                        "AZ-2026-09-77310",
                    ]
                )
    write_csv(OUT / "azure_openai_cost_2026-09.csv", header, rows)


def aliyun_invoice() -> None:
    header = [
        "账期",
        "供应商",
        "产品",
        "模型",
        "应用",
        "输入Token",
        "输出Token",
        "输入单价(元/千Token)",
        "输出单价(元/千Token)",
        "应付金额(元)",
        "币种",
        "账单编号",
    ]
    rows: list[list[object]] = []
    for day in DAYS:
        for app in ZH_APPS:
            for model, input_price, output_price, base in ALIYUN_MODELS:
                input_tokens, output_tokens = tokens_for(base)
                amount = (
                    input_tokens / 1e6 * input_price
                    + output_tokens / 1e6 * output_price
                )
                rows.append(
                    [
                        day.isoformat(),
                        "阿里云百炼",
                        "大模型服务平台百炼",
                        model,
                        app,
                        input_tokens,
                        output_tokens,
                        input_price / 1000,
                        output_price / 1000,
                        money(amount),
                        "CNY",
                        "BIL-ALI-202609-55120",
                    ]
                )
    write_csv(OUT / "aliyun_bailian_bill_2026-09.csv", header, rows, bom=True)


def deepseek_invoice() -> None:
    header = [
        "账期",
        "供应商",
        "模型",
        "应用",
        "输入Token",
        "输出Token",
        "输入单价(元/千Token)",
        "输出单价(元/千Token)",
        "金额(元)",
        "币种",
        "账单编号",
    ]
    rows: list[list[object]] = []
    for day in DAYS:
        for app in ZH_APPS:
            for model, input_price, output_price, base in DEEPSEEK_MODELS:
                input_tokens, output_tokens = tokens_for(base)
                amount = (
                    input_tokens / 1e6 * input_price
                    + output_tokens / 1e6 * output_price
                )
                rows.append(
                    [
                        day.isoformat(),
                        "DeepSeek",
                        model,
                        app,
                        input_tokens,
                        output_tokens,
                        input_price / 1000,
                        output_price / 1000,
                        money(amount),
                        "CNY",
                        "DS-202609-880126",
                    ]
                )
    write_csv(OUT / "deepseek_bill_2026-09.csv", header, rows, bom=True)


def consolidated_invoice() -> None:
    rows: list[dict[str, object]] = []

    def add(
        day: date,
        provider: str,
        model: str,
        app: str,
        input_price_cny_m: float,
        output_price_cny_m: float,
        input_tokens: int,
        output_tokens: int,
        business_line: str,
    ) -> None:
        amount = (
            input_tokens / 1e6 * input_price_cny_m
            + output_tokens / 1e6 * output_price_cny_m
        )
        rows.append(
            {
                "账期": day.isoformat(),
                "供应商": provider,
                "模型": model,
                "应用": app,
                "业务线": business_line,
                "输入Token": input_tokens,
                "输出Token": output_tokens,
                "金额(元)": money(amount),
                "币种": "CNY",
            }
        )

    for day in DAYS:
        for app, business in zip(EN_APPS, ["ToC", "ToB", "内部工具"]):
            for model, input_price, output_price, base in OPENAI_MODELS:
                input_tokens, output_tokens = tokens_for(base)
                add(day, "OpenAI", model, app, input_price * USD_CNY, output_price * USD_CNY,
                    input_tokens, output_tokens, business)
            for model, input_price, output_price, base in ANTHROPIC_MODELS:
                input_tokens, output_tokens = tokens_for(base)
                add(day, "Anthropic", model, app, input_price * USD_CNY, output_price * USD_CNY,
                    input_tokens, output_tokens, business)
            for model, input_price, output_price, base in ALIYUN_MODELS:
                input_tokens, output_tokens = tokens_for(base)
                add(day, "阿里云百炼", model, app, input_price, output_price,
                    input_tokens, output_tokens, business)
            for model, input_price, output_price, base in DEEPSEEK_MODELS:
                input_tokens, output_tokens = tokens_for(base)
                add(day, "DeepSeek", model, app, input_price, output_price,
                    input_tokens, output_tokens, business)

    frame = pd.DataFrame(rows)
    frame.to_excel(OUT / "llm_consolidated_invoice_2026-09.xlsx", index=False)


def csv_to_excel() -> None:
    """为 CSV 账单额外生成一份 Excel 版本，方便直接在 Excel / WPS 中查看。"""
    for csv_path in sorted(OUT.glob("*_2026-09.csv")):
        frame = pd.read_csv(csv_path)
        frame.to_excel(csv_path.with_suffix(".xlsx"), index=False, sheet_name="账单明细")


def main() -> None:
    openai_invoice()
    anthropic_invoice()
    azure_invoice()
    aliyun_invoice()
    deepseek_invoice()
    consolidated_invoice()
    csv_to_excel()
    for path in sorted(OUT.iterdir()):
        print(f"{path.name:44s} {path.stat().st_size / 1024:8.1f} KB")


if __name__ == "__main__":
    main()
