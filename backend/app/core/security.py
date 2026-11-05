from __future__ import annotations

import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import User
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

BCRYPT_MAX_BYTES = 72
ALGORITHM = "HS256"

# 未知用户也执行一次 bcrypt 校验，避免通过响应时间判断用户名是否存在。
DUMMY_HASH = "$2b$12$vz0TStE/UywH6cv1AUgqC.1V./9tiZ9k3ENIA8vW1X3jVXbHSVnzu"

_fallback_secret: str | None = None


class AuthError(Exception):
    """认证失败，由依赖层转换为 401。"""


@dataclass(frozen=True, slots=True)
class AuthUser:
    id: uuid.UUID
    username: str
    display_name: str
    role: str
    is_active: bool
    token_version: int
    must_change_password: bool
    last_login_at: datetime | None
    created_at: datetime


def validate_password(password: str) -> None:
    if not password or not password.strip():
        raise ValueError("密码不能为空白字符。")
    if len(password) < 8:
        raise ValueError("密码至少 8 个字符。")
    if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise ValueError("密码不能超过 72 字节（约 24 个中文字符）。")


def hash_password(password: str, rounds: int | None = None) -> str:
    validate_password(password)
    cost = rounds if rounds is not None else get_settings().bcrypt_rounds
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=cost)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
            return False
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def jwt_secret() -> str:
    global _fallback_secret

    configured = get_settings().jwt_secret.strip()
    if configured and configured != "change-me-to-a-long-random-string":
        return configured
    if _fallback_secret is None:
        _fallback_secret = secrets.token_urlsafe(48)
        logger.warning(
            "JWT_SECRET 未配置，已生成进程内临时密钥；服务重启后登录态会失效。"
            "请在 .env 中配置 JWT_SECRET。"
        )
    return _fallback_secret


def create_access_token(
    user: User | AuthUser,
    *,
    secret: str | None = None,
    now: datetime | None = None,
    expires_minutes: int | None = None,
) -> str:
    settings = get_settings()
    issued = now or datetime.now(UTC)
    minutes = expires_minutes if expires_minutes is not None else settings.jwt_expire_minutes
    payload = {
        "sub": str(user.id),
        "ver": user.token_version,
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(minutes=minutes)).timestamp()),
        "jti": secrets.token_urlsafe(12),
    }
    return jwt.encode(payload, secret or jwt_secret(), algorithm=ALGORITHM)


def decode_access_token(token: str, *, secret: str | None = None) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            secret or jwt_secret(),
            algorithms=[ALGORITHM],
            options={"require": ["exp", "sub", "ver"]},
            leeway=get_settings().jwt_leeway_seconds,
        )
    except jwt.PyJWTError as exc:
        raise AuthError("登录状态无效或已过期。") from exc


def set_auth_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.jwt_expire_minutes * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path="/",
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
    )


def to_auth_user(user: User) -> AuthUser:
    return AuthUser(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        is_active=user.is_active,
        token_version=user.token_version,
        must_change_password=user.must_change_password,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


async def resolve_user(session: AsyncSession, payload: dict[str, Any]) -> AuthUser:
    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise AuthError("登录状态无效或已过期。") from exc

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthError("账号不存在或已被停用。")
    if int(payload.get("ver", -1)) != user.token_version:
        raise AuthError("登录状态已失效，请重新登录。")
    return to_auth_user(user)


async def get_current_user(request: Request) -> AuthUser:
    token = request.cookies.get(get_settings().auth_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="未登录或登录已过期。")

    try:
        payload = decode_access_token(token)
        async with SessionLocal() as session:
            return await resolve_user(session, payload)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


async def get_current_user_optional(request: Request) -> AuthUser | None:
    try:
        return await get_current_user(request)
    except HTTPException:
        return None


async def require_admin(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限。")
    return user


def client_ip(request: Request) -> str:
    settings = get_settings()
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()[:64]
    host = request.client.host if request.client else ""
    return (host or "")[:64]
