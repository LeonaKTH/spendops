"""报表只读分享链接。

数据库只保存 token 的 SHA-256 摘要，链接本身只在创建时返回一次；
分享可以绑定数据集与账期，并支持有效期与主动撤销。
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import AuthUser
from app.db.models import ReportShare

SHARE_EXPIRE_DAYS = (7, 30, 90)


class SharePermissionError(PermissionError):
    """当前用户无权撤销该分享。"""


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_active(share: ReportShare, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    if share.revoked_at is not None:
        return False
    expires_at = share.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at > now


async def create_share(
    session: AsyncSession,
    *,
    dataset_id: str,
    dataset_name: str,
    period_start: date | None,
    period_end: date | None,
    actor: AuthUser,
    expires_in_days: int = 30,
    provider: str | None = None,
) -> tuple[ReportShare, str]:
    token = generate_token()
    share = ReportShare(
        token_hash=hash_token(token),
        dataset_id=uuid.UUID(dataset_id),
        dataset_name=dataset_name,
        period_start=period_start,
        period_end=period_end,
        provider=provider or None,
        created_by=actor.id,
        created_by_username=actor.username,
        expires_at=datetime.now(UTC) + timedelta(days=expires_in_days),
    )
    session.add(share)
    await session.flush()
    return share, token


async def resolve_share(
    session: AsyncSession, token: str, *, touch: bool = False
) -> ReportShare | None:
    if not token or len(token) > 200:
        return None
    share = await session.scalar(
        select(ReportShare).where(ReportShare.token_hash == hash_token(token))
    )
    if share is None or not is_active(share):
        return None
    if touch:
        share.view_count = (share.view_count or 0) + 1
        share.last_viewed_at = datetime.now(UTC)
        await session.commit()
    return share


def _visible_filter(statement: Select, actor: AuthUser) -> Select:
    if actor.role == "admin":
        return statement
    return statement.where(ReportShare.created_by == actor.id)


async def list_shares(
    session: AsyncSession,
    *,
    actor: AuthUser,
    dataset_id: str | None = None,
    include_inactive: bool = False,
) -> list[ReportShare]:
    statement = _visible_filter(select(ReportShare), actor)
    if dataset_id:
        statement = statement.where(ReportShare.dataset_id == uuid.UUID(dataset_id))
    if not include_inactive:
        statement = statement.where(
            ReportShare.revoked_at.is_(None),
            ReportShare.expires_at > datetime.now(UTC),
        )
    statement = statement.order_by(ReportShare.created_at.desc()).limit(100)
    return list((await session.execute(statement)).scalars().all())


async def revoke_share(
    session: AsyncSession, share_id: str, *, actor: AuthUser
) -> ReportShare | None:
    try:
        key = uuid.UUID(share_id)
    except ValueError:
        return None

    share = await session.get(ReportShare, key)
    if share is None:
        return None
    if actor.role != "admin" and share.created_by != actor.id:
        raise SharePermissionError("只能撤销自己创建的分享链接。")
    if share.revoked_at is None:
        share.revoked_at = datetime.now(UTC)
        await session.flush()
    return share
