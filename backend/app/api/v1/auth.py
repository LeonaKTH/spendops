from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.v1.schemas import ChangePasswordIn, LoginIn, UserOut
from app.core.security import (
    DUMMY_HASH,
    AuthUser,
    clear_auth_cookie,
    client_ip,
    create_access_token,
    get_current_user,
    get_current_user_optional,
    set_auth_cookie,
    to_auth_user,
    verify_password,
)
from app.db.models import User
from app.db.session import SessionLocal
from app.infra.rate_limit import (
    check_login_locked,
    clear_login_failures,
    record_login_failure,
)
from app.services.audit import (
    AUTH_LOGIN,
    AUTH_LOGOUT,
    AUTH_PASSWORD_CHANGE,
    log_action,
    log_action_standalone,
)
from app.services.users import (
    change_password as change_password_service,
)
from app.services.users import (
    get_user_by_username,
    normalize_username,
)

router = APIRouter(tags=["auth"])


def _to_out(user: User | AuthUser) -> UserOut:
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


@router.post("/auth/login", response_model=UserOut)
async def login(payload: LoginIn, request: Request, response: Response) -> UserOut:
    username = normalize_username(payload.username)
    ip = client_ip(request)

    retry_after = await check_login_locked(username, ip)
    if retry_after > 0:
        raise HTTPException(
            status_code=429,
            detail=f"登录失败次数过多，请 {retry_after} 秒后再试。",
            headers={"Retry-After": str(retry_after)},
        )

    token = ""
    user = None
    async with SessionLocal() as session:
        async with session.begin():
            user = await get_user_by_username(session, username)
            if user is None:
                # 未知用户也执行一次 bcrypt，降低用户名枚举的时序差异。
                verify_password(payload.password, DUMMY_HASH)
            else:
                password_ok = verify_password(payload.password, user.password_hash)
                if user.is_active and password_ok:
                    user.last_login_at = datetime.now(UTC)
                    actor = to_auth_user(user)
                    await log_action(session, actor=actor, action=AUTH_LOGIN, ip=ip)
                    token = create_access_token(user)

    if not user or not token:
        await record_login_failure(username, ip)
        await log_action_standalone(
            actor=None,
            actor_username=username,
            action=AUTH_LOGIN,
            status="failure",
            detail={"reason": "invalid_credentials"},
            ip=ip,
        )
        raise HTTPException(status_code=401, detail="用户名或密码错误。")

    await clear_login_failures(username, ip)
    set_auth_cookie(response, token)
    return _to_out(user)


@router.post("/auth/logout", status_code=204)
async def logout(request: Request, response: Response) -> None:
    current = await get_current_user_optional(request)
    clear_auth_cookie(response)
    if current is not None:
        await log_action_standalone(actor=current, action=AUTH_LOGOUT, ip=client_ip(request))


@router.get("/auth/me", response_model=UserOut)
async def me(current: AuthUser = Depends(get_current_user)) -> UserOut:
    return _to_out(current)


@router.post("/auth/change-password", status_code=204)
async def change_password(
    payload: ChangePasswordIn,
    request: Request,
    response: Response,
    current: AuthUser = Depends(get_current_user),
) -> None:
    async with SessionLocal() as session:
        async with session.begin():
            user = await session.get(User, current.id)
            if user is None:
                raise HTTPException(status_code=401, detail="账号不存在或已被停用。")
            try:
                await change_password_service(
                    session,
                    user,
                    current_password=payload.current_password,
                    new_password=payload.new_password,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            await log_action(
                session,
                actor=current,
                action=AUTH_PASSWORD_CHANGE,
                ip=client_ip(request),
            )
            token = create_access_token(user)

    # 改密后递增 token_version，旧会话失效；当前会话重新签发 cookie 保持登录。
    set_auth_cookie(response, token)
