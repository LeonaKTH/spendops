"""生成 ProcureBI 演示用的模拟采购数据。

固定随机种子，结果可复现。输出：
  sample_data/bills_2025.xlsx          2025 年历史账单（多 Sheet）
  sample_data/bills_2026.xlsx          2026 年当前模型账单（多 Sheet）
  sample_data/quotes.xlsx              供应商报价单
  sample_data/quotas.xlsx              2025 合同配额与用量
  sample_data/quotas_2026.xlsx         2026 合同配额与用量
  sample_data/bills_dirty_sample.xlsx  带格式问题的脏数据样本
  sample_data/summary.json             元信息与演示故事点
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "sample_data"
SEED = 20251019

random.seed(SEED)
RNG_2026 = random.Random(20260201)

PROVIDERS = ["DeepSeek", "阿里云百炼", "火山引擎", "OpenAI", "Anthropic"]
# (供应商, 模型, 输入单价 元/千token, 输出单价 元/千token)
MODELS = [
    ("DeepSeek", "deepseek-chat", 2.0, 8.0),
    ("DeepSeek", "deepseek-reasoner", 4.0, 16.0),
    ("阿里云百炼", "qwen-plus", 0.8, 2.0),
    ("阿里云百炼", "qwen-max", 2.4, 9.6),
    ("火山引擎", "doubao-pro-32k", 0.8, 2.0),
    ("火山引擎", "doubao-lite-32k", 0.3, 0.6),
    ("OpenAI", "gpt-4o-mini", 1.1, 4.4),
    ("Anthropic", "claude-sonnet", 21.0, 105.0),
]
APPS = ["智能客服", "代码助手", "文档摘要"]
BUSINESS_LINES = ["ToC", "ToB", "内部工具"]
APP_FACTOR = {"智能客服": 1.5, "代码助手": 0.8, "文档摘要": 0.6}
BIZ_FACTOR = {"ToC": 1.2, "ToB": 1.0, "内部工具": 0.5}

START = date(2025, 1, 1)
END = date(2025, 12, 31)

# 2026 年当前主流模型（人民币元 / 千 token，按 1 USD = 7.2 CNY 折算）
# (供应商, 模型, 输入单价, 输出单价, 走量系数)
PROVIDERS_2026 = [
    "OpenAI",
    "Anthropic",
    "Google",
    "阿里云",
    "火山引擎",
    "DeepSeek",
    "智谱",
    "Kimi",
    "MiniMax",
    "xAI",
]
MODELS_2026 = [
    ("OpenAI", "gpt-6-astra", 0.072, 0.360, 0.9),
    ("OpenAI", "gpt-6.1-sol", 0.0144, 0.072, 1.3),
    ("OpenAI", "gpt-6-luna", 0.00072, 0.0036, 1.8),
    ("Anthropic", "claude-fable-5-1", 0.072, 0.360, 0.9),
    ("Anthropic", "claude-opus-5-5", 0.0288, 0.144, 1.1),
    ("Anthropic", "claude-sonnet-5-5", 0.0144, 0.072, 1.3),
    ("Google", "gemini-4-argon", 0.0288, 0.144, 1.0),
    ("Google", "gemini-3.8-flash", 0.0108, 0.054, 1.4),
    ("阿里云", "qwen3.8-max", 0.0144, 0.0432, 1.2),
    ("阿里云", "qwen3.7-plus", 0.00288, 0.01152, 1.7),
    ("火山引擎", "doubao-seed-2.1-pro", 0.006, 0.030, 1.5),
    ("DeepSeek", "deepseek-v4-pro", 0.006, 0.018, 1.6),
    ("智谱", "glm-5.3", 0.008, 0.028, 1.4),
    ("Kimi", "kimi-k3", 0.020, 0.100, 1.0),
    ("MiniMax", "minimax-m3", 0.0021, 0.0084, 1.7),
    ("xAI", "grok-4.7", 0.0144, 0.0432, 1.1),
]

START_2026 = date(2026, 1, 1)
END_2026 = date(2026, 9, 30)


def daterange(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def is_spike_day(day: date, app: str, model: str, biz: str) -> bool:
    return (
        date(2025, 6, 10) <= day <= date(2025, 6, 25)
        and app == "智能客服"
        and model == "doubao-pro-32k"
        and biz == "ToC"
    )


def build_bills() -> pd.DataFrame:
    rows: list[dict] = []
    for day in daterange(START, END):
        weekday_factor = 0.62 if day.weekday() >= 5 else 1.0
        month_growth = 1.0 + (day.month - 1) * 0.035
        for provider, model, in_price, out_price in MODELS:
            provider_factor = 1.35 if provider == "DeepSeek" else 1.0
            price_noise = random.uniform(0.96, 1.04)
            for app in APPS:
                for biz in BUSINESS_LINES:
                    input_tokens = int(
                        random.uniform(180_000, 1_600_000)
                        * weekday_factor
                        * month_growth
                        * APP_FACTOR[app]
                        * BIZ_FACTOR[biz]
                        * provider_factor
                        * random.uniform(0.85, 1.15)
                    )
                    output_tokens = int(input_tokens * random.uniform(0.18, 0.45))

                    if is_spike_day(day, app, model, biz):
                        input_tokens = int(input_tokens * 2.8)
                        output_tokens = int(output_tokens * 2.8)

                    row_in_price = round(in_price * price_noise, 4)
                    row_out_price = round(out_price * price_noise, 4)

                    # 异常单价：用于演示异常检测
                    if (
                        day == date(2025, 9, 15)
                        and provider == "Anthropic"
                        and app == "智能客服"
                        and biz == "ToB"
                    ):
                        row_in_price = round(row_in_price * 10, 4)
                        row_out_price = round(row_out_price * 10, 4)

                    amount = round(
                        input_tokens / 1000 * row_in_price
                        + output_tokens / 1000 * row_out_price,
                        2,
                    )
                    rows.append(
                        {
                            "账期": day.isoformat(),
                            "供应商": provider,
                            "模型": model,
                            "应用": app,
                            "业务线": biz,
                            "输入token": input_tokens,
                            "输出token": output_tokens,
                            "输入单价(元/千token)": row_in_price,
                            "输出单价(元/千token)": row_out_price,
                            "金额(元)": amount,
                            "币种": "CNY",
                        }
                    )
    return pd.DataFrame(rows)


def build_quotes() -> pd.DataFrame:
    rows = []
    for idx, (provider, model, in_price, out_price) in enumerate(MODELS, start=1):
        rows.append(
            {
                "供应商": provider,
                "模型": model,
                "输入单价(元/千token)": in_price,
                "输出单价(元/千token)": out_price,
                "承诺量(万元)": random.choice([50, 80, 100, 150]),
                "阶梯折扣": random.choice(["无", "满50万 95折", "满100万 9折"]),
                "有效期": "2026-12-31",
                "备注": "性价比推荐" if (in_price, out_price) in {(0.8, 2.0), (0.3, 0.6)} else "",
            }
        )
    return pd.DataFrame(rows)


def build_quotas(bills: pd.DataFrame) -> pd.DataFrame:
    usage = bills.groupby("供应商", as_index=False)["金额(元)"].sum()
    target_ratio = {
        "DeepSeek": 0.78,
        "阿里云百炼": 0.60,
        "火山引擎": 0.92,
        "OpenAI": 0.45,
        "Anthropic": 0.30,
    }
    rows = []
    for idx, item in enumerate(usage.itertuples(index=False), start=1):
        used = float(item[1])
        ratio = target_ratio.get(item[0], 0.5)
        committed = round(used / ratio, -4)
        rows.append(
            {
                "合同编号": f"HT-2025-{idx:03d}",
                "供应商": item[0],
                "承诺金额(元)": committed,
                "已用金额(元)": round(used, 2),
                "使用率": round(used / committed, 4) if committed else 0,
                "到期日": f"2026-{(idx * 2) % 12 + 1:02d}-28",
            }
        )
    return pd.DataFrame(rows)


def build_dirty_sample(bills: pd.DataFrame) -> pd.DataFrame:
    sample = bills.sample(n=60, random_state=SEED).copy().astype(object)
    for idx, row in sample.iterrows():
        if idx % 4 == 0:
            sample.at[idx, "账期"] = row["账期"].replace("-", "/")
        elif idx % 4 == 1:
            sample.at[idx, "账期"] = row["账期"].replace("-", "")
        if idx % 5 == 0:
            sample.at[idx, "输入token"] = f"{int(row['输入token']):,}"
        if idx % 6 == 0:
            sample.at[idx, "金额(元)"] = f"¥{row['金额(元)']:,.2f}"
        if idx % 7 == 0:
            sample.at[idx, "输出token"] = ""
        if idx % 9 == 0:
            sample.at[idx, "供应商"] = f" {row['供应商']} "
    return sample


def is_spike_day_2026(day: date, app: str, model: str, biz: str) -> bool:
    return (
        date(2026, 6, 8) <= day <= date(2026, 6, 20)
        and app == "代码助手"
        and model == "gpt-6-astra"
        and biz == "内部工具"
    )


def build_bills_2026() -> pd.DataFrame:
    rows: list[dict] = []
    for day in daterange(START_2026, END_2026):
        weekday_factor = 0.62 if day.weekday() >= 5 else 1.0
        month_growth = 1.0 + (day.month - 1) * 0.04
        for provider, model, in_price, out_price, volume in MODELS_2026:
            price_noise = RNG_2026.uniform(0.97, 1.03)
            for app in APPS:
                for biz in BUSINESS_LINES:
                    input_tokens = int(
                        RNG_2026.uniform(1_200_000, 7_000_000)
                        * weekday_factor
                        * month_growth
                        * APP_FACTOR[app]
                        * BIZ_FACTOR[biz]
                        * volume
                        * RNG_2026.uniform(0.85, 1.15)
                    )
                    output_tokens = int(input_tokens * RNG_2026.uniform(0.20, 0.50))

                    if is_spike_day_2026(day, app, model, biz):
                        input_tokens = int(input_tokens * 2.6)
                        output_tokens = int(output_tokens * 2.6)

                    row_in_price = round(in_price * price_noise, 6)
                    row_out_price = round(out_price * price_noise, 6)
                    amount = round(
                        input_tokens / 1000 * row_in_price
                        + output_tokens / 1000 * row_out_price,
                        2,
                    )
                    rows.append(
                        {
                            "账期": day.isoformat(),
                            "供应商": provider,
                            "模型": model,
                            "应用": app,
                            "业务线": biz,
                            "输入token": input_tokens,
                            "输出token": output_tokens,
                            "输入单价(元/千token)": row_in_price,
                            "输出单价(元/千token)": row_out_price,
                            "金额(元)": amount,
                            "币种": "CNY",
                        }
                    )
    return pd.DataFrame(rows)


def build_quotas_2026(bills: pd.DataFrame) -> pd.DataFrame:
    usage = bills.groupby("供应商", as_index=False)["金额(元)"].sum()
    target_ratio = {
        "OpenAI": 0.72,
        "Anthropic": 0.88,
        "Google": 0.55,
        "阿里云": 0.64,
        "火山引擎": 0.91,
        "DeepSeek": 0.47,
        "智谱": 0.38,
        "Kimi": 0.83,
        "MiniMax": 0.42,
        "xAI": 0.58,
    }
    rows = []
    for idx, item in enumerate(usage.itertuples(index=False), start=1):
        used = float(item[1])
        ratio = target_ratio.get(item[0], 0.5)
        committed = round(used / ratio, -4)
        rows.append(
            {
                "合同编号": f"HT-2026-{idx:03d}",
                "供应商": item[0],
                "承诺金额(元)": committed,
                "已用金额(元)": round(used, 2),
                "使用率": round(used / committed, 4) if committed else 0,
                "到期日": f"2027-{(idx * 2) % 12 + 1:02d}-28",
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    bills = build_bills()
    bills_2026 = build_bills_2026()
    quotes = build_quotes()
    quotas = build_quotas(bills)
    quotas_2026 = build_quotas_2026(bills_2026)
    dirty = build_dirty_sample(bills)

    supplier_summary = (
        bills.groupby("供应商", as_index=False)
        .agg(
            输入token=("输入token", "sum"),
            输出token=("输出token", "sum"),
            金额=("金额(元)", "sum"),
        )
        .sort_values("金额", ascending=False)
    )
    supplier_summary["金额"] = supplier_summary["金额"].round(2)

    bills_path = OUT / "bills_2025.xlsx"
    with pd.ExcelWriter(bills_path, engine="openpyxl") as writer:
        bills.to_excel(writer, sheet_name="账单明细", index=False)
        supplier_summary.to_excel(writer, sheet_name="供应商汇总", index=False)

    supplier_summary_2026 = (
        bills_2026.groupby("供应商", as_index=False)
        .agg(
            输入token=("输入token", "sum"),
            输出token=("输出token", "sum"),
            金额=("金额(元)", "sum"),
        )
        .sort_values("金额", ascending=False)
    )
    supplier_summary_2026["金额"] = supplier_summary_2026["金额"].round(2)

    with pd.ExcelWriter(OUT / "bills_2026.xlsx", engine="openpyxl") as writer:
        bills_2026.to_excel(writer, sheet_name="账单明细", index=False)
        supplier_summary_2026.to_excel(writer, sheet_name="供应商汇总", index=False)

    quotes.to_excel(OUT / "quotes.xlsx", index=False)
    quotas.to_excel(OUT / "quotas.xlsx", index=False)
    quotas_2026.to_excel(OUT / "quotas_2026.xlsx", index=False)
    dirty.to_excel(OUT / "bills_dirty_sample.xlsx", index=False)

    summary = {
        "seed": SEED,
        "period": f"{START.isoformat()} ~ {END.isoformat()}",
        "row_count": len(bills),
        "total_amount": round(float(bills["金额(元)"].sum()), 2),
        "providers": PROVIDERS,
        "models": [model for _, model, _, _ in MODELS],
        "story_points": [
            "2025-06-10 ~ 2025-06-25：智能客服 × doubao-pro-32k 成本突增，用于归因演示",
            "2025-09-15：Anthropic claude-sonnet 出现异常单价，用于异常检测演示",
            "火山引擎配额使用率约 92%，用于配额预警演示",
            "doubao-lite-32k / qwen-plus 单价更低，用于模型替换与比价演示",
        ],
        "bills_2026": {
            "period": f"{START_2026.isoformat()} ~ {END_2026.isoformat()}",
            "row_count": len(bills_2026),
            "total_amount": round(float(bills_2026["金额(元)"].sum()), 2),
            "providers": PROVIDERS_2026,
            "models": [model for _, model, _, _, _ in MODELS_2026],
            "story_points": [
                "当前主流模型：GPT-6 Astra、Claude Fable 5.1 / Opus 5.5、Gemini 4 Argon、Kimi K3",
                "2026-06-08 ~ 2026-06-20：代码助手 × GPT-6 Astra 用量突增，用于归因演示",
                "火山引擎与 Anthropic 配额使用率超过 85%，用于配额预警演示",
            ],
        },
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Generated {len(bills):,} bill rows for 2025")
    print(f"Total amount: {summary['total_amount']:,.2f} CNY")
    print(f"Generated {len(bills_2026):,} bill rows for 2026")
    print(f"2026 total amount: {summary['bills_2026']['total_amount']:,.2f} CNY")
    print(f"Output directory: {OUT}")


if __name__ == "__main__":
    main()
