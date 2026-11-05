"""生成大模型价格/套餐/限流采购底表（Excel）。

数据口径：
- Token 价格统一折算为「每 1,000,000 tokens」，保留各厂商原币种。
- 人民币按 1 USD = 7.2 CNY 折算，仅用于横向比较，实际结算以合同/账单为准。
- 核实日期 2026-10-20；核实状态见每行「核实状态」列。

运行：
    backend/.venv/Scripts/python.exe scripts/build_model_pricing.py
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "sample_data"
VERIFIED_AT = "2026-10-20"
FX_CNY_PER_USD = 7.2
DEMO_INPUT_MTOK = 1.0
DEMO_OUTPUT_MTOK = 0.2

URL = {
    "Anthropic": "https://www.anthropic.com/pricing",
    "OpenAI": "https://openai.com/api/pricing/",
    "Google": "https://ai.google.dev/gemini-api/docs/pricing",
    "DeepSeek": "https://api-docs.deepseek.com/quick_start/pricing",
    "智谱": "https://docs.bigmodel.cn/cn/guide/models/model-pricing",
    "Kimi": "https://platform.moonshot.cn/docs/pricing/chat",
    "MiniMax": "https://platform.minimax.io/docs/guides/pricing",
    "阿里云": "https://help.aliyun.com/zh/model-studio/models",
    "火山引擎": "https://docs.volcengine.com/docs/ark/model-pricing",
    "xAI": "https://docs.x.ai/docs/models",
}

HEADERS = {
    "catalog": [
        "供应商",
        "系列",
        "模型标识",
        "显示名称",
        "版本快照",
        "状态",
        "上下文窗口Token",
        "最大输出Token",
        "模态",
        "计费方式",
        "服务区域",
        "官方页面",
        "核实日期",
        "核实状态",
    ],
    "price": [
        "供应商",
        "模型标识",
        "服务区域",
        "计费方式",
        "价格类型",
        "币种",
        "计价单位",
        "输入价格",
        "输出价格",
        "缓存命中价格",
        "缓存写入价格",
        "批量输入价格",
        "批量输出价格",
        "上下文区间",
        "时段",
        "生效开始",
        "生效结束",
        "示例成本_原币",
        "示例成本_USD",
        "折算输入价_USD",
        "折算输出价_USD",
        "官方页面",
        "核实日期",
        "核实状态",
        "备注",
    ],
    "plan": [
        "供应商",
        "产品",
        "套餐",
        "计费周期",
        "价格",
        "币种",
        "折合月价_原币",
        "折算月价_USD",
        "席位或账号",
        "包含额度",
        "主要权益",
        "适用对象",
        "价格变更",
        "官方页面",
        "核实日期",
        "核实状态",
        "备注",
    ],
    "limit": [
        "供应商",
        "模型或模型族",
        "账户等级",
        "RPM",
        "输入TPM",
        "输出TPM",
        "并发数",
        "月消费上限_USD",
        "10分钟消费上限_USD",
        "日限额",
        "说明",
        "官方页面",
        "核实日期",
        "核实状态",
    ],
}


def catalog(
    provider: str,
    family: str,
    key: str,
    name: str,
    version: str,
    status: str,
    ctx: int | None,
    out: int | None,
    modality: str,
    region: str,
    verify: str,
) -> list:
    return [
        provider,
        family,
        key,
        name,
        version,
        status,
        ctx,
        out,
        modality,
        "按量计费",
        region,
        URL[provider],
        VERIFIED_AT,
        verify,
    ]


def price(
    provider: str,
    key: str,
    *,
    region: str = "全球",
    mode: str = "按量计费",
    kind: str = "目录价",
    currency: str = "USD",
    inp: float,
    out: float,
    cache_read: float | None = None,
    cache_write: float | None = None,
    batch_in: float | None = None,
    batch_out: float | None = None,
    window: str = "标准",
    period: str = "标准",
    start: str = VERIFIED_AT,
    end: str = "",
    verify: str = "官方页面",
    note: str = "",
) -> list:
    rate = FX_CNY_PER_USD if currency == "CNY" else 1.0
    example_native = inp * DEMO_INPUT_MTOK + out * DEMO_OUTPUT_MTOK
    return [
        provider,
        key,
        region,
        mode,
        kind,
        currency,
        "每百万Token",
        inp,
        out,
        cache_read,
        cache_write,
        batch_in,
        batch_out,
        window,
        period,
        start,
        end,
        round(example_native, 4),
        round(example_native / rate, 4),
        round(inp / rate, 4),
        round(out / rate, 4),
        URL[provider],
        VERIFIED_AT,
        verify,
        note,
    ]


CATALOG = [
    # Anthropic
    catalog("Anthropic", "Fable", "claude-fable-5-1", "Claude Fable 5.1", "5.1", "active", 1_000_000, 128_000, "文本+图像", "全球", "官方页面"),
    catalog("Anthropic", "Fable", "claude-fable-5", "Claude Fable 5", "5", "active", 1_000_000, 128_000, "文本+图像", "全球", "官方页面"),
    catalog("Anthropic", "Opus", "claude-opus-5-5", "Claude Opus 5.5", "5.5", "active", 1_000_000, 128_000, "文本+图像", "全球", "官方页面"),
    catalog("Anthropic", "Opus", "claude-opus-5", "Claude Opus 5", "5", "active", 1_000_000, 128_000, "文本+图像", "全球", "官方页面"),
    catalog("Anthropic", "Sonnet", "claude-sonnet-5-5", "Claude Sonnet 5.5", "5.5", "active", 1_000_000, 128_000, "文本+图像", "全球", "官方页面"),
    catalog("Anthropic", "Sonnet", "claude-sonnet-5", "Claude Sonnet 5", "5", "active", 1_000_000, 128_000, "文本+图像", "全球", "官方页面"),
    catalog("Anthropic", "Sonnet", "claude-sonnet-4-6", "Claude Sonnet 4.6", "4.6", "active", 1_000_000, 128_000, "文本+图像", "全球", "搜索摘要"),
    catalog("Anthropic", "Haiku", "claude-haiku-5-5", "Claude Haiku 5.5", "5.5", "active", 1_000_000, 128_000, "文本+图像", "全球", "官方页面"),
    catalog("Anthropic", "Haiku", "claude-haiku-4-5", "Claude Haiku 4.5", "4.5", "legacy", 200_000, 64_000, "文本+图像", "全球", "搜索摘要"),
    catalog("Anthropic", "Mythos", "claude-mythos-5", "Claude Mythos 5", "5", "active", 1_000_000, 128_000, "文本+图像", "全球", "搜索摘要"),
    catalog("Anthropic", "Opus", "claude-3-opus", "Claude 3 Opus", "3", "legacy", 200_000, 4_096, "文本+图像", "全球", "搜索摘要"),
    # OpenAI
    catalog("OpenAI", "GPT-6", "gpt-6-astra", "GPT-6 Astra", "6", "active", 1_050_000, 128_000, "文本+图像+音频", "全球", "搜索摘要"),
    catalog("OpenAI", "GPT-6", "gpt-6.1-sol", "GPT-6.1 Sol", "6.1", "active", None, None, "文本+图像", "全球", "搜索摘要"),
    catalog("OpenAI", "GPT-6", "gpt-6-luna", "GPT-6 Luna", "6", "active", None, None, "文本+图像", "全球", "搜索摘要"),
    catalog("OpenAI", "GPT-5", "gpt-5.6-sol", "GPT-5.6 Sol", "5.6", "active", None, None, "文本+图像", "全球", "搜索摘要"),
    # Google
    catalog("Google", "Gemini 4", "gemini-4-argon", "Gemini 4 Argon", "4", "active", 1_048_576, 65_536, "文本+图像+音频+视频", "全球", "官方页面+搜索"),
    catalog("Google", "Gemini 3", "gemini-3.1-pro", "Gemini 3.1 Pro", "3.1", "active", None, None, "文本+图像+音频+视频", "全球", "官方页面"),
    catalog("Google", "Gemini 3", "gemini-3.8-flash", "Gemini 3.8 Flash", "3.8", "active", None, None, "文本+图像+音频+视频", "全球", "官方页面"),
    catalog("Google", "Gemini 3", "gemini-3.6-flash", "Gemini 3.6 Flash", "3.6", "active", None, None, "文本+图像+音频+视频", "全球", "官方页面"),
    catalog("Google", "Gemini 3", "gemini-3-flash", "Gemini 3 Flash", "3", "active", None, None, "文本+图像+音频+视频", "全球", "官方页面"),
    catalog("Google", "Gemini 3", "gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", "3.5", "active", None, None, "文本+图像+音频+视频", "全球", "官方页面"),
    catalog("Google", "Gemini 2", "gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite", "2.5", "active", None, None, "文本+图像+音频+视频", "全球", "官方页面"),
    # DeepSeek
    catalog("DeepSeek", "V4", "deepseek-v4-pro", "DeepSeek V4 Pro", "V4 Pro", "active", 1_000_000, 384_000, "文本", "中国", "官方页面"),
    catalog("DeepSeek", "Flash", "deepseek-flash", "DeepSeek Flash", "Flash", "active", 1_000_000, 384_000, "文本", "中国", "官方页面"),
    # 智谱
    catalog("智谱", "GLM-5", "glm-5.3", "GLM-5.3", "5.3", "active", 1_000_000, None, "文本", "中国", "官方页面"),
    catalog("智谱", "GLM-5", "glm-5.3-flash", "GLM-5.3-Flash", "5.3", "active", None, None, "文本", "中国", "官方页面"),
    catalog("智谱", "GLM-5", "glm-5.3-flashx", "GLM-5.3-FlashX", "5.3", "active", None, None, "文本", "中国", "官方页面"),
    catalog("智谱", "GLM-5", "glm-5.2", "GLM-5.2", "5.2", "active", None, None, "文本", "中国", "官方页面"),
    catalog("智谱", "GLM-5", "glm-5.1", "GLM-5.1", "5.1", "active", None, None, "文本", "中国", "官方页面"),
    catalog("智谱", "GLM-5", "glm-5-turbo", "GLM-5-Turbo", "5", "active", None, None, "文本", "中国", "官方页面"),
    catalog("智谱", "GLM-5", "glm-5", "GLM-5", "5", "active", None, None, "文本", "中国", "官方页面"),
    catalog("智谱", "GLM-4", "glm-4.7", "GLM-4.7", "4.7", "active", None, None, "文本", "中国", "官方页面"),
    catalog("智谱", "GLM-4", "glm-4.5-air", "GLM-4.5-Air", "4.5", "active", None, None, "文本", "中国", "官方页面"),
    catalog("智谱", "GLM-4", "glm-4.7-flashx", "GLM-4.7-FlashX", "4.7", "active", None, None, "文本", "中国", "官方页面"),
    catalog("智谱", "GLM-4", "glm-4.7-flash", "GLM-4.7-Flash", "4.7", "active", None, None, "文本", "中国", "官方页面"),
    # Kimi
    catalog("Kimi", "K3", "kimi-k3", "Kimi K3", "K3", "active", 1_048_576, None, "文本+图像", "中国", "官方页面"),
    catalog("Kimi", "K2", "kimi-k2.7-code", "Kimi K2.7 Code", "K2.7", "active", 262_144, None, "文本", "中国", "官方页面"),
    catalog("Kimi", "K2", "kimi-k2.7-code-highspeed", "Kimi K2.7 Code 高速版", "K2.7", "active", 262_144, None, "文本", "中国", "官方页面"),
    catalog("Kimi", "K2", "kimi-k2.6", "Kimi K2.6", "K2.6", "active", 262_144, None, "文本", "中国", "官方页面"),
    # MiniMax
    catalog("MiniMax", "M3", "minimax-m3", "MiniMax M3", "M3", "active", None, None, "文本+图像+音频", "全球", "官方页面"),
    catalog("MiniMax", "M3", "minimax-m3.1-flash", "MiniMax M3.1-Flash", "M3.1", "active", None, None, "文本+图像+音频", "全球", "官方页面"),
    # 阿里云 Qwen
    catalog("阿里云", "Qwen Max", "qwen3.8-max", "Qwen3.8-Max", "3.8", "active", 1_000_000, None, "文本+图像", "国际", "官方页面"),
    catalog("阿里云", "Qwen Max", "qwen3.7-max", "Qwen3.7-Max", "3.7", "active", 1_000_000, None, "文本+图像", "国际/中国", "官方页面"),
    catalog("阿里云", "Qwen Plus", "qwen3.7-plus", "Qwen3.7-Plus", "3.7", "active", 1_000_000, None, "文本+图像", "国际/中国", "官方页面"),
    catalog("阿里云", "Qwen Plus", "qwen3.6-plus", "Qwen3.6-Plus", "3.6", "active", 1_000_000, None, "文本+图像", "国际/中国", "官方页面"),
    catalog("阿里云", "Qwen Plus", "qwen-plus", "Qwen-Plus", "通用", "active", None, None, "文本+图像", "国际/中国", "官方页面"),
    # 火山引擎 Doubao
    catalog("火山引擎", "Doubao 2.1", "doubao-seed-2.1-pro", "Doubao-Seed-2.1-Pro", "2.1", "active", 256_000, None, "文本+图像", "中国", "搜索摘要"),
    catalog("火山引擎", "Doubao 2.1", "doubao-seed-2.1-turbo", "Doubao-Seed-2.1-Turbo", "2.1", "active", None, None, "文本+图像", "中国", "搜索摘要"),
    catalog("火山引擎", "Doubao 2.1", "doubao-seed-2.1-lite", "Doubao-Seed-2.1-Lite", "2.1", "active", None, None, "文本+图像", "中国", "搜索摘要"),
    catalog("火山引擎", "Doubao 2.0", "doubao-seed-2.0-pro", "Doubao-Seed-2.0-Pro", "2.0", "active", 256_000, None, "文本+图像", "中国", "搜索摘要"),
    # xAI
    catalog("xAI", "Grok 4", "grok-4.7", "Grok 4.7", "4.7", "active", 500_000, None, "文本+图像", "美国", "搜索摘要"),
    catalog("xAI", "Grok 4", "grok-4.6", "Grok 4.6", "4.6", "active", 500_000, None, "文本+图像", "美国", "搜索摘要"),
    catalog("xAI", "Grok 4", "grok-4.5", "Grok 4.5", "4.5", "active", 500_000, None, "文本+图像", "美国", "搜索摘要"),
    catalog("xAI", "Grok 4", "grok-4.3", "Grok 4.3", "4.3", "active", 1_000_000, None, "文本+图像", "美国", "搜索摘要"),
    catalog("xAI", "Grok 4", "grok-4.20", "Grok 4.20", "4.20", "active", 1_000_000, None, "文本+图像", "美国", "搜索摘要"),
    catalog("xAI", "Grok Build", "grok-build-0.1", "Grok Build 0.1", "0.1", "active", 256_000, None, "文本", "美国", "搜索摘要"),
]

PRICES = [
    # ---------- Anthropic ----------
    price("Anthropic", "claude-fable-5-1", inp=10, out=50, cache_read=0.25, cache_write=12.5, batch_in=5, batch_out=25, note="批量 5 折；缓存写入为 5 分钟 TTL，1 小时 TTL 为 2 倍"),
    price("Anthropic", "claude-opus-5-5", inp=4, out=20, cache_read=0.20, cache_write=5, batch_in=2, batch_out=10, note="批量 5 折；Fast 模式 2 倍价格"),
    price("Anthropic", "claude-sonnet-5-5", inp=2, out=10, cache_read=0.10, cache_write=2.5, batch_in=1, batch_out=5, note="批量 5 折"),
    price("Anthropic", "claude-haiku-5-5", inp=0.10, out=0.50, cache_read=0.01, cache_write=0.125, batch_in=0.05, batch_out=0.25, window="≤100K", note="100K 以内档"),
    price("Anthropic", "claude-haiku-5-5", inp=0.50, out=2.50, cache_read=0.05, cache_write=0.625, batch_in=0.25, batch_out=1.25, window=">100K", note="超过 100K 档"),
    price("Anthropic", "claude-fable-5", inp=10, out=50, cache_read=1, batch_in=5, batch_out=25, note="上一代"),
    price("Anthropic", "claude-opus-5", inp=5, out=25, cache_read=0.5, batch_in=2.5, batch_out=12.5, note="上一代"),
    price("Anthropic", "claude-sonnet-5", inp=2, out=10, cache_read=0.2, batch_in=1, batch_out=5, note="上一代"),
    price("Anthropic", "claude-sonnet-4-6", inp=3, out=15, cache_read=0.3, batch_in=1.5, batch_out=7.5, note="4.6/4.5 同价"),
    price("Anthropic", "claude-haiku-4-5", inp=1, out=5, cache_read=0.1, batch_in=0.5, batch_out=2.5, note="上一代轻量"),
    price("Anthropic", "claude-mythos-5", inp=10, out=50, cache_read=1, batch_in=5, batch_out=25, note="Mythos 线"),
    price("Anthropic", "claude-3-opus", inp=15, out=75, batch_in=7.5, batch_out=37.5, kind="历史价", note="旧版，仅用于历史账单对照"),
    # ---------- OpenAI ----------
    price("OpenAI", "gpt-6-astra", inp=10, out=50, cache_read=1, cache_write=12.5, batch_in=5, batch_out=25, window="≤272K", verify="搜索摘要", note="超过 272K 长上下文 $20/$75；Fast $20/$100；Ultrafast $60/$300（短上下文）；区域/FedRAMP +10%"),
    price("OpenAI", "gpt-6-astra", inp=20, out=75, cache_read=2, batch_in=10, batch_out=37.5, window=">272K", verify="搜索摘要", note="长上下文档"),
    price("OpenAI", "gpt-6.1-sol", inp=2, out=10, cache_read=0.10, cache_write=2.5, batch_in=1, batch_out=5, verify="搜索摘要", note="长上下文 $4/$15，具体阈值以官方为准"),
    price("OpenAI", "gpt-6-luna", inp=0.10, out=0.50, verify="搜索摘要", note="入门低价档"),
    price("OpenAI", "gpt-5.6-sol", inp=4, out=20, batch_in=2, batch_out=10, kind="促销价", end="2026-11-21", verify="搜索摘要", note="促销至 2026-11-21"),
    price("OpenAI", "gpt-5.6-sol", inp=5, out=30, batch_in=2.5, batch_out=15, kind="目录价", start="2026-11-22", verify="搜索摘要", note="促销结束后的列表价"),
    # ---------- Google ----------
    price("Google", "gemini-4-argon", inp=2, out=10, cache_read=0.10, cache_write=0.20, batch_in=1, batch_out=5, kind="促销价", end="2026-11-30", note="无免费额度；批量/ Flex 5 折"),
    price("Google", "gemini-4-argon", inp=4, out=20, cache_read=0.20, cache_write=0.40, batch_in=2, batch_out=10, kind="目录价", start="2026-12-01", note="促销结束后的列表价"),
    price("Google", "gemini-3.1-pro", inp=2, out=12, cache_read=0.20, cache_write=0.40, batch_in=1, batch_out=6, window="≤200K"),
    price("Google", "gemini-3.1-pro", inp=4, out=18, cache_read=0.20, cache_write=0.40, batch_in=2, batch_out=9, window=">200K"),
    price("Google", "gemini-3.8-flash", inp=0.75, out=3.75, cache_read=0.075, cache_write=0.15, batch_in=0.375, batch_out=1.875, kind="促销价", end="2026-12-31"),
    price("Google", "gemini-3.8-flash", inp=1.50, out=7.50, cache_read=0.15, cache_write=0.30, batch_in=0.75, batch_out=3.75, kind="目录价", start="2027-01-01"),
    price("Google", "gemini-3.6-flash", inp=0.75, out=3.75, cache_read=0.075, cache_write=0.15, batch_in=0.375, batch_out=1.875, kind="促销价", end="2026-12-31"),
    price("Google", "gemini-3.6-flash", inp=1.50, out=7.50, cache_read=0.15, cache_write=0.30, batch_in=0.75, batch_out=3.75, kind="目录价", start="2027-01-01"),
    price("Google", "gemini-3-flash", inp=0.50, out=3.00, cache_read=0.05, batch_in=0.25, batch_out=1.50),
    price("Google", "gemini-3.5-flash-lite", inp=0.30, out=2.50, cache_read=0.03, batch_in=0.15, batch_out=1.25),
    price("Google", "gemini-2.5-flash-lite", inp=0.10, out=0.40, cache_read=0.01, batch_in=0.05, batch_out=0.20),
    # ---------- DeepSeek ----------
    price("DeepSeek", "deepseek-flash", currency="CNY", inp=1, out=4, cache_read=0.02, kind="错峰价", period="错峰（非高峰时段）", note="错峰为高峰的 5 折；并发上限 2500"),
    price("DeepSeek", "deepseek-flash", currency="CNY", inp=2, out=8, cache_read=0.04, kind="高峰价", period="高峰（工作日 09-12、14-18）", note="北京时间工作日高峰"),
    price("DeepSeek", "deepseek-v4-pro", currency="CNY", inp=4.5, out=13.5, cache_read=0.15, kind="错峰价", period="错峰（非高峰时段）", note="错峰为高峰的 5 折；并发上限 500"),
    price("DeepSeek", "deepseek-v4-pro", currency="CNY", inp=9, out=27, cache_read=0.30, kind="高峰价", period="高峰（工作日 09-12、14-18）", note="北京时间工作日高峰"),
    # ---------- 智谱 ----------
    price("智谱", "glm-5.3", currency="CNY", inp=8, out=28, cache_read=2, note="1M 上下文"),
    price("智谱", "glm-5.3-flash", currency="CNY", inp=0.8, out=2.8, cache_read=0.23),
    price("智谱", "glm-5.3-flashx", currency="CNY", inp=2, out=7, cache_read=0.57),
    price("智谱", "glm-5.2", currency="CNY", inp=8, out=28, cache_read=2),
    price("智谱", "glm-5.1", currency="CNY", inp=6, out=24, cache_read=1.3, window="≤32K"),
    price("智谱", "glm-5.1", currency="CNY", inp=8, out=28, cache_read=2, window=">32K"),
    price("智谱", "glm-5-turbo", currency="CNY", inp=5, out=22, cache_read=1.2, window="≤32K"),
    price("智谱", "glm-5-turbo", currency="CNY", inp=7, out=26, cache_read=1.8, window=">32K"),
    price("智谱", "glm-5", currency="CNY", inp=4, out=18, cache_read=1, window="≤32K"),
    price("智谱", "glm-5", currency="CNY", inp=6, out=22, cache_read=1.5, window=">32K"),
    price("智谱", "glm-4.7", currency="CNY", inp=2, out=8, cache_read=0.4, window="阶梯1", note="官网按上下文长度分三档"),
    price("智谱", "glm-4.7", currency="CNY", inp=3, out=14, cache_read=0.6, window="阶梯2"),
    price("智谱", "glm-4.7", currency="CNY", inp=4, out=16, cache_read=0.8, window="阶梯3"),
    price("智谱", "glm-4.5-air", currency="CNY", inp=0.8, out=2, cache_read=0.16, window="阶梯1"),
    price("智谱", "glm-4.5-air", currency="CNY", inp=0.8, out=6, cache_read=0.16, window="阶梯2"),
    price("智谱", "glm-4.5-air", currency="CNY", inp=1.2, out=8, cache_read=0.24, window="阶梯3"),
    price("智谱", "glm-4.7-flashx", currency="CNY", inp=0.5, out=3, cache_read=0.1),
    price("智谱", "glm-4.7-flash", currency="CNY", inp=0, out=0, cache_read=0, kind="免费", note="限时免费模型"),
    price("智谱", "glm-5.3", region="国际", inp=1.4, out=4.4, cache_read=0.26, verify="官方页面", note="Z.AI 美元价"),
    price("智谱", "glm-5.2", region="国际", inp=1.4, out=4.4, cache_read=0.26, verify="官方页面", note="Z.AI 美元价"),
    price("智谱", "glm-5", region="国际", inp=1, out=3.2, cache_read=0.2, verify="官方页面", note="Z.AI 美元价"),
    price("智谱", "glm-4.7", region="国际", inp=0.6, out=2.2, cache_read=0.11, verify="官方页面", note="Z.AI 美元价"),
    # ---------- Kimi ----------
    price("Kimi", "kimi-k3", currency="CNY", inp=20, out=100, cache_read=2, cache_write=20, note="缓存写入 5 分钟 ¥20，1 小时 ¥40；1M 上下文"),
    price("Kimi", "kimi-k2.7-code", currency="CNY", inp=6.5, out=27, cache_read=1.3),
    price("Kimi", "kimi-k2.7-code-highspeed", currency="CNY", inp=13, out=54, cache_read=2.6),
    price("Kimi", "kimi-k2.6", currency="CNY", inp=6.5, out=27, cache_read=1.1),
    # ---------- MiniMax ----------
    price("MiniMax", "minimax-m3.1-flash", currency="CNY", inp=1, out=4, cache_read=0.10),
    price("MiniMax", "minimax-m3", currency="CNY", inp=2.10, out=8.40, cache_read=0.42, window="≤512K"),
    price("MiniMax", "minimax-m3", currency="CNY", inp=4.20, out=16.80, cache_read=0.84, window=">512K"),
    # ---------- 阿里云 Qwen（国际站美元） ----------
    price("阿里云", "qwen3.8-max", region="国际", inp=2, out=6, note="上下文缓存享折扣"),
    price("阿里云", "qwen3.7-max", region="国际", inp=2.5, out=7.5),
    price("阿里云", "qwen3.7-plus", region="国际", inp=0.4, out=1.6, window="≤256K", note="限时 8 折"),
    price("阿里云", "qwen3.7-plus", region="国际", inp=1.2, out=4.8, window=">256K", note="限时 8 折"),
    price("阿里云", "qwen3.6-plus", region="国际", inp=0.5, out=3, window="≤256K"),
    price("阿里云", "qwen3.6-plus", region="国际", inp=2, out=6, window=">256K"),
    price("阿里云", "qwen-plus", region="国际", inp=0.115, out=1.147, note="非思考输出 $0.287"),
    # 中国内地 CNY（搜索摘要，按官网人民币价整理）
    price("阿里云", "qwen3.7-max", region="中国内地", currency="CNY", inp=12, out=36, verify="搜索摘要", note="人民币目录价，建议以百炼控制台为准"),
    price("阿里云", "qwen3.6-plus", region="中国内地", currency="CNY", inp=2, out=12, verify="搜索摘要", note="人民币目录价"),
    price("阿里云", "qwen-plus", region="中国内地", currency="CNY", inp=0.8, out=2, verify="搜索摘要", note="人民币目录价"),
    # ---------- 火山引擎 Doubao ----------
    price("火山引擎", "doubao-seed-2.1-pro", currency="CNY", inp=6, out=30, cache_read=1.2, verify="搜索摘要", note="缓存写入约 ¥0.017/百万Token/小时；批量约 5 折"),
    price("火山引擎", "doubao-seed-2.1-turbo", currency="CNY", inp=3, out=15, cache_read=0.6, verify="搜索摘要", note="批量约 5 折"),
    price("火山引擎", "doubao-seed-2.1-lite", currency="CNY", inp=0.8, out=12, verify="搜索摘要", note="约数，需控制台核实"),
    price("火山引擎", "doubao-seed-2.0-pro", currency="CNY", inp=3.2, out=16, window="≤32K", verify="搜索摘要"),
    price("火山引擎", "doubao-seed-2.0-pro", currency="CNY", inp=4.8, out=24, window="32K-128K", verify="搜索摘要"),
    price("火山引擎", "doubao-seed-2.0-pro", currency="CNY", inp=9.6, out=48, window="128K-256K", verify="搜索摘要"),
    # ---------- xAI ----------
    price("xAI", "grok-4.7", inp=2, out=6, cache_read=0.50, verify="搜索摘要", note="美国端点 1.1 倍；Grok 4.7 Fast 2 倍价格"),
    price("xAI", "grok-4.6", inp=2, out=6, cache_read=0.50, verify="搜索摘要"),
    price("xAI", "grok-4.5", inp=2, out=6, cache_read=0.30, verify="搜索摘要"),
    price("xAI", "grok-4.3", inp=1.25, out=2.50, cache_read=0.20, verify="搜索摘要", note="批量 8 折"),
    price("xAI", "grok-4.20", inp=1.25, out=2.50, cache_read=0.20, verify="搜索摘要", note="批量 8 折"),
    price("xAI", "grok-build-0.1", inp=1, out=2, cache_read=0.20, verify="搜索摘要"),
]


def plan(
    provider: str,
    product: str,
    name: str,
    cycle: str,
    amount: float,
    currency: str,
    monthly: float,
    seats: str,
    quota: str,
    benefits: str,
    audience: str,
    change: str = "",
    verify: str = "搜索摘要",
    note: str = "",
) -> list:
    monthly_usd = monthly / FX_CNY_PER_USD if currency == "CNY" else monthly
    return [
        provider,
        product,
        name,
        cycle,
        amount,
        currency,
        round(monthly, 2),
        round(monthly_usd, 2),
        seats,
        quota,
        benefits,
        audience,
        change,
        URL[provider],
        VERIFIED_AT,
        verify,
        note,
    ]


PLANS = [
    # Anthropic（官网）
    plan("Anthropic", "Claude", "Free", "月付", 0, "USD", 0, "1 个账号", "有限额度", "网页/桌面/移动端，基础对话与文件", "个人试用", verify="官方页面"),
    plan("Anthropic", "Claude", "Pro", "月付", 20, "USD", 20, "1 个账号", "较高用量", "Claude Code、Projects、更多模型、Chrome/M365", "个人日常", verify="官方页面"),
    plan("Anthropic", "Claude", "Pro", "年付", 200, "USD", 16.67, "1 个账号", "较高用量", "年付一次性支付 $200，折合 $16.67/月", "个人日常", verify="官方页面"),
    plan("Anthropic", "Claude", "Max 5x", "月付", 100, "USD", 100, "1 个账号", "Pro 的 5 倍用量", "更高输出上限、优先访问、$100/月 API 额度", "重度个人", verify="官方页面"),
    plan("Anthropic", "Claude", "Max 20x", "月付", 200, "USD", 200, "1 个账号", "Pro 的 20 倍用量", "更高输出上限、优先访问、$200/月 API 额度", "重度个人/小团队", verify="官方页面"),
    plan("Anthropic", "Claude", "Team 标准席", "月付", 25, "USD", 25, "每席位", "高于 Pro", "协作、集中计费、SSO、管理控制", "2-150 人团队", verify="官方页面"),
    plan("Anthropic", "Claude", "Team 标准席", "年付", 20, "USD", 20, "每席位", "高于 Pro", "年付 $20/席/月；最多 $500/月共享 API 额度", "2-150 人团队", verify="官方页面"),
    plan("Anthropic", "Claude", "Team 高级席", "月付", 125, "USD", 125, "每席位", "标准席的 5 倍", "Claude Code/Cowork、Design、Science 等", "重度团队", verify="官方页面"),
    plan("Anthropic", "Claude", "Team 高级席", "年付", 100, "USD", 100, "每席位", "标准席的 5 倍", "年付 $100/席/月", "重度团队", verify="官方页面"),
    plan("Anthropic", "Claude", "Enterprise", "年付", 20, "USD", 20, "每席位，最低 20 席", "席位费 + API 用量费", "SCIM、审计日志、合规 API、自定义留存", "大型企业", verify="官方页面", note="席位 $20/席/月，按年计费，另加 API 用量"),
    # OpenAI
    plan("OpenAI", "ChatGPT", "Free", "月付", 0, "USD", 0, "1 个账号", "有限额度", "基础对话", "个人试用"),
    plan("OpenAI", "ChatGPT", "Go", "月付", 8, "USD", 8, "1 个账号", "轻量额度", "入门付费档", "轻度个人"),
    plan("OpenAI", "ChatGPT", "Plus", "月付", 20, "USD", 20, "1 个账号", "较高额度", "高级模型、工具、文件", "个人日常"),
    plan("OpenAI", "ChatGPT", "Pro 5x", "月付", 100, "USD", 100, "1 个账号", "Plus 的 5 倍", "更高模型额度与深度研究", "重度个人"),
    plan("OpenAI", "ChatGPT", "Pro 20x", "月付", 200, "USD", 200, "1 个账号", "Plus 的 20 倍", "最高个人额度", "重度个人"),
    plan("OpenAI", "ChatGPT", "Business 标准席", "月付", 25, "USD", 25, "每席位，最低 2 席", "团队共享额度", "管理后台、数据不用于训练", "中小企业", change="2026-04-02 由 $30 降至 $25"),
    plan("OpenAI", "ChatGPT", "Business 标准席", "年付", 20, "USD", 20, "每席位，最低 2 席", "团队共享额度", "年付 $20/席/月", "中小企业", change="2026-04-02 由 $25 降至 $20"),
    plan("OpenAI", "ChatGPT", "Enterprise", "年付", 60, "USD", 60, "按席位，约 150 席起", "定制", "SCIM、RBAC、数据驻留、专属支持", "大型企业", verify="第三方估算", note="公开报价约 $45-75/席/月，以商务报价为准"),
    # Google
    plan("Google", "Google AI", "AI Plus", "月付", 7.99, "USD", 7.99, "1 个账号", "基础额度", "Gemini 应用与云存储", "轻度个人"),
    plan("Google", "Google AI", "AI Pro", "月付", 19.99, "USD", 19.99, "1 个账号", "较高额度", "Gemini 高级模型、Flow、云存储", "个人日常"),
    plan("Google", "Google AI", "AI Ultra 5x", "月付", 99.99, "USD", 99.99, "1 个账号", "Pro 的 5 倍", "3.5 Flash 优先、20TB、YouTube Premium、$40 云额度", "重度个人", change="2026-05 新增 $99.99 档"),
    plan("Google", "Google AI", "AI Ultra 20x", "月付", 199.99, "USD", 199.99, "1 个账号", "Pro 的 20 倍", "Project Genie 等专属能力", "重度个人/团队", change="2026-05 由 $250 降至 $199.99"),
    # xAI
    plan("xAI", "SuperGrok", "Lite", "月付", 10, "USD", 10, "1 个账号", "基础额度", "基础模型访问", "轻度个人"),
    plan("xAI", "SuperGrok", "标准", "月付", 30, "USD", 30, "1 个账号", "较大共享周额度", "完整模型访问", "个人日常"),
    plan("xAI", "SuperGrok", "标准", "年付", 300, "USD", 25, "1 个账号", "较大共享周额度", "年付折合 $25/月", "个人日常"),
    plan("xAI", "SuperGrok", "Plus", "月付", 100, "USD", 100, "1 个账号", "更高额度", "更高用量", "重度个人"),
    plan("xAI", "SuperGrok", "Heavy", "月付", 300, "USD", 300, "1 个账号", "最高额度", "Heavy 多智能体模式、优先队列", "重度个人/团队"),
    plan("xAI", "SuperGrok", "Enterprise", "月付", 30, "USD", 30, "每席位", "团队额度", "团队管理", "企业"),
    # Kimi（国内）
    plan("Kimi", "Kimi 会员", "Go", "月付", 49, "CNY", 49, "1 个账号", "共享额度池", "通用会员", "轻度个人"),
    plan("Kimi", "Kimi 会员", "Go", "年付", 468, "CNY", 39, "1 个账号", "共享额度池", "年付折合 ¥39/月", "轻度个人"),
    plan("Kimi", "Kimi 会员", "Plus", "月付", 99, "CNY", 99, "1 个账号", "共享额度池", "更高用量", "个人日常"),
    plan("Kimi", "Kimi 会员", "Plus", "年付", 948, "CNY", 79, "1 个账号", "共享额度池", "年付折合 ¥79/月", "个人日常"),
    plan("Kimi", "Kimi 会员", "Pro", "月付", 199, "CNY", 199, "1 个账号", "共享额度池", "高用量", "重度个人"),
    plan("Kimi", "Kimi 会员", "Pro", "年付", 1908, "CNY", 159, "1 个账号", "共享额度池", "年付折合 ¥159/月", "重度个人"),
    plan("Kimi", "Kimi 会员", "Max", "月付", 699, "CNY", 699, "1 个账号", "共享额度池", "最高个人档", "重度个人/团队"),
    plan("Kimi", "Kimi 会员", "Max", "年付", 6708, "CNY", 559, "1 个账号", "共享额度池", "年付折合 ¥559/月", "重度个人/团队"),
    # 智谱
    plan("智谱", "GLM Coding Plan", "Lite", "月付", 118, "CNY", 118, "1 个账号", "10,000 积分/月", "GLM-5.3，适配 Claude Code/ZCode/Codex", "轻度开发者", change="2026-07-30 改版，原 ¥49"),
    plan("智谱", "GLM Coding Plan", "Pro", "月付", 538, "CNY", 538, "1 个账号", "60,000 积分/月", "更高积分，非高峰 50% 抵扣", "重度开发者", change="2026-07-30 改版，原 ¥149"),
    plan("智谱", "GLM Coding Plan", "Max", "月付", 1078, "CNY", 1078, "1 个账号", "140,000 积分/月", "最高积分", "团队/重度", change="2026-07-30 改版，原 ¥469"),
    plan("智谱", "GLM Coding Plan", "团队标准席", "月付", 598, "CNY", 598, "每席位，最低 2 席", "66,000 积分/席位/月", "团队管理与集中计费", "企业团队"),
    # 千问 App
    plan("阿里云", "千问 App", "高级", "月付", 19, "CNY", 19, "1 个账号", "2 倍额度", "Qwen3.8-Max、办公助理、文件交付", "个人", change="2026-08-10 上线"),
    plan("阿里云", "千问 App", "高级", "年付", 200, "CNY", 16.67, "1 个账号", "2 倍额度", "年付折合 ¥16.67/月", "个人"),
    plan("阿里云", "千问 App", "精英", "月付", 49, "CNY", 49, "1 个账号", "5 倍额度", "更高额度", "个人日常"),
    plan("阿里云", "千问 App", "精英", "年付", 568, "CNY", 47.33, "1 个账号", "5 倍额度", "年付折合 ¥47.33/月", "个人日常"),
    plan("阿里云", "千问 App", "旗舰", "月付", 128, "CNY", 128, "1 个账号", "20 倍额度", "最高个人额度", "重度个人"),
    plan("阿里云", "千问 App", "旗舰", "年付", 1499, "CNY", 124.92, "1 个账号", "20 倍额度", "年付折合 ¥124.92/月", "重度个人"),
    # 豆包
    plan("火山引擎", "豆包 App", "Pro", "月付", 68, "CNY", 68, "1 个账号", "标准额度", "豆包 Pro 会员", "个人"),
    plan("火山引擎", "豆包 App", "Pro", "年付", 688, "CNY", 57.33, "1 个账号", "标准额度", "年付折合 ¥57.33/月", "个人"),
    plan("火山引擎", "豆包 App", "增强版", "月付", 200, "CNY", 200, "1 个账号", "更高额度", "增强会员", "重度个人"),
    plan("火山引擎", "豆包 App", "增强版", "年付", 2048, "CNY", 170.67, "1 个账号", "更高额度", "年付折合 ¥170.67/月", "重度个人"),
    plan("火山引擎", "豆包 App", "尊享版", "月付", 500, "CNY", 500, "1 个账号", "最高额度", "尊享会员", "重度个人/团队"),
    plan("火山引擎", "豆包 App", "尊享版", "年付", 5088, "CNY", 424, "1 个账号", "最高额度", "年付折合 ¥424/月", "重度个人/团队"),
    # MiniMax
    plan("MiniMax", "Token Plan", "Plus", "月付", 49, "CNY", 49, "1 个账号", "按积分计", "轻量 API/开发", "个人开发者"),
    plan("MiniMax", "Token Plan", "Max", "月付", 119, "CNY", 119, "1 个账号", "按积分计", "高频编程/多模态", "个人开发者"),
    plan("MiniMax", "Token Plan", "Ultra", "月付", 469, "CNY", 469, "1 个账号", "按积分计", "重度 Agent 工作流", "团队/重度"),
    plan("MiniMax", "Token Plan", "Plus", "年付", 490, "CNY", 40.83, "1 个账号", "按积分计", "年付折合 ¥40.83/月", "个人开发者"),
    plan("MiniMax", "Token Plan", "Max", "年付", 1190, "CNY", 99.17, "1 个账号", "按积分计", "年付折合 ¥99.17/月", "个人开发者"),
    plan("MiniMax", "Token Plan", "Ultra", "年付", 4690, "CNY", 390.83, "1 个账号", "按积分计", "年付折合 ¥390.83/月", "团队/重度"),
    plan("MiniMax", "M Plan", "Go", "月付", 49, "CNY", 49, "1 个账号", "含 MiniMax Code", "个人 AI 订阅", "个人"),
    plan("MiniMax", "M Plan", "Explore", "月付", 119, "CNY", 119, "1 个账号", "含 MiniMax Code", "更高用量", "个人日常"),
    plan("MiniMax", "M Plan", "Build", "月付", 234.5, "CNY", 234.5, "1 个账号", "含 MiniMax Code", "构建型用量", "开发者"),
]

def limits_for(
    provider: str,
    model: str,
    tiers: list[tuple[str, int | None, int | None, int | None, int | None, int | None, int | None]],
    note: str,
    verify: str = "搜索摘要",
) -> list[list]:
    rows = []
    for tier, rpm, itpm, otpm, concurrency, month_cap, ten_min_cap in tiers:
        rows.append(
            [
                provider,
                model,
                tier,
                rpm,
                itpm,
                otpm,
                concurrency,
                month_cap,
                ten_min_cap,
                None,
                note,
                URL[provider],
                VERIFIED_AT,
                verify,
            ]
        )
    return rows


LIMITS = [
    *limits_for(
        "Anthropic",
        "Claude Fable 5.1",
        [("Start", 1000, 2_000_000, 400_000, None, 500, None), ("Build", 5000, 5_000_000, 1_000_000, None, 1000, None), ("Scale", 10000, 10_000_000, 2_000_000, None, 200_000, None)],
        "按模型族共享额度；缓存读取通常不计入输入 TPM",
    ),
    *limits_for(
        "Anthropic",
        "Claude Opus 5.5",
        [("Start", 1000, 2_000_000, 400_000, None, 500, None), ("Build", 5000, 5_000_000, 1_000_000, None, 1000, None), ("Scale", 10000, 10_000_000, 2_000_000, None, 200_000, None)],
        "按模型族共享额度；缓存读取通常不计入输入 TPM",
    ),
    *limits_for(
        "Anthropic",
        "Claude Sonnet 5.5",
        [("Start", 1000, 2_000_000, 400_000, None, 500, None), ("Build", 5000, 5_000_000, 1_000_000, None, 1000, None), ("Scale", 10000, 10_000_000, 2_000_000, None, 200_000, None)],
        "按模型族共享额度；缓存读取通常不计入输入 TPM",
    ),
    *limits_for(
        "OpenAI",
        "GPT-6 Astra",
        [("Build", 5000, 1_000_000, None, None, 500, None), ("Launch", 10000, 4_000_000, None, None, 5_000, None), ("Grow", 15000, 40_000_000, None, None, 200_000, None)],
        "2026-10-06 起改为 Build/Launch/Grow 三级",
    ),
    *limits_for(
        "OpenAI",
        "GPT-6.1 Sol",
        [("Build", 5000, 1_000_000, None, None, 500, None), ("Launch", 10000, 4_000_000, None, None, 5_000, None), ("Grow", 15000, 40_000_000, None, None, 200_000, None)],
        "与 GPT-6 Astra 同档",
    ),
    *limits_for(
        "OpenAI",
        "GPT-6 Luna",
        [("Build", 5000, 2_000_000, None, None, 500, None), ("Launch", 10000, 10_000_000, None, None, 5_000, None), ("Grow", 30000, 180_000_000, None, None, 200_000, None)],
        "低价模型额度更高",
    ),
    *limits_for(
        "DeepSeek",
        "deepseek-flash",
        [("默认", None, None, None, 2500, None, None)],
        "官方按并发数限流，未公开固定 RPM/TPM",
        verify="官方页面",
    ),
    *limits_for(
        "DeepSeek",
        "deepseek-v4-pro",
        [("默认", None, None, None, 500, None, None)],
        "官方按并发数限流，未公开固定 RPM/TPM",
        verify="官方页面",
    ),
    *limits_for(
        "Google",
        "Gemini 4 Argon",
        [("Free", None, None, None, None, None, None), ("Tier 1", None, None, None, None, None, 10), ("Tier 2", None, None, None, None, None, 50), ("Tier 3", None, None, None, None, None, 200)],
        "无免费额度；RPM/TPM 在 AI Studio 按项目查看",
        verify="官方页面",
    ),
    *limits_for(
        "火山引擎",
        "doubao-seed-2.1-pro",
        [("默认", 10000, 800_000, None, None, None, None)],
        "第三方口径，默认值以控制台「模型级别限流」为准",
    ),
    *limits_for("智谱", "GLM-5.3", [("按账号", None, None, None, None, None, None)], "未公开统一数值，按账号等级/控制台配额"),
    *limits_for("Kimi", "Kimi K3", [("按账号", None, None, None, None, None, None)], "未公开统一 RPM/TPM，按账号等级与充值档位"),
    *limits_for("MiniMax", "MiniMax M3", [("按账号", None, None, None, None, None, None)], "未公开统一数值，按账号/套餐配额"),
    *limits_for("阿里云", "Qwen3.8-Max", [("按账号", None, None, None, None, None, None)], "按地域与模型配额，百炼控制台可查/申请提升"),
    *limits_for("xAI", "Grok 4.7", [("按账号", None, None, None, None, None, None)], "未公开统一数值，按控制台配额"),
]


def write_sheet(path: Path, headers: list[str], rows: list[list], widths: list[int]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = path.stem
    ws.append(headers)
    for row in rows:
        ws.append(row)

    header_fill = PatternFill("solid", fgColor="1F4E79")
    header_font = Font(color="FFFFFF", bold=True, size=10)
    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 32

    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.border = border
            cell.alignment = Alignment(vertical="center", wrap_text=False)
            if isinstance(cell.value, float):
                cell.number_format = "0.0000"
            elif isinstance(cell.value, int):
                cell.number_format = "#,##0"

    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    wb.save(path)
    print(f"wrote {path.relative_to(ROOT)}  rows={len(rows)} cols={len(headers)}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    write_sheet(
        OUT / "model_catalog.xlsx",
        HEADERS["catalog"],
        CATALOG,
        [12, 14, 26, 30, 14, 10, 16, 14, 20, 12, 14, 42, 12, 14],
    )
    write_sheet(
        OUT / "price_book.xlsx",
        HEADERS["price"],
        PRICES,
        [12, 26, 14, 12, 10, 8, 14, 12, 12, 14, 14, 14, 14, 14, 22, 12, 12, 14, 14, 14, 14, 40, 12, 12, 46],
    )
    write_sheet(
        OUT / "subscription_plans.xlsx",
        HEADERS["plan"],
        PLANS,
        [12, 18, 16, 10, 12, 8, 14, 14, 18, 22, 40, 18, 26, 42, 12, 14, 40],
    )
    write_sheet(
        OUT / "rate_limits.xlsx",
        HEADERS["limit"],
        LIMITS,
        [12, 32, 12, 10, 14, 12, 10, 14, 18, 10, 50, 42, 12, 12],
    )


if __name__ == "__main__":
    main()
