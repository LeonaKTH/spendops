"""DeepSeek（OpenAI 兼容协议）客户端与模型输出解析。"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from app.core.config import get_settings

JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class LLMNotConfigured(RuntimeError):
    pass


@lru_cache
def get_llm(fast: bool = False, streaming: bool = False) -> ChatOpenAI:
    settings = get_settings()
    if not settings.llm_api_key:
        raise LLMNotConfigured("未配置 LLM_API_KEY，请在项目根目录 .env 中填写。")

    return ChatOpenAI(
        model=settings.llm_model_fast if fast else settings.llm_model_sql,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=0,
        max_tokens=1800,
        timeout=60,
        max_retries=1,
        streaming=streaming,
    )


def content_text(message: BaseMessage | Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text") or block.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content or "")


def parse_json_object(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except (TypeError, ValueError):
        pass

    match = JSON_BLOCK.search(raw)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None
