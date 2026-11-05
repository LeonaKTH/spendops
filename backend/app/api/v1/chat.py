"""NL2SQL 问数接口，以 SSE 推送 Agent 的中间过程与最终结果。"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.agent.graph import agent_graph
from app.api.v1.schemas import ChatRequest
from app.core.security import AuthUser, get_current_user
from app.db.session import SessionLocal
from app.infra.cache import SCHEMA_CACHE_KEY, get_json, set_json
from app.services.datasets import DatasetMeta, load_datasets
from app.services.documents import search_chunks, wants_contracts

router = APIRouter(tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _serialize(dataset: DatasetMeta) -> dict[str, Any]:
    return {
        "id": dataset.id,
        "name": dataset.name,
        "table": dataset.full_table,
        "row_count": dataset.row_count,
        "columns": [
            {
                "display": column.display,
                "physical": column.physical,
                "kind": column.kind,
                "sample": column.sample,
            }
            for column in dataset.columns
        ],
    }


async def _load_schema(dataset_ids: list[str]) -> list[dict[str, Any]]:
    cached = await get_json(SCHEMA_CACHE_KEY)
    if isinstance(cached, list) and not dataset_ids:
        return [item for item in cached if isinstance(item, dict)]

    async with SessionLocal() as session:
        datasets = await load_datasets(session, dataset_ids or None)

    serialized = [_serialize(dataset) for dataset in datasets]
    if not dataset_ids:
        await set_json(SCHEMA_CACHE_KEY, serialized, ttl=60)
    return serialized


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    _current: AuthUser = Depends(get_current_user),
) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

        def emit(event: str, data: dict[str, Any]) -> None:
            queue.put_nowait((event, data))

        async def run() -> None:
            try:
                datasets = await _load_schema(payload.dataset_ids)
                if not datasets:
                    emit(
                        "error",
                        {"message": "还没有可用的数据集，请先在「数据接入」上传采购 Excel。"},
                    )
                    return

                emit("status", {"stage": "正在理解问题…"})

                contracts: list[dict[str, Any]] = []
                if wants_contracts(payload.question):
                    emit("status", {"stage": "正在检索合同条款…"})
                    async with SessionLocal() as session:
                        contracts = await search_chunks(session, payload.question)
                    if contracts:
                        emit(
                            "sources",
                            {
                                "items": [
                                    {
                                        "documentId": str(item.get("document_id") or ""),
                                        "document": str(item.get("document") or ""),
                                        "page": item.get("page"),
                                        "snippet": str(item.get("content") or "")[:200],
                                    }
                                    for item in contracts
                                ]
                            },
                        )

                state = {
                    "question": payload.question.strip(),
                    "datasets": datasets,
                    "contracts": contracts,
                    "attempts": 0,
                }
                await agent_graph.ainvoke(
                    state,
                    {"configurable": {"emit": emit}},
                )
            except Exception as exc:
                emit("error", {"message": f"服务异常：{str(exc)[:300]}"})
            finally:
                emit("done", {})

        task = asyncio.create_task(run())
        try:
            while True:
                event, data = await queue.get()
                yield _sse(event, data)
                if event == "done":
                    break
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
