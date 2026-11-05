from __future__ import annotations

import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, validate_password, verify_password
from app.db.models import User

USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,32}$")
ROLES = {"admin", "viewer"}


def normalize_username(value: str) -> str:
    return (value or "").strip().lower()


def validate_username(value: str) -> str:
    normalized = normalize_username(value)
    if not USERNAME_RE.fullmatch(normalized):
        raise ValueError("用户名需为 3-32 位字母、数字、下划线、点或短横线。")
    return normalized


def validate_role(value: str) -> str:
    if value not in ROLES:
        raise ValueError("角色只能是 admin 或 viewer。")
    return value


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    normalized = normalize_username(username)
    statement = select(User).where(func.lower(User.username) == normalized)
    return (await session.execute(statement)).scalar_one_or_none()


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


def _user_filters(
    statement,
    *,
    q: str | None,
    role: str | None,
    is_active: bool | None,
):
    if q:
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            User.username.ilike(pattern) | User.display_name.ilike(pattern)
        )
    if role:
        statement = statement.where(User.role == role)
    if is_active is not None:
        statement = statement.where(User.is_active.is_(is_active))
    return statement


async def list_users(
    session: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
) -> tuple[list[User], int]:
    filters = {"q": q, "role": role, "is_active": is_active}
    count_statement = _user_filters(select(func.count()).select_from(User), **filters)
    total = int((await session.scalar(count_statement)) or 0)

    statement = _user_filters(select(User), **filters)
    statement = (
        statement.order_by(User.created_at.desc(), User.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list((await session.execute(statement)).scalars().all())
    return rows, total


async def create_user(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    role: str = "viewer",
    display_name: str = "",
) -> User:
    normalized = validate_username(username)
    validate_role(role)
    validate_password(password)
    user = User(
        username=normalized,
        display_name=(display_name or "").strip()[:100],
        password_hash=hash_password(password),
        role=role,
        is_active=True,
        token_version=1,
        must_change_password=True,
    )
    session.add(user)
    await session.flush()
    return user


async def update_user(
    session: AsyncSession,
    user: User,
    *,
    display_name: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
) -> User:
    if display_name is not None:
        user.display_name = display_name.strip()[:100]
    if role is not None:
        user.role = validate_role(role)
    if is_active is not None and user.is_active != is_active:
        user.is_active = is_active
        if not is_active:
            # 停用后立即使旧 cookie 失效。
            user.token_version += 1
    await session.flush()
    return user


async def reset_password(session: AsyncSession, user: User, new_password: str) -> None:
    validate_password(new_password)
    user.password_hash = hash_password(new_password)
    user.token_version += 1
    user.must_change_password = True
    await session.flush()


async def change_password(
    session: AsyncSession,
    user: User,
    *,
    current_password: str,
    new_password: str,
) -> None:
    if not verify_password(current_password, user.password_hash):
        raise ValueError("当前密码不正确。")
    if verify_password(new_password, user.password_hash):
        raise ValueError("新密码不能与当前密码相同。")
    validate_password(new_password)
    user.password_hash = hash_password(new_password)
    user.token_version += 1
    user.must_change_password = False
    await session.flush()


async def delete_user(session: AsyncSession, user: User) -> None:
    await session.delete(user)
    await session.flush()


async def count_active_admins(session: AsyncSession, *, lock: bool = True) -> int:
    statement = select(User.id).where(User.role == "admin", User.is_active.is_(True))
    if lock:
        statement = statement.with_for_update()
    return len((await session.execute(statement)).scalars().all())


def ensure_can_change_admin(
    *,
    is_self: bool,
    action: str,
    target_is_active_admin: bool,
    active_admin_count: int,
) -> None:
    """action: delete / disable / demote。"""
    if is_self and action in {"delete", "disable", "demote"}:
        messages = {
            "delete": "不能删除当前登录的账号。",
            "disable": "不能停用当前登录的管理员账号。",
            "demote": "不能降级当前登录的管理员账号。",
        }
        raise ValueError(messages[action])
    if action in {"delete", "disable", "demote"} and target_is_active_admin:
        if active_admin_count <= 1:
            raise ValueError("系统至少需要保留一个启用状态的管理员。")
