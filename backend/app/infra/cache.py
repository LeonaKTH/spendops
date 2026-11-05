"""Redis 缓存封装。Redis 不可用时自动退化为无缓存，不影响主流程。"""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis

from app.core.config import get_settings

SCHEMA_CACHE_KEY = "procurebi:schema:v1"

_client: Redis | None = None


def _redis() -> Redis:
    global _client
    if _client is None:
        # 本地 Windows 版 Redis 5.x 不支持 RESP3，显式使用协议 2。
        _client = Redis.from_url(get_settings().redis_url, protocol=2)
    return _client


def get_redis() -> Redis:
    """供限流等场景复用同一个 Redis 客户端。"""
    return _redis()


async def get_json(key: str) -> Any | None:
    try:
        raw = await _redis().get(key)
    except Exception:
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


async def set_json(key: str, value: Any, ttl: int = 60) -> None:
    try:
        await _redis().set(key, json.dumps(value, ensure_ascii=False), ex=ttl)
    except Exception:
        return


async def invalidate(key: str = SCHEMA_CACHE_KEY) -> None:
    try:
        await _redis().delete(key)
    except Exception:
        return
