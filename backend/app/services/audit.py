from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import AuthUser
from app.db.models import AuditLog
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

AUTH_LOGIN = "auth.login"
AUTH_LOGOUT = "auth.logout"
AUTH_PASSWORD_CHANGE = "auth.password.change"
USER_CREATE = "user.create"
USER_UPDATE = "user.update"
USER_RESET_PASSWORD = "user.password.reset"
USER_DELETE = "user.delete"
DATASET_UPLOAD = "dataset.upload"
DATASET_DELETE = "dataset.delete"
DOCUMENT_UPLOAD = "document.upload"
DOCUMENT_DELETE = "document.delete"
REPORT_EXPORT = "report.export"
REPORT_SHARE_CREATE = "report.share.create"
REPORT_SHARE_REVOKE = "report.share.revoke"
REPORT_VIEW_CREATE = "report.view.create"
REPORT_VIEW_DELETE = "report.view.delete"
INVOICE_VERIFY = "invoice.verify"


def _jsonable(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


async def log_action(
    session: AsyncSession,
    *,
    actor: AuthUser | None,
    action: str,
    actor_username: str = "",
    target_type: str | None = None,
    target_id: str | None = None,
    status: str = "success",
    detail: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_id=actor.id if actor else None,
            actor_username=actor.username if actor else actor_username,
            action=action,
            target_type=target_type,
            target_id=target_id,
            status=status,
            detail=_jsonable(detail) if detail is not None else None,
            ip=ip,
        )
    )


async def log_action_standalone(**kwargs: Any) -> None:
    """用于登录失败等没有现成事务的场景；审计失败不影响主流程。"""
    try:
        async with SessionLocal() as session:
            async with session.begin():
                await log_action(session, **kwargs)
    except Exception:
        logger.warning("写入审计日志失败", exc_info=True)


def _apply_filters(
    statement: Select[Any],
    *,
    action: str | None,
    status: str | None,
    actor: str | None,
    start: datetime | None,
    end: datetime | None,
) -> Select[Any]:
    if action:
        statement = statement.where(AuditLog.action == action)
    if status:
        statement = statement.where(AuditLog.status == status)
    if actor:
        statement = statement.where(AuditLog.actor_username.ilike(f"%{actor}%"))
    if start:
        statement = statement.where(AuditLog.created_at >= start)
    if end:
        statement = statement.where(AuditLog.created_at <= end)
    return statement


async def list_audit_logs(
    session: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
    action: str | None = None,
    status: str | None = None,
    actor: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> tuple[list[AuditLog], int]:
    filters = {
        "action": action,
        "status": status,
        "actor": actor,
        "start": start,
        "end": end,
    }
    count_statement = _apply_filters(
        select(func.count()).select_from(AuditLog), **filters
    )
    total = int((await session.scalar(count_statement)) or 0)

    statement = _apply_filters(select(AuditLog), **filters)
    statement = (
        statement.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list((await session.execute(statement)).scalars().all())
    return rows, total
