"""SpendOps G5 受控经营问数引擎（离线确定性分析 + 可选 LLM 解释）。

设计原则（区别于上游 LangGraph NL2SQL）：
- 不生成、不执行任意 SQL。AI 只能解析「意图 + 时间范围 + 供应商」，然后调用
  可信的 metrics 确定性计算，金额/数量/比例一律以数据库结果为准。
- 模型不得拥有任何写权限，不接触用户/密码/审计等敏感表。
- 离线模式无需 API Key，用规则解析意图 + 规则化解释，明确标注「确定性分析」。
- 可选 LLM 仅用于：解析意图（结果仍校验到固定枚举）与组织解释语言，
  绝不用模型生成最终数字。

结果字段统一 camelCase，供前端直接展示。
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import metrics

# 支持的意图（固定枚举，LLM 解析结果也必须落到这个集合内）。
INTENT_OVERVIEW = "overview"
INTENT_SUPPLIER_RANKING = "supplier_ranking"
INTENT_MONTHLY_TREND = "monthly_trend"
INTENT_SUPPLIER_TREND = "supplier_trend"
INTENT_DELIVERY = "delivery"
INTENT_PENDING_INVOICES = "pending_invoices"
INTENT_DISCREPANCIES = "discrepancies"

INTENT_LABELS = {
    INTENT_OVERVIEW: "经营总览（订单/收货/开票金额）",
    INTENT_SUPPLIER_RANKING: "供应商采购金额排名",
    INTENT_MONTHLY_TREND: "采购月度趋势",
    INTENT_SUPPLIER_TREND: "供应商采购金额变化",
    INTENT_DELIVERY: "交付履约与延期",
    INTENT_PENDING_INVOICES: "待核对发票",
    INTENT_DISCREPANCIES: "收货与开票差异",
}

# 指标口径说明（与 metrics.py 顶部注释一致，供结果溯源）。
METRIC_DEFINITIONS = {
    "orderAmount": "采购订单金额 = Σ 订单明细金额（数量×单价），排除已取消订单，时间按订单日期，未税、单币种 CNY。",
    "receiptAmount": "实际收货金额 = Σ 收货明细金额（收货数量×订单单价），排除已取消收货单，时间按收货日期。",
    "invoiceAmount": "已开票金额 = Σ 发票未税金额，排除已取消发票，时间按开票日期。",
    "pendingVerificationAmount": "待核对金额 = Σ 状态为「待核对」的发票未税金额。",
    "deliveryRate": "交货及时率 = 及时明细数 / 可判定明细数（仅统计约定交期非空且已履约或已逾期的明细）。",
}


_CN_DIGITS = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def _cn_number(text: str) -> int | None:
    """把「最近三个月 / 最近 10 天」里的数量解析为整数（支持中文数字与阿拉伯数字）。"""
    m = re.search(r"(\d+)\s*(?:个)?月", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*天", text)
    if m:
        return int(m.group(1))
    m = re.search(r"([一二两三四五六七八九十]+)\s*个月", text)
    if m:
        s = m.group(1)
        if s in _CN_DIGITS:
            return _CN_DIGITS[s]
        if len(s) == 2 and s[0] == "十":
            return 10 + _CN_DIGITS.get(s[1], 0)
    return None


def _month_range(month: date) -> tuple[date, date]:
    """某月的闭区间。"""
    if month.month == 12:
        nxt = date(month.year + 1, 1, 1)
    else:
        nxt = date(month.year, month.month + 1, 1)
    return month, nxt - timedelta(days=1)


def _parse_time_range(question: str, today: date) -> tuple[date, date, str | None]:
    """从问题里提取时间范围（闭区间），返回 (start, end, 附加说明)。

    支持：YYYY年、YYYY年M月、M月、今年、去年、上半年/下半年、上个月、最近N个月/N天。
    未命中时回退到「今年」，并在说明中标注默认假设。
    """
    q = question.strip()

    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月", q)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            start, end = _month_range(date(y, mo, 1))
            return start, end, None

    m = re.search(r"(\d{4})\s*年", q)
    if m:
        y = int(m.group(1))
        return date(y, 1, 1), date(y, 12, 31), None

    m = re.search(r"(?<!\d)(\d{1,2})\s*月", q)
    if m:
        mo = int(m.group(1))
        if 1 <= mo <= 12:
            start, end = _month_range(date(today.year, mo, 1))
            return start, end, None

    if "上半年" in q:
        return date(today.year, 1, 1), date(today.year, 6, 30), None
    if "下半年" in q:
        return date(today.year, 7, 1), date(today.year, 12, 31), None
    if "去年" in q:
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), None
    if "上个月" in q or "上月" in q:
        prev = date(today.year, today.month, 1) - timedelta(days=1)
        start, end = _month_range(date(prev.year, prev.month, 1))
        return start, end, None
    if "今年" in q:
        return date(today.year, 1, 1), date(today.year, 12, 31), None

    if re.search(r"(?:最近|近)\s*[\d一二两三四五六七八九十]+", q):
        if "天" in q:
            n = _cn_number(q)
            if n:
                return today - timedelta(days=n), today, f"最近 {n} 天"
        n = _cn_number(q)
        if n:
            end = today
            start = end - timedelta(days=30 * n)
            start = date(start.year, start.month, 1)
            return start, end, f"最近 {n} 个月（{start} 至 {end}）"

    # 默认今年，并标注。
    return date(today.year, 1, 1), date(today.year, 12, 31), "未指定时间，默认按今年统计。"


def _match_supplier(question: str, suppliers: list[dict[str, Any]]) -> dict[str, Any] | None:
    """按编码（SUP-xx）或名称子串匹配供应商（返回第一个匹配）。"""
    for s in suppliers:
        code = str(s.get("code") or "")
        name = str(s.get("name") or "")
        if code and code.lower() in question.lower():
            return s
    for s in suppliers:
        name = str(s.get("name") or "")
        if name and name in question:
            return s
    return None


# 中文公司名特征：通常以这些后缀结尾；泛化词「供应商」不含这些后缀，不会被误判。
_COMPANY_TOKEN_RE = re.compile(
    r"[\u4e00-\u9fa5]{2,10}(?:公司|集团|科技|电子|机械|材料|包装|元件|办公|精密|智造|信息)"
)


def _match_suppliers(
    question: str, suppliers: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], bool]:
    """返回 (匹配列表, 是否提到公司名但未匹配)。

    - 匹配列表：按编码优先、其次名称子串，可能 0/1/多个。
    - named_unmatched：问题中出现「公司名特征」但未命中任何已知供应商，
      用于避免「明确指定某供应商但未找到」时静默降级为整体数据。
    """
    matches: list[dict[str, Any]] = []
    q = question.lower()
    for s in suppliers:
        code = str(s.get("code") or "").lower()
        if code and code in q:
            matches.append(s)
    if not matches:
        for s in suppliers:
            name = str(s.get("name") or "")
            if name and name in question:
                matches.append(s)

    named_tokens = set(_COMPANY_TOKEN_RE.findall(question))
    known_names = {str(s.get("name") or "") for s in suppliers}
    named_unmatched = bool(named_tokens - known_names)
    return matches, named_unmatched


def _detect_intent(question: str) -> str:
    q = question
    if any(k in q for k in ("待核对", "待核", "pending")):
        return INTENT_PENDING_INVOICES
    if any(k in q for k in ("延期", "延迟", "按时", "及时", "交付", "履约")):
        return INTENT_DELIVERY
    if any(k in q for k in ("差异", "不一致", "收货.*开票", "开票.*收货", "对不上")):
        return INTENT_DISCREPANCIES
    if any(k in q for k in ("排名", "最高", "最多", "top", "集中", "哪些供应商", "哪个供应商")):
        return INTENT_SUPPLIER_RANKING
    if "供应商" in q and any(k in q for k in ("变化", "趋势", "增长", "上涨", "下降")):
        return INTENT_SUPPLIER_TREND
    if any(k in q for k in ("趋势", "按月", "每月", "月度", "变化")):
        return INTENT_MONTHLY_TREND
    return INTENT_OVERVIEW


def parse_intent(
    question: str, suppliers: list[dict[str, Any]], today: date | None = None
) -> dict[str, Any]:
    """规则解析问题 → 结构化意图（时间范围 + 供应商 + 意图枚举）。"""
    today = today or date.today()
    start, end, time_note = _parse_time_range(question, today)
    matches, named_unmatched = _match_suppliers(question, suppliers)
    supplier = matches[0] if len(matches) == 1 else None
    supplier_ambiguous = len(matches) > 1
    supplier_unmatched = named_unmatched and not matches
    intent = _detect_intent(question)
    # 供应商名 + 变化/趋势关键词 → 供应商采购金额变化（而非整体月度趋势）。
    if (
        intent == INTENT_MONTHLY_TREND
        and supplier is not None
        and any(k in question for k in ("变化", "趋势", "增长", "上涨", "下降"))
    ):
        intent = INTENT_SUPPLIER_TREND
    # 明确指定供应商但未匹配到：不静默降级为整体数据，交由上层澄清。
    if intent == INTENT_SUPPLIER_TREND and supplier is None and not supplier_unmatched:
        intent = INTENT_MONTHLY_TREND

    m = re.search(r"(?:top|前|排名前)\s*(\d+)", question, re.IGNORECASE)
    top_n = int(m.group(1)) if m else 10
    top_n = max(1, min(top_n, 50))

    return {
        "intent": intent,
        "intentLabel": INTENT_LABELS[intent],
        "start": start,
        "end": end,
        "supplier": supplier,
        "supplierAmbiguous": supplier_ambiguous,
        "supplierUnmatched": supplier_unmatched,
        "topN": top_n,
        "timeNote": time_note,
    }


def _fmt_amount(v: Decimal | None) -> str:
    if v is None:
        return "不可计算"
    return f"¥{v:,.2f}"


def _fmt_rate(v: Decimal | None) -> str:
    if v is None:
        return "不可计算（缺少约定交期数据）"
    return f"{v * 100:.1f}%"


async def _run_intent(
    session: AsyncSession, intent: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """执行意图，返回 (facts, observations)。"""
    start = intent["start"]
    end = intent["end"]
    supplier_id = intent["supplier"]["id"] if intent["supplier"] else None
    code = intent["intent"]
    observations: list[str] = []

    if code == INTENT_OVERVIEW:
        ov = await metrics.overview(session, start, end, supplier_id)
        facts = {
            "orderAmount": ov["orderAmount"],
            "receiptAmount": ov["receiptAmount"],
            "invoiceAmount": ov["invoiceAmount"],
            "pendingVerificationAmount": ov["pendingVerificationAmount"],
            "supplierCount": ov["supplierCount"],
        }
    elif code == INTENT_SUPPLIER_RANKING:
        rank = await metrics.supplier_ranking(session, start, end, intent["topN"])
        facts = {
            "ranking": rank["ranking"],
            "totalAmount": rank["totalAmount"],
            "topAmount": rank["topAmount"],
            "concentration": rank["concentration"],
        }
        if rank["ranking"]:
            top1 = rank["ranking"][0]
            observations.append(
                f"排名第一的供应商是「{top1['name']}」，采购金额 {_fmt_amount(top1['amount'])}，"
                f"占比 {top1['share'] * 100:.1f}%。"
            )
    elif code in (INTENT_MONTHLY_TREND, INTENT_SUPPLIER_TREND):
        trend = await metrics.monthly_trend(session, start, end, supplier_id)
        facts = {"trend": trend["series"]}
        series = trend["series"]
        if len(series) >= 2:
            prev = series[-2]["orderAmount"]
            cur = series[-1]["orderAmount"]
            if prev and prev != 0:
                chg = (cur - prev) / prev
                direction = "增长" if chg >= 0 else "下降"
                observations.append(
                    f"最近一月订单金额较前一月{direction} {abs(chg) * 100:.1f}%"
                    f"（{_fmt_amount(prev)} → {_fmt_amount(cur)}）。此为数据事实，非因果结论。"
                )
    elif code == INTENT_DELIVERY:
        perf = await metrics.delivery_performance(session, start, end, supplier_id)
        late = await metrics.late_orders(session, start, end, supplier_id)
        facts = {
            "ontime": perf["ontime"],
            "late": perf["late"],
            "judged": perf["judged"],
            "excluded": perf["excluded"],
            "rate": perf["rate"],
            "lateOrders": late,
        }
        observations.append(
            f"可判定明细 {perf['judged']} 条，其中及时 {perf['ontime']} 条、延期 {perf['late']} 条。"
        )
    elif code == INTENT_PENDING_INVOICES:
        pending = await metrics.pending_invoices(session, start, end, supplier_id)
        facts = {
            "count": pending["count"],
            "total": pending["total"],
            "items": pending["items"],
        }
        observations.append(
            f"当前有 {pending['count']} 张待核对发票，涉及金额 {_fmt_amount(pending['total'])}。"
        )
    elif code == INTENT_DISCREPANCIES:
        items = await metrics.discrepancies(session, start, end)
        facts = {"items": items, "total": len(items)}
        with_diff = [i for i in items if i["discrepancyKinds"]]
        observations.append(
            f"共 {len(with_diff)} 条明细存在收货/开票差异，占全部明细 {len(items)} 条的一部分。"
        )
    else:  # 理论不可达
        raise ValueError(f"未知意图：{code}")

    return facts, observations


async def run_analysis(
    session: AsyncSession,
    question: str,
    suppliers: list[dict[str, Any]],
    *,
    mode: str = "offline",
    today: date | None = None,
) -> dict[str, Any]:
    """执行受控经营问数，返回结构化结果。

    mode: "offline"（确定性规则）或 "llm"（可选 LLM 解释，仍以 metrics 计算结果为准）。
    LLM 模式下若未配置 key 或调用失败，自动降级为离线确定性分析并标注。
    """
    today = today or date.today()
    intent = parse_intent(question, suppliers, today)

    # 供应商无法唯一确定时，不静默用整体数据代替：返回澄清说明，不执行指标计算。
    if intent.get("supplierUnmatched") or intent.get("supplierAmbiguous"):
        if intent.get("supplierAmbiguous"):
            clarification = "检测到多个匹配的供应商，请指明具体供应商名称或编码后再问。"
        else:
            clarification = "未在系统中找到你指定的供应商，请确认名称或使用供应商编码。"
        return {
            "question": question,
            "mode": "offline",
            "intent": intent["intent"],
            "intentLabel": intent["intentLabel"],
            "timeRange": {"start": intent["start"].isoformat(), "end": intent["end"].isoformat()},
            "supplier": None,
            "metricName": intent["intentLabel"],
            "metricDefinition": "",
            "facts": {},
            "explanation": clarification,
            "observations": [],
            "generatedAt": today.isoformat(),
            "limitations": ["无法唯一确定供应商，未执行任何指标计算，也未用整体数据代替。"],
        }

    facts, observations = await _run_intent(session, intent)

    limitations: list[str] = []
    if intent["timeNote"]:
        limitations.append(intent["timeNote"])
    if intent["supplier"]:
        limitations.append(f"已按供应商「{intent['supplier']['name']}」筛选。")
    limitations.append("金额为未税、单币种 CNY，口径见指标定义。")

    explanation: str | None = None
    if mode == "llm":
        explanation = await generate_llm_explanation(
            question, intent["intentLabel"], facts, observations
        )
        if explanation is None:
            mode = "offline"
            limitations.append("未配置 LLM_API_KEY 或模型调用失败，已降级为离线确定性分析。")

    if mode == "llm" and explanation:
        explain_text = explanation
    else:
        explain_text = _rule_explain(intent["intent"], facts, observations)

    return {
        "question": question,
        "mode": mode,
        "intent": intent["intent"],
        "intentLabel": intent["intentLabel"],
        "timeRange": {"start": intent["start"].isoformat(), "end": intent["end"].isoformat()},
        "supplier": intent["supplier"],
        "metricName": intent["intentLabel"],
        "metricDefinition": METRIC_DEFINITIONS.get(_primary_metric(intent["intent"]), ""),
        "facts": _jsonable(facts),
        "explanation": explain_text,
        "observations": observations,
        "generatedAt": today.isoformat(),
        "limitations": limitations,
    }


def _primary_metric(intent: str) -> str:
    return {
        INTENT_OVERVIEW: "orderAmount",
        INTENT_SUPPLIER_RANKING: "orderAmount",
        INTENT_MONTHLY_TREND: "orderAmount",
        INTENT_SUPPLIER_TREND: "orderAmount",
        INTENT_DELIVERY: "deliveryRate",
        INTENT_PENDING_INVOICES: "pendingVerificationAmount",
        INTENT_DISCREPANCIES: "orderAmount",
    }.get(intent, "orderAmount")


def _jsonable(value: Any) -> Any:
    """把 Decimal/date 转成 JSON 可序列化类型（金额 Decimal→str 保精度）。"""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, timedelta)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


async def generate_llm_explanation(
    question: str, intent_label: str, facts: dict[str, Any], observations: list[str]
) -> str | None:
    """可选 LLM：根据确定性结果生成中文解释。

    - 未配置 LLM_API_KEY 或调用失败/超时，返回 None（由上层降级到离线解释）。
    - 提示词严格限制：只能用给定事实中的数字，禁止编造；原因类表述必须区分事实与推测。
    """
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.agent.llm import content_text, get_llm
    except Exception:
        return None

    try:
        llm = get_llm(fast=True)
    except Exception:
        return None

    facts_text = _jsonable(facts)
    prompt = [
        SystemMessage(
            content=(
                "你是采购经营数据分析助手。根据给定的确定性计算结果，用中文 2-4 句话解释。"
                "硬性规则：只能使用下面「计算结果」里真实存在的数字，绝对禁止编造任何金额、数量或比例；"
                "如果提到原因或趋势，必须明确区分「数据事实」与「推测」，不得把相关性说成因果。"
            )
        ),
        HumanMessage(
            content=(
                f"用户问题：{question}\n"
                f"分析类型：{intent_label}\n"
                f"计算结果（唯一可信来源）：{facts_text}\n"
                f"已知观察：{observations}"
            )
        ),
    ]
    try:
        message = await llm.ainvoke(prompt)
    except Exception:
        return None
    text = content_text(message).strip()
    return text or None


def _rule_explain(intent: str, facts: dict[str, Any], observations: list[str]) -> str:
    """规则化解释：只陈述数据库计算得到的事实，不编造因果。"""
    lines: list[str] = []
    if intent == INTENT_OVERVIEW:
        lines.append(
            f"采购订单金额 {_fmt_amount(facts.get('orderAmount'))}，"
            f"已收货金额 {_fmt_amount(facts.get('receiptAmount'))}，"
            f"已开票金额（未税）{_fmt_amount(facts.get('invoiceAmount'))}，"
            f"待核对金额 {_fmt_amount(facts.get('pendingVerificationAmount'))}，"
            f"供应商 {facts.get('supplierCount', 0)} 家。"
        )
    elif intent == INTENT_SUPPLIER_RANKING:
        rank = facts.get("ranking") or []
        if rank:
            top = "、".join(f"{r['name']}({_fmt_amount(r['amount'])})" for r in rank[:5])
            lines.append(f"采购金额排名（前 {len(rank)}）：{top}。")
        else:
            lines.append("该时间范围内没有采购订单数据。")
    elif intent in (INTENT_MONTHLY_TREND, INTENT_SUPPLIER_TREND):
        series = facts.get("trend") or []
        if series:
            last = series[-1]
            lines.append(
                f"最近一月（{last['month']}）订单金额 {_fmt_amount(last['orderAmount'])}，"
                f"收货金额 {_fmt_amount(last['receiptAmount'])}，"
                f"开票金额 {_fmt_amount(last['invoiceAmount'])}。"
            )
        else:
            lines.append("该时间范围内没有趋势数据。")
    elif intent == INTENT_DELIVERY:
        lines.append(
            f"交货及时率 {_fmt_rate(facts.get('rate'))}，"
            f"及时 {facts.get('ontime', 0)} 条、延期 {facts.get('late', 0)} 条。"
        )
    elif intent == INTENT_PENDING_INVOICES:
        lines.append(
            f"待核对发票 {facts.get('count', 0)} 张，涉及金额 {_fmt_amount(facts.get('total'))}。"
        )
    elif intent == INTENT_DISCREPANCIES:
        lines.append(f"共 {facts.get('total', 0)} 条明细参与差异分析。")

    for obs in observations:
        lines.append(f"（观察）{obs}")

    lines.append("以上金额与比例均为数据库确定性计算，模型未参与生成数字。")
    return "\n".join(lines)
