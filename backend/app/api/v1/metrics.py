"""SpendOps G3 采购经营指标 API。所有查询经认证 + 真实 PostgreSQL 聚合。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import AuthUser, get_current_user
from app.db.session import SessionLocal
from app.services import metrics

router = APIRouter(tags=["metrics"])


def _json(value):
    """把 Decimal 转字符串、date 转 ISO，保证金额精度不丢失。"""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json(v) for v in value]
    return value


def _range(start: date, end: date) -> tuple[date, date]:
    if start > end:
        raise HTTPException(status_code=400, detail="开始日期不能晚于结束日期。")
    # 保护：不合理的大时间跨度（> 5 年）拒绝，避免超量聚合。
    if (end - start).days > 365 * 5:
        raise HTTPException(status_code=400, detail="时间跨度过大，请缩小到 5 年以内。")
    return start, end


@router.get("/metrics/overview")
async def overview(
    start: date,
    end: date,
    supplier_id: str | None = Query(default=None),
    order_status: str | None = Query(default=None),
    _user: AuthUser = Depends(get_current_user),
) -> dict:
    start, end = _range(start, end)
    async with SessionLocal() as session:
        return _json(await metrics.overview(session, start, end, supplier_id, order_status))


@router.get("/metrics/suppliers")
async def supplier_ranking(
    start: date,
    end: date,
    top_n: int = Query(default=10, ge=1, le=100),
    _user: AuthUser = Depends(get_current_user),
) -> dict:
    start, end = _range(start, end)
    async with SessionLocal() as session:
        return _json(await metrics.supplier_ranking(session, start, end, top_n))


@router.get("/metrics/trend")
async def monthly_trend(
    start: date,
    end: date,
    supplier_id: str | None = Query(default=None),
    _user: AuthUser = Depends(get_current_user),
) -> dict:
    start, end = _range(start, end)
    async with SessionLocal() as session:
        return _json(await metrics.monthly_trend(session, start, end, supplier_id))


@router.get("/metrics/delivery")
async def delivery_performance(
    start: date,
    end: date,
    supplier_id: str | None = Query(default=None),
    _user: AuthUser = Depends(get_current_user),
) -> dict:
    start, end = _range(start, end)
    async with SessionLocal() as session:
        return _json(await metrics.delivery_performance(session, start, end, supplier_id))


@router.get("/metrics/categories")
async def category_breakdown(
    start: date,
    end: date,
    _user: AuthUser = Depends(get_current_user),
) -> dict:
    start, end = _range(start, end)
    async with SessionLocal() as session:
        return _json(await metrics.category_breakdown(session, start, end))


@router.get("/metrics/discrepancies")
async def discrepancies(
    start: date,
    end: date,
    _user: AuthUser = Depends(get_current_user),
) -> dict:
    start, end = _range(start, end)
    async with SessionLocal() as session:
        rows = await metrics.discrepancies(session, start, end)
    return _json({"items": rows, "total": len(rows)})
