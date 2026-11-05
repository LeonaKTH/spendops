from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas import (
    AdminOverviewOut,
    AdminUserCreateIn,
    AdminUserUpdateIn,
    AuditLogOut,
    PaginatedAuditLogsOut,
    PaginatedUsersOut,
    ResetPasswordIn,
    UserOut,
)
from app.core.security import AuthUser, client_ip, require_admin
from app.db.models import AuditLog, Dataset, Document, User
from app.db.session import SessionLocal, get_db
from app.services.audit import (
    USER_CREATE,
    USER_DELETE,
    USER_RESET_PASSWORD,
    USER_UPDATE,
    list_audit_logs,
    log_action,
)
from app.services.users import (
    count_active_admins,
    create_user,
    delete_user,
    ensure_can_change_admin,
    get_user,
    list_users,
    reset_password,
    update_user,
    validate_role,
)

router = APIRouter(tags=["admin"], dependencies=[Depends(require_admin)])


def _to_user_out(user: User) -> UserOut:
    return UserOut(
        id=str(user.id),
        username=user.username,
        display_name=user.display_name or user.username,
        role=user.role,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


def _to_audit_out(log: AuditLog) -> AuditLogOut:
    return AuditLogOut(
        id=str(log.id),
        actor_username=log.actor_username,
        action=log.action,
        target_type=log.target_type,
        target_id=log.target_id,
        status=log.status,
        detail=log.detail,
        ip=log.ip,
        created_at=log.created_at,
    )


def _parse_user_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="无效的用户 ID。") from exc


