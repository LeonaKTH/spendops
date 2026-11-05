"""LangGraph NL2SQL Agent。

流程：
    generate_sql -> validate_sql -> execute_sql -> build_chart -> summarize
                       |  ^             |  ^
                       v  |             v  |
                     repair（最多 3 次）  fail

节点通过 config["configurable"]["emit"] 把过程事件推给 SSE 接口，
因此图本身不依赖任何 Web 框架。
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app.agent.chart import build_chart
from app.agent.llm import content_text, get_llm, parse_json_object
from app.services.query import (
    SqlValidationError,
    display_map,
    execute_readonly,
    validate_readonly_sql,
)

MAX_ATTEMPTS = 3

Emit = Callable[[str, dict[str, Any]], None]


class AgentState(TypedDict, total=False):
    question: str
    datasets: list[dict[str, Any]]
    contracts: list[dict[str, Any]]
    sql: str
    chart_plan: dict[str, Any]
    explanation: str
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool
    error: str
    retryable: bool
    skip_sql: bool
    attempts: int
    summary: str


SYSTEM_PROMPT = """你是 ProcureBI 的 PostgreSQL 数据分析师，负责把大模型采购场景的问题翻译成只读 SQL，并给出图表建议。

只输出一个 JSON 对象，不要输出 Markdown、代码围栏或额外解释：
{
  "sql": "SELECT ...",
  "chart": {
    "type": "bar | line | pie | table",
    "title": "图表标题",
    "x": "结果中的维度列名",
    "series": ["结果中的数值列名"],
    "unit": "元"
  },
  "explanation": "一句话说明查询思路"
}

