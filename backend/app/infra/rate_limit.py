"""登录失败限流。

Redis 不可用时的行为：
- 本地开发（APP_ENV=dev）：fail-open，只记录警告，登录流程继续可用。
- 其他环境：fail-closed，Redis 不可用是硬错误（抛异常），不允许限流静默失效。
  生产环境必须保证 Redis 可用，否则登录限流形同虚设。
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings
from app.infra.cache import get_redis

logger = logging.getLogger(__name__)

_warned = False


def _fail_open_allowed() -> bool:
    """只有本地开发环境允许 Redis 不可用时 fail-open。"""
    return get_settings().app_env == "dev"


def _warn_once() -> None:
    global _warned
    if not _warned:
        _warned = True
        logger.warning("Redis 不可用，登录失败限流已临时关闭。")


def _pair_key(username: str, ip: str) -> str:
    return f"procurebi:auth:fail:{username}:{ip}"


def _ip_key(ip: str) -> str:
    return f"procurebi:auth:fail:ip:{ip}"


async def _incr_with_ttl(redis: Any, key: str, ttl: int) -> int:
    count = int(await redis.incr(key))
    if count == 1:
        await redis.expire(key, ttl)
    return count


async def _ttl(redis: Any, key: str, default: int) -> int:
    value = int(await redis.ttl(key))
    if value < 0:
        return max(1, default)
    return max(1, value)


async def check_login_locked(
    username: str, ip: str, redis: Any | None = None
) -> int:
    """返回 0 表示可以继续登录；大于 0 表示需要等待的秒数。"""
    settings = get_settings()
    try:
        client = redis or get_redis()
        pair_count = int(await client.get(_pair_key(username, ip)) or 0)
        ip_count = int(await client.get(_ip_key(ip)) or 0)
        if pair_count < settings.login_max_attempts and ip_count < settings.login_ip_max_attempts:
            return 0
        pair_ttl = await _ttl(client, _pair_key(username, ip), settings.login_lockout_seconds)
        ip_ttl = await _ttl(client, _ip_key(ip), settings.login_lockout_seconds)
        return max(pair_ttl, ip_ttl)
    except Exception:
        if _fail_open_allowed():
            _warn_once()
            return 0
        raise


async def record_login_failure(
    username: str, ip: str, redis: Any | None = None
) -> tuple[int, int]:
    settings = get_settings()
    try:
        client = redis or get_redis()
        pair_count = await _incr_with_ttl(
            client, _pair_key(username, ip), settings.login_lockout_seconds
        )
        ip_count = await _incr_with_ttl(
            client, _ip_key(ip), settings.login_lockout_seconds
        )
        return pair_count, ip_count
    except Exception:
        if _fail_open_allowed():
            _warn_once()
            return 0, 0
        raise


async def clear_login_failures(
    username: str, ip: str, redis: Any | None = None
) -> None:
    """登录成功后清掉该 (用户名, IP) 的计数，IP 维度自然过期。"""
    try:
        client = redis or get_redis()
        await client.delete(_pair_key(username, ip))
    except Exception:
        if _fail_open_allowed():
            _warn_once()
            return
        raise


def _share_key(scope: str, value: str) -> str:
    return f"procurebi:share:{scope}:{value}"


async def hit_share_limit(
    *, token: str, ip: str, redis: Any | None = None
) -> int:
    """公开分享端点限流；返回 0 表示放行，大于 0 为建议的 Retry-After 秒数。

    同时按 IP 与 token 计数：单个链接被爬取和单个 IP 扫多个链接都会受限。
    Redis 不可用时 fail-open。
    """
    settings = get_settings()
    window = max(1, settings.share_rate_window_seconds)
    limit = max(1, settings.share_rate_max_requests)
    token_key = _share_key("token", token[-24:] if token else "none")
    ip_key = _share_key("ip", ip or "unknown")
    try:
        client = redis or get_redis()
        for key in (ip_key, token_key):
            count = await _incr_with_ttl(client, key, window)
            if count > limit:
                return await _ttl(client, key, window)
        return 0
    except Exception:
        if _fail_open_allowed():
            _warn_once()
            return 0
        raise