@router.get("/admin/overview", response_model=AdminOverviewOut)
async def overview(db: AsyncSession = Depends(get_db)) -> AdminOverviewOut:
    now = datetime.now(UTC)
    user_total = int((await db.scalar(select(func.count()).select_from(User))) or 0)
    active_users = int(
        (
            await db.scalar(
                select(func.count()).select_from(User).where(User.is_active.is_(True))
            )
        )
        or 0
    )
    admins = int(
        (
            await db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.role == "admin", User.is_active.is_(True))
            )
        )
        or 0
    )
    datasets = int((await db.scalar(select(func.count()).select_from(Dataset))) or 0)
    active_datasets = int(
        (
            await db.scalar(
                select(func.count())
                .select_from(Dataset)
                .where(Dataset.status == "active")
            )
        )
        or 0
    )
    documents = int((await db.scalar(select(func.count()).select_from(Document))) or 0)
    audit_events = int(
        (
            await db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.created_at >= now - timedelta(hours=24))
            )
        )
        or 0
    )
    recent = list(
        (
            await db.execute(
                select(AuditLog)
                .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    return AdminOverviewOut(
        users=user_total,
        active_users=active_users,
        admins=admins,
        datasets=datasets,
        active_datasets=active_datasets,
        documents=documents,
        audit_events_24h=audit_events,
        recent_audit=[_to_audit_out(item) for item in recent],
    )


@router.get("/admin/users", response_model=PaginatedUsersOut)
async def list_users_endpoint(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = Query(default=None, max_length=100),
    role: Literal["admin", "viewer"] | None = None,
    is_active: bool | None = None,
    db: AsyncSession = Depends(get_db),
) -> PaginatedUsersOut:
    rows, total = await list_users(
        db,
        page=page,
        page_size=page_size,
        q=q,
        role=role,
        is_active=is_active,
    )
    return PaginatedUsersOut(
        items=[_to_user_out(item) for item in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/admin/users", response_model=UserOut, status_code=201)
async def create_user_endpoint(
    payload: AdminUserCreateIn,
    request: Request,
    current: AuthUser = Depends(require_admin),
) -> UserOut:
    try:
        async with SessionLocal() as session:
            async with session.begin():
                user = await create_user(
                    session,
                    username=payload.username,
                    password=payload.password,
                    role=payload.role,
                    display_name=payload.display_name,
                )
                await log_action(
                    session,
                    actor=current,
                    action=USER_CREATE,
                    target_type="user",
                    target_id=str(user.id),
                    detail={"username": user.username, "role": user.role},
                    ip=client_ip(request),
                )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="用户名已存在。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_user_out(user)


@router.patch("/admin/users/{user_id}", response_model=UserOut)
async def update_user_endpoint(
    user_id: str,
    payload: AdminUserUpdateIn,
    request: Request,
    current: AuthUser = Depends(require_admin),
) -> UserOut:
    if payload.is_empty():
        raise HTTPException(status_code=400, detail="没有需要更新的字段。")

    target_id = _parse_user_id(user_id)
    async with SessionLocal() as session:
        async with session.begin():
            user = await get_user(session, target_id)
            if user is None:
                raise HTTPException(status_code=404, detail="用户不存在。")

            if payload.role is not None:
                try:
                    validate_role(payload.role)
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc

            action = ""
            if payload.is_active is False and user.is_active:
                action = "disable"
            if payload.role == "viewer" and user.role == "admin":
                action = "demote"

            active_admins = 0
            if action:
                active_admins = await count_active_admins(session)
            try:
                ensure_can_change_admin(
                    is_self=user.id == current.id,
                    action=action,
                    target_is_active_admin=user.role == "admin" and user.is_active,
                    active_admin_count=active_admins,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            changed = []
            if payload.display_name is not None:
                changed.append("display_name")
            if payload.role is not None and payload.role != user.role:
                changed.append("role")
            if payload.is_active is not None and payload.is_active != user.is_active:
                changed.append("is_active")

            await update_user(
                session,
                user,
                display_name=payload.display_name,
                role=payload.role,
                is_active=payload.is_active,
            )
            await log_action(
                session,
                actor=current,
                action=USER_UPDATE,
                target_type="user",
                target_id=str(user.id),
                detail={"username": user.username, "changed": changed},
                ip=client_ip(request),
            )
    return _to_user_out(user)


@router.post("/admin/users/{user_id}/reset-password", status_code=204)
async def reset_password_endpoint(
    user_id: str,
    payload: ResetPasswordIn,
    request: Request,
    current: AuthUser = Depends(require_admin),
) -> None:
    target_id = _parse_user_id(user_id)
    if target_id == current.id:
        raise HTTPException(status_code=400, detail="请使用「修改密码」修改自己的密码。")

    async with SessionLocal() as session:
        async with session.begin():
            user = await get_user(session, target_id)
            if user is None:
                raise HTTPException(status_code=404, detail="用户不存在。")
            try:
                await reset_password(session, user, payload.new_password)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            await log_action(
                session,
                actor=current,
                action=USER_RESET_PASSWORD,
                target_type="user",
                target_id=str(user.id),
                detail={"username": user.username},
                ip=client_ip(request),
            )


@router.delete("/admin/users/{user_id}", status_code=204)
async def delete_user_endpoint(
    user_id: str,
    request: Request,
    current: AuthUser = Depends(require_admin),
) -> None:
    target_id = _parse_user_id(user_id)
    if target_id == current.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录的账号。")

    async with SessionLocal() as session:
        async with session.begin():
            user = await get_user(session, target_id)
            if user is None:
                raise HTTPException(status_code=404, detail="用户不存在。")

            if user.role == "admin" and user.is_active:
                active_admins = await count_active_admins(session)
                if active_admins <= 1:
                    raise HTTPException(
                        status_code=409,
                        detail="系统至少需要保留一个启用状态的管理员。",
                    )

            username = user.username
            await log_action(
                session,
                actor=current,
                action=USER_DELETE,
                target_type="user",
                target_id=str(user.id),
                detail={"username": username},
                ip=client_ip(request),
            )
            await delete_user(session, user)


@router.get("/admin/audit-logs", response_model=PaginatedAuditLogsOut)
async def audit_logs_endpoint(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    action: str | None = Query(default=None, max_length=64),
    status: Literal["success", "failure"] | None = None,
    actor: str | None = Query(default=None, max_length=64),
    start: datetime | None = None,
    end: datetime | None = None,
    db: AsyncSession = Depends(get_db),
) -> PaginatedAuditLogsOut:
    rows, total = await list_audit_logs(
        db,
        page=page,
        page_size=page_size,
        action=action,
        status=status,
        actor=actor,
        start=start,
        end=end,
    )
    return PaginatedAuditLogsOut(
        items=[_to_audit_out(item) for item in rows],
        total=total,
        page=page,
        page_size=page_size,
    )
