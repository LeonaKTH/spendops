"""采购写操作的幂等支持。

关键写操作支持 Idempotency-Key：
- 客户端对同一业务请求使用同一个 key 重试时，若请求内容一致，返回原资源，不重复创建。
- 请求内容通过 SHA-256 指纹校验，key 被复用但内容不同则返回 409。
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IdempotencyKey
from app.services.purchasing.domain import ConflictError


def request_fingerprint(payload: dict) -> str:
    """计算请求内容指纹（稳定序列化，字段顺序无关）。"""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def resolve_idempotency(
    session: AsyncSession,
    key: str,
    resource_type: str,
    fingerprint: str,
) -> str | None:
    """返回已存在的 resource_id（幂等命中）；未命中返回 None。"""
    existing = await session.get(IdempotencyKey, key)
    if existing is None:
        return None
    if existing.resource_type != resource_type or existing.request_hash != fingerprint:
        raise ConflictError("Idempotency-Key 已用于不同的请求内容，请更换 key。")
    return existing.resource_id


async def record_idempotency(
    session: AsyncSession,
    key: str,
    resource_type: str,
    resource_id: str,
    fingerprint: str,
    status_code: int = 201,
) -> None:
    session.add(
        IdempotencyKey(
            key=key,
            resource_type=resource_type,
            resource_id=resource_id,
            request_hash=fingerprint,
            status_code=status_code,
        )
    )
