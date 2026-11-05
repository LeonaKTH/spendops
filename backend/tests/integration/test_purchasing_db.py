"""真实 PostgreSQL 集成测试：迁移结构、约束、事务、只读角色。

这些测试连接真实数据库（spendops_test），验证：
1. 采购表结构与约束真实存在（非 mock）。
2. 唯一约束、外键约束、检查约束真实生效。
3. 事务提交与回滚行为正确。
4. 只读角色真实权限（能读不能写）。

这些是 G1 第一道硬门槛的自动化证据。
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.models import Supplier

TEST_DB_NAME = "spendops_test"


@pytest.mark.asyncio
async def test_purchasing_tables_exist(engine):
    """迁移后采购表真实存在。"""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                "AND tablename IN ('suppliers','purchase_orders','purchase_order_lines',"
                "'goods_receipts','goods_receipt_lines','purchase_invoices','purchase_invoice_lines')"
            )
        )
        tables = {row[0] for row in result.all()}
    expected = {
        "suppliers",
        "purchase_orders",
        "purchase_order_lines",
        "goods_receipts",
        "goods_receipt_lines",
        "purchase_invoices",
        "purchase_invoice_lines",
    }
    assert tables == expected


@pytest.mark.asyncio
async def test_supplier_unique_code_constraint(db_session):
    """唯一约束：重复供应商编码被数据库拒绝。"""
    db_session.add(Supplier(code="S001", name="供应商甲"))
    await db_session.flush()

    db_session.add(Supplier(code="S001", name="供应商乙"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_supplier_status_check_constraint(db_session):
    """检查约束：非法状态被数据库拒绝。"""
    db_session.add(Supplier(code="S002", name="供应商", status="unknown"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_foreign_key_constraint(db_session):
    """外键约束：引用不存在的供应商被拒绝。"""
    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO purchase_orders (id, order_no, supplier_id, order_date, status) "
                "VALUES (gen_random_uuid(), 'PO-X', gen_random_uuid(), '2026-01-01', 'draft')"
            )
        )
    await db_session.rollback()


@pytest.mark.asyncio
async def test_transaction_rollback(db_session):
    """事务回滚：flush 后未 commit 的回滚使数据不可见。"""
    db_session.add(Supplier(code="S003", name="回滚测试"))
    await db_session.flush()
    await db_session.rollback()

    result = await db_session.execute(text("SELECT count(*) FROM suppliers WHERE code='S003'"))
    assert result.scalar() == 0


@pytest.mark.asyncio
async def test_readonly_role_cannot_write():
    """只读角色：真实 PG 角色能读不能写（应用层 SQL 守卫的数据库层兜底）。"""
    import asyncpg

    from app.core.config import get_settings

    ro_url = get_settings().ro_database_url
    if not ro_url:
        pytest.skip("未配置 RO_DATABASE_URL，跳过只读角色权限测试。")

    # asyncpg.connect 不接受 SQLAlchemy 的 +asyncpg 后缀。
    ro_url = ro_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(ro_url)
    try:
        # 能读
        count = await conn.fetchval("SELECT count(*) FROM suppliers")
        assert count is not None
        # 不能写
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute("INSERT INTO suppliers (code, name) VALUES ('RO-X', '越权')")
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_decimal_amount_column_type(engine):
    """金额列是 numeric(18,2)，不是 float。"""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT data_type, numeric_precision, numeric_scale "
                "FROM information_schema.columns "
                "WHERE table_name='purchase_order_lines' AND column_name='amount'"
            )
        )
        row = result.one()
    assert row[0] == "numeric"
    assert row[1] == 18
    assert row[2] == 2
