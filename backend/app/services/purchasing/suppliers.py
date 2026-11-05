"""供应商业务服务。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Supplier
from app.services.purchasing.domain import (
    SUPPLIER_BLOCKED,
    ConflictError,
    NotFoundError,
)


@dataclass
class SupplierData:
    id: uuid.UUID
    code: str
    name: str
    contact_name: str | None
    contact_phone: str | None
    email: str | None
    address: str | None
    status: str
    remark: str | None
    created_at: datetime
    updated_at: datetime


def _to_data(s: Supplier) -> SupplierData:
    return SupplierData(
        id=s.id,
        code=s.code,
        name=s.name,
        contact_name=s.contact_name,
        contact_phone=s.contact_phone,
        email=s.email,
        address=s.address,
        status=s.status,
        remark=s.remark,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


async def list_suppliers(
    session: AsyncSession, status: str | None = None
) -> list[SupplierData]:
    statement = select(Supplier).order_by(Supplier.code)
    if status:
        statement = statement.where(Supplier.status == status)
    rows = (await session.execute(statement)).scalars()
    return [_to_data(s) for s in rows]


async def get_supplier(session: AsyncSession, supplier_id: str) -> SupplierData:
    try:
        key = uuid.UUID(supplier_id)
    except ValueError as exc:
        raise NotFoundError("无效的供应商 ID。") from exc
    supplier = await session.get(Supplier, key)
    if supplier is None:
        raise NotFoundError("供应商不存在。")
    return _to_data(supplier)


async def create_supplier(
    session: AsyncSession,
    *,
    code: str,
    name: str,
    contact_name: str | None,
    contact_phone: str | None,
    email: str | None,
    address: str | None,
    remark: str | None,
) -> SupplierData:
    supplier = Supplier(
        code=code.strip(),
        name=name.strip(),
        contact_name=contact_name,
        contact_phone=contact_phone,
        email=email,
        address=address,
        remark=remark,
    )
    session.add(supplier)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError(f"供应商编码「{code}」已存在。") from exc
    return _to_data(supplier)


async def update_supplier(
    session: AsyncSession,
    supplier_id: str,
    *,
    name: str | None = None,
    contact_name: str | None = None,
    contact_phone: str | None = None,
    email: str | None = None,
    address: str | None = None,
    status: str | None = None,
    remark: str | None = None,
) -> SupplierData:
    try:
        key = uuid.UUID(supplier_id)
    except ValueError as exc:
        raise NotFoundError("无效的供应商 ID。") from exc
    supplier = await session.get(Supplier, key)
    if supplier is None:
        raise NotFoundError("供应商不存在。")

    if name is not None:
        supplier.name = name.strip()
    if contact_name is not None:
        supplier.contact_name = contact_name
    if contact_phone is not None:
        supplier.contact_phone = contact_phone
    if email is not None:
        supplier.email = email
    if address is not None:
        supplier.address = address
    if status is not None:
        if status == SUPPLIER_BLOCKED:
            # 已停用供应商不允许新增订单，由订单服务校验。
            pass
        supplier.status = status
    if remark is not None:
        supplier.remark = remark

    await session.flush()
    return _to_data(supplier)
