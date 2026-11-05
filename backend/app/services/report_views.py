"""保存的报表视图。

复用 `reports` 表：一条记录只保存「数据集 + 期间 + 下钻条件」，
报表内容仍在打开时按当前数据实时计算，避免快照过期。
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import AuthUser
from app.db.models import Report
from app.services.datasets import DatasetMeta


class ReportViewPermissionError(PermissionError):
    """当前用户无权修改他人的报表视图。"""


async def create_view(
    session: AsyncSession,
    *,
    actor: AuthUser,
    title: str,
    dataset: DatasetMeta,
    start_date: date | None = None,
    end_date: date | None = None,
    provider: str | None = None,
) -> Report:
    view = Report(
        title=title.strip(),
        dataset_id=uuid.UUID(dataset.id),
        dataset_name=dataset.name,
        owner_id=actor.id,
        created_by_username=actor.username,
        period_start=start_date,
        period_end=end_date,
        provider=(provider or "").strip() or None,
    )
    session.add(view)
    await session.flush()
    return view


async def list_views(session: AsyncSession, *, actor: AuthUser) -> list[Report]:
    statement = select(Report).order_by(Report.updated_at.desc(), Report.created_at.desc())
    if actor.role != "admin":
        statement = statement.where(Report.owner_id == actor.id)
    return list((await session.execute(statement)).scalars().all())


async def delete_view(
    session: AsyncSession, view_id: str, *, actor: AuthUser
) -> Report | None:
    try:
        key = uuid.UUID(view_id)
    except ValueError as exc:
        raise ValueError("报表视图 ID 不合法。") from exc

    view = await session.get(Report, key)
    if view is None:
        return None
    if actor.role != "admin" and view.owner_id != actor.id:
        raise ReportViewPermissionError("只能删除自己保存的报表视图。")

    await session.delete(view)
    return view
