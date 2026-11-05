"""真实 PostgreSQL 集成测试 fixtures。

隔离策略：每个测试开始时 TRUNCATE 采购表（CASCADE 级联清空），测试结束回滚。
所有 async 测试共享 session 级 event loop（pytest.ini 配置），engine 为 session scope，
连接池绑定同一 loop，避免连接跨 event loop 使用（MissingGreenlet 根因）。

安全护栏：
- 测试连接只来自环境变量 SPENDOPS_TEST_DATABASE_URL 或 .env 的 TEST_DATABASE_URL；
  未配置时测试直接失败，绝不回落到演示库。
- 破坏性清理（TRUNCATE）前强制校验数据库名必须以 `_test` 结尾，防止误清演示库/其他库。
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


def _resolve_test_url() -> str:
    explicit = os.environ.get("SPENDOPS_TEST_DATABASE_URL")
    if explicit:
        return explicit
    configured = get_settings().test_database_url
    if configured:
        return configured
    raise RuntimeError(
        "未配置测试数据库连接。请设置 SPENDOPS_TEST_DATABASE_URL 或 .env 的 "
        "TEST_DATABASE_URL（必须指向以 _test 结尾的独立测试库）。"
    )


TEST_DATABASE_URL = _resolve_test_url()


def _assert_test_database(url: str) -> None:
    """破坏性清理的安全护栏：数据库名必须以 _test 结尾。"""
    try:
        db_name = urlparse(url).path.lstrip("/")
    except Exception as exc:  # pragma: no cover - 解析异常直接失败
        raise RuntimeError(f"无法解析测试数据库 URL：{exc}") from exc
    if not db_name.endswith("_test"):
        raise RuntimeError(
            f"拒绝在非测试库上运行集成测试（数据库名 {db_name!r} 必须以 _test 结尾）。"
            "这防止 TRUNCATE 误清演示库或其他项目数据库。"
        )


_assert_test_database(TEST_DATABASE_URL)

_PURCHASING_TABLES = (
    "suppliers, purchase_orders, purchase_order_lines, goods_receipts, "
    "goods_receipt_lines, purchase_invoices, purchase_invoice_lines, "
    "import_tasks, import_staging_rows"
)


@pytest_asyncio.fixture(scope="session")
async def engine():
    eng = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncSession:
    """每个测试一个干净会话，开始前清空采购表。"""
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    session = session_factory()
    await session.execute(text(f"TRUNCATE TABLE {_PURCHASING_TABLES} CASCADE"))
    await session.commit()
    try:
        yield session
    finally:
        await session.rollback()
        await session.close()