硬性规则：
1. 只能查询下面列出的物理表，必须写全 ds 前缀，例如 ds.t_bills_ab12cd。
2. 只能生成一条 SELECT，禁止 INSERT / UPDATE / DELETE / DDL / 多条语句。
3. SQL 中必须使用“物理列名”，并用双引号包裹（中文列名必须加引号）。
4. chart 中的 x 和 series 必须与 SQL 的 SELECT 别名完全一致；建议给聚合列起中文别名，如 总金额、调用量。
5. 时间字段是 date 类型，可直接比较；金额聚合用 SUM，单价用 AVG，次数用 COUNT。
6. 金额/成本类问题优先按供应商、月份等维度聚合，结果不超过 50 行。
7. 如果问题无法用现有数据回答，sql 返回 null，并在 explanation 中说明缺少哪些数据。
8. 不要调用 pg_read_file、dblink 等系统函数。"""


def _emit(config: Any) -> Emit:
    configurable = (config or {}).get("configurable", {}) if isinstance(config, dict) else {}
    emit = configurable.get("emit")
    if callable(emit):
        return emit

    def noop(_event: str, _data: dict[str, Any]) -> None:
        return None

    return noop


def _used_datasets(sql: str, datasets: list[dict[str, Any]]) -> list[str]:
    """按物理表名找出这条 SQL 实际用到的数据集，用于前端展示执行上下文。"""
    lowered = sql.lower()
    names: list[str] = []
    for dataset in datasets:
        table = str(dataset.get("table") or "").lower()
        if table and re.search(rf"\b{re.escape(table)}\b", lowered):
            name = str(dataset.get("name") or "")
            if name and name not in names:
                names.append(name)
    return names


def _schema_text(datasets: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for dataset in datasets:
        lines = [
            f"数据集：{dataset['name']}",
            f"物理表：{dataset['table']}",
            f"行数：{dataset.get('row_count', 0)}",
            "字段（显示名 => 物理列名 (类型, 样例)）：",
        ]
        for column in dataset.get("columns", []):
            sample = str(column.get("sample") or "")[:40]
            lines.append(
                f"- {column['display']} => \"{column['physical']}\" "
                f"({column.get('kind', 'text')}, {sample})"
            )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _contract_text(contracts: list[dict[str, Any]], limit: int = 3) -> str:
    if not contracts:
        return ""
    blocks = []
    for item in contracts[:limit]:
        page = f" 第 {item['page']} 页" if item.get("page") else ""
        blocks.append(f"《{item.get('document', '合同')}》{page}：\n{str(item.get('content', ''))[:400]}")
    return "\n\n".join(blocks)


def _serialize_rows(columns: list[str], rows: list[list[Any]], limit: int = 20) -> str:
    lines = [" | ".join(columns)]
    for row in rows[:limit]:
        lines.append(" | ".join("" if value is None else str(value)[:40] for value in row))
    return "\n".join(lines)


async def generate_sql(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    emit = _emit(config)
    attempts = int(state.get("attempts", 0)) + 1
    emit("status", {"stage": "正在修正 SQL…" if state.get("error") else "正在生成 SQL…"})

    contracts = _contract_text(state.get("contracts", []))
    contract_block = (
        f"\n\n合同条款参考（只用于理解业务口径，不要从中推断表名或字段名）：\n{contracts}"
        if contracts
        else ""
    )

    prompt = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"可用数据集：\n{_schema_text(state.get('datasets', []))}\n\n"
                f"当前问题：{state['question']}{contract_block}"
            )
        ),
    ]

    previous_error = state.get("error")
    if previous_error:
        prompt.append(
            HumanMessage(
                content=(
                    "上一次的回答有问题，请修正后重新输出完整 JSON：\n"
                    f"上一次 SQL：{state.get('sql') or '（无）'}\n"
                    f"错误信息：{previous_error}"
                )
            )
        )

    try:
        message = await get_llm().ainvoke(prompt)
    except Exception as exc:  # 网络、鉴权、额度等问题
        return {
            "error": f"调用大模型失败：{str(exc)[:300]}",
            "retryable": True,
            "attempts": attempts,
        }

    payload = parse_json_object(content_text(message))
    if payload is None:
        return {
            "error": "模型返回的内容不是有效 JSON，请重新生成。",
            "retryable": True,
            "attempts": attempts,
        }

    sql = payload.get("sql")
    explanation = str(payload.get("explanation") or "").strip()
    chart = payload.get("chart") if isinstance(payload.get("chart"), dict) else {}

    if not isinstance(sql, str) or not sql.strip():
        # 有合同条款时，允许跳过 SQL 直接基于文档回答。
        if state.get("contracts"):
            return {
                "sql": "",
                "error": "",
                "retryable": False,
                "skip_sql": True,
                "attempts": attempts,
                "chart_plan": chart,
            }
        return {
            "error": explanation or "无法根据现有数据集回答这个问题。",
            "retryable": False,
            "attempts": attempts,
            "chart_plan": chart,
        }

    return {
        "sql": sql.strip(),
        "chart_plan": chart,
        "explanation": explanation,
        "error": "",
        "retryable": False,
        "attempts": attempts,
    }


async def validate_sql(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    emit = _emit(config)
    # generate_sql 已经设置了错误（不可重试或等待重试），跳过校验直接交给路由。
    if state.get("error"):
        return {}

    allowed = {dataset["table"] for dataset in state.get("datasets", [])}
    try:
        checked = validate_readonly_sql(state.get("sql", ""), allowed)
    except SqlValidationError as exc:
        return {"error": str(exc), "retryable": True}

    emit(
        "sql",
        {
            "sql": checked,
            "datasets": _used_datasets(checked, state.get("datasets", [])),
        },
    )
    return {"sql": checked, "error": "", "retryable": False}


async def execute_sql(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    emit = _emit(config)
    emit("status", {"stage": "正在执行查询…"})

    datasets = state.get("datasets", [])
    mapping = {
        column["physical"]: column["display"]
        for dataset in datasets
        for column in dataset.get("columns", [])
    }

    try:
        result = await execute_readonly(state.get("sql", ""), mapping)
    except Exception as exc:
        return {"error": f"SQL 执行失败：{str(exc)[:300]}", "retryable": True}

    emit(
        "table",
        {
            "columns": result.columns,
            "rows": result.rows,
            "truncated": result.truncated,
        },
    )
    return {
        "columns": result.columns,
        "rows": result.rows,
        "truncated": result.truncated,
        "error": "",
        "retryable": False,
    }


async def build_chart_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    emit = _emit(config)
    emit("status", {"stage": "正在生成图表…"})
    chart = build_chart(state.get("chart_plan"), state.get("columns", []), state.get("rows", []))
    if chart:
        emit("chart", chart)
    return {}


async def summarize(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    emit = _emit(config)
    emit("status", {"stage": "正在总结结论…"})

    columns = state.get("columns", [])
    rows = state.get("rows", [])
    contracts = _contract_text(state.get("contracts", []))

    if not rows and not contracts:
        text = "没有查询到符合条件的数据，可以换一种问法，或检查筛选条件是否过严。"
        emit("text", {"delta": text})
        return {"summary": text}

    sections = [f"用户问题：{state['question']}"]
    if rows:
        sections.append(
            f"执行的 SQL：{state.get('sql', '')}\n"
            f"查询结果（共 {len(rows)} 行"
            f"{'，已截断' if state.get('truncated') else ''}）：\n"
            f"{_serialize_rows(columns, rows)}"
        )
    if contracts:
        sections.append(f"合同条款参考（回答时可引用合同名称与页码）：\n{contracts}")
    context = "\n\n".join(sections)

    messages = [
        SystemMessage(
            content=(
                "你是采购 BI 分析师。根据查询结果和合同条款用中文回答用户，2-4 句话，"
                "先给结论，再给关键数字。只使用材料中真实存在的数据，不要编造。"
                "如果查询结果为空，就基于合同条款回答。直接输出正文，不要 Markdown 标题。"
            )
        ),
        HumanMessage(content=context),
    ]

    collected: list[str] = []
    try:
        async for chunk in get_llm(fast=True, streaming=True).astream(messages):
            delta = content_text(chunk)
            if delta:
                collected.append(delta)
                emit("text", {"delta": delta})
    except Exception:
        if not collected:
            fallback = f"查询完成，共返回 {len(rows)} 行结果。"
            emit("text", {"delta": fallback})
            collected.append(fallback)

    return {"summary": "".join(collected)}


async def fail(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    emit = _emit(config)
    emit("error", {"message": state.get("error") or "处理失败，请稍后重试。"})
    return {}


def _next_after(state: AgentState, success_node: str) -> str:
    if not state.get("error"):
        return success_node
    if state.get("retryable") and int(state.get("attempts", 0)) < MAX_ATTEMPTS:
        return "generate_sql"
    return "fail"


def _route_after_generate(state: AgentState) -> str:
    if state.get("skip_sql"):
        return "summarize"
    if not state.get("error"):
        return "validate_sql"
    if state.get("retryable") and int(state.get("attempts", 0)) < MAX_ATTEMPTS:
        return "generate_sql"
    return "fail"


def _route_after_validate(state: AgentState) -> str:
    return _next_after(state, "execute_sql")


def _route_after_execute(state: AgentState) -> str:
    return _next_after(state, "build_chart")


def build_graph() -> Any:
    graph = StateGraph(AgentState)
    graph.add_node("generate_sql", generate_sql)
    graph.add_node("validate_sql", validate_sql)
    graph.add_node("execute_sql", execute_sql)
    graph.add_node("build_chart", build_chart_node)
    graph.add_node("summarize", summarize)
    graph.add_node("fail", fail)

    graph.add_edge(START, "generate_sql")
    graph.add_conditional_edges(
        "generate_sql",
        _route_after_generate,
        {
            "validate_sql": "validate_sql",
            "summarize": "summarize",
            "generate_sql": "generate_sql",
            "fail": "fail",
        },
    )
    graph.add_conditional_edges(
        "validate_sql",
        _route_after_validate,
        {"execute_sql": "execute_sql", "generate_sql": "generate_sql", "fail": "fail"},
    )
    graph.add_conditional_edges(
        "execute_sql",
        _route_after_execute,
        {"build_chart": "build_chart", "generate_sql": "generate_sql", "fail": "fail"},
    )
    graph.add_edge("build_chart", "summarize")
    graph.add_edge("summarize", END)
    graph.add_edge("fail", END)
    return graph.compile()


agent_graph = build_graph()
