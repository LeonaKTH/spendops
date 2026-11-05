from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.security import hash_password, validate_password
from app.db.models import User
from app.db.session import SessionLocal
from app.services.users import validate_username

logger = logging.getLogger(__name__)

DEFAULT_DEV_PASSWORD = "admin123456"


async def seed_initial_admin() -> None:
    """仅在数据库中没有任何管理员时创建初始管理员。

    迁移文件里不写密码哈希；已有管理员永远不会被覆盖或重置。
    """
    settings = get_settings()
    if not settings.admin_bootstrap:
        return

    try:
        async with SessionLocal() as session:
            async with session.begin():
                admin_count = await session.scalar(
                    select(func.count()).select_from(User).where(User.role == "admin")
                )
                if admin_count:
                    return

                try:
                    username = validate_username(settings.admin_username or "admin")
                except ValueError as exc:
                    logger.error("ADMIN_USERNAME 不合法：%s", exc)
                    return

                password = settings.admin_password
                used_default = False
                if not password:
                    if settings.app_env != "dev":
                        logger.error(
                            "未配置 ADMIN_PASSWORD，已跳过管理员初始化。"
                            "请在部署环境显式设置 ADMIN_PASSWORD。"
                        )
                        return
                    password = DEFAULT_DEV_PASSWORD
                    used_default = True

                try:
                    validate_password(password)
                except ValueError as exc:
                    logger.error("ADMIN_PASSWORD 不合法：%s", exc)
                    return

                session.add(
                    User(
                        username=username,
                        display_name="系统管理员",
                        password_hash=hash_password(password),
                        role="admin",
                        is_active=True,
                        token_version=1,
                        must_change_password=True,
                    )
                )
                logger.warning(
                    "已创建初始管理员 %s%s。请登录后尽快修改密码。",
                    username,
                    "（使用开发环境默认密码）" if used_default else "",
                )
    except IntegrityError:
        logger.info("管理员已由其他进程创建，跳过初始化。")
    except Exception:
        logger.exception(
            "管理员初始化失败，请确认已执行 alembic upgrade head 且数据库可用。"
        )
