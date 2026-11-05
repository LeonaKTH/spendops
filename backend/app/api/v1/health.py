from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict[str, object]:
    settings = get_settings()

    db_ok = False
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    redis_ok = False
    # 本地 Windows 版 Redis 5.x 不支持 RESP3，显式使用协议 2。
    redis = Redis.from_url(settings.redis_url, protocol=2)
    try:
        redis_ok = bool(await redis.ping())
    except Exception:
        redis_ok = False
    finally:
        await redis.aclose()

    return {
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
        "redis": redis_ok,
    }
