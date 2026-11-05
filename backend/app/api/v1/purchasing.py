"""SpendOps 采购业务 API 路由。

权限约定：
- 读操作（GET）：登录用户（admin / viewer）均可。
- 写操作（POST / PATCH / DELETE）：仅 admin。

业务异常（BusinessError 家族）统一在此转换为 HTTP 响应。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.purchasing_schemas import (
    GoodsReceiptCreate,
    GoodsReceiptOut,
    InvoiceLineOut,
    OrderLineOut,
    PurchaseInvoiceCreate,
    PurchaseInvoiceOut,
    PurchaseOrderCreate,
    PurchaseOrderOut,
    PurchaseOrderStatusUpdate,
    ReceiptLineOut,
    SupplierCreate,
    SupplierOut,
    SupplierUpdate,
)
from app.core.security import AuthUser, client_ip, get_current_user, require_admin
from app.db.session import SessionLocal, get_db
from app.services import audit
from app.services.purchasing import invoices, orders, receipts, suppliers
from app.services.purchasing.domain import BusinessError
from app.services.purchasing.idempotency import (
    record_idempotency,
    request_fingerprint,
    resolve_idempotency,
)

router = APIRouter(tags=["purchasing"], prefix="/api/v1")


def _raise_http(exc: Exception) -> None:
    if isinstance(exc, BusinessError):
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    raise HTTPException(status_code=500, detail=f"数据库操作失败：{exc}")


# ---------- 供应商 ----------


def _supplier_out(s) -> SupplierOut:
    return SupplierOut(
        id=str(s.id),
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


@router.get("/suppliers", response_model=list[SupplierOut])
async def list_suppliers(
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _current: AuthUser = Depends(get_current_user),
) -> list[SupplierOut]:
    rows = await suppliers.list_suppliers(db, status)
    return [_supplier_out(s) for s in rows]


@router.post("/suppliers", response_model=SupplierOut, status_code=201)
async def create_supplier(
    body: SupplierCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _admin: AuthUser = Depends(require_admin),
) -> SupplierOut:
    try:
        async with SessionLocal() as session:
            async with session.begin():
                payload = body.model_dump()
                fingerprint = request_fingerprint(payload) if idempotency_key else None
                if idempotency_key:
                    existing_id = await resolve_idempotency(
                        session, idempotency_key, "supplier", fingerprint or ""
                    )
                    if existing_id:
                        existing = await suppliers.get_supplier(session, existing_id)
                        return _supplier_out(existing)
                data = await suppliers.create_supplier(
                    session,
                    code=body.code,
                    name=body.name,
                    contact_name=body.contact_name,
                    contact_phone=body.contact_phone,
                    email=body.email,
                    address=body.address,
                    remark=body.remark,
                )
                if idempotency_key:
                    await record_idempotency(
                        session, idempotency_key, "supplier", str(data.id), fingerprint or ""
                    )
                return _supplier_out(data)
    except Exception as exc:
        _raise_http(exc)


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut)
async def update_supplier(
    supplier_id: str,
    body: SupplierUpdate,
    _admin: AuthUser = Depends(require_admin),
) -> SupplierOut:
    try:
        async with SessionLocal() as session:
            async with session.begin():
                data = await suppliers.update_supplier(
                    session,
                    supplier_id,
                    name=body.name,
                    contact_name=body.contact_name,
                    contact_phone=body.contact_phone,
                    email=body.email,
                    address=body.address,
                    status=body.status,
                    remark=body.remark,
                )
                return _supplier_out(data)
    except Exception as exc:
        _raise_http(exc)


# ---------- 采购订单 ----------


def _order_out(o) -> PurchaseOrderOut:
    return PurchaseOrderOut(
        id=str(o.id),
        order_no=o.order_no,
        supplier_id=str(o.supplier_id),
        supplier_name=o.supplier_name,
        order_date=o.order_date,
        status=o.status,
        currency=o.currency,
        total_amount=o.total_amount,
        remark=o.remark,
        lines=[
            OrderLineOut(
                id=str(line.id),
                line_no=line.line_no,
                item_code=line.item_code,
                item_name=line.item_name,
                quantity=line.quantity,
                unit=line.unit,
                unit_price=line.unit_price,
                tax_rate=line.tax_rate,
                amount=line.amount,
                received_qty=line.received_qty,
                invoiced_qty=line.invoiced_qty,
            )
            for line in o.lines
        ],
        created_at=o.created_at,
        updated_at=o.updated_at,
    )


@router.get("/purchase-orders")
async def list_orders(
    status: str | None = Query(default=None),
    supplier_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _current: AuthUser = Depends(get_current_user),
) -> dict:
    rows, total = await orders.list_orders(db, status, supplier_id, limit, offset)
    return {"items": [_order_out(o) for o in rows], "total": total}


@router.get("/purchase-orders/{order_id}", response_model=PurchaseOrderOut)
async def get_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    _current: AuthUser = Depends(get_current_user),
) -> PurchaseOrderOut:
    try:
        data = await orders.get_order(db, order_id)
        return _order_out(data)
    except Exception as exc:
        _raise_http(exc)


@router.post("/purchase-orders", response_model=PurchaseOrderOut, status_code=201)
async def create_order(
    body: PurchaseOrderCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _admin: AuthUser = Depends(require_admin),
) -> PurchaseOrderOut:
    try:
        async with SessionLocal() as session:
            async with session.begin():
                payload = body.model_dump()
                fingerprint = request_fingerprint(payload) if idempotency_key else None
                if idempotency_key:
                    existing_id = await resolve_idempotency(
                        session, idempotency_key, "purchase_order", fingerprint or ""
                    )
                    if existing_id:
                        existing = await orders.get_order(session, existing_id)
                        return _order_out(existing)
                data = await orders.create_order(
                    session,
                    order_no=body.order_no,
                    supplier_id=body.supplier_id,
                    order_date=body.order_date,
                    lines=[line.model_dump() for line in body.lines],
                    remark=body.remark,
                )
                if idempotency_key:
                    await record_idempotency(
                        session, idempotency_key, "purchase_order", str(data.id), fingerprint or ""
                    )
                return _order_out(data)
    except Exception as exc:
        _raise_http(exc)


@router.patch("/purchase-orders/{order_id}/status", response_model=PurchaseOrderOut)
async def update_order_status(
    order_id: str,
    body: PurchaseOrderStatusUpdate,
    _admin: AuthUser = Depends(require_admin),
) -> PurchaseOrderOut:
    try:
        async with SessionLocal() as session:
            async with session.begin():
                if body.status == "cancelled":
                    data = await orders.cancel_order(session, order_id)
                else:
                    raise HTTPException(status_code=400, detail="不支持该状态变更。")
                return _order_out(data)
    except Exception as exc:
        _raise_http(exc)


# ---------- 收货 ----------


def _receipt_out(r) -> GoodsReceiptOut:
    return GoodsReceiptOut(
        id=str(r.id),
        receipt_no=r.receipt_no,
        order_id=str(r.order_id),
        order_no=r.order_no,
        supplier_id=str(r.supplier_id),
        supplier_name=r.supplier_name,
        receipt_date=r.receipt_date,
        status=r.status,
        total_quantity=r.total_quantity,
        total_amount=r.total_amount,
        remark=r.remark,
        lines=[
            ReceiptLineOut(
                id=str(line.id),
                line_no=line.line_no,
                order_line_id=str(line.order_line_id),
                quantity=line.quantity,
                unit_price=line.unit_price,
                amount=line.amount,
            )
            for line in r.lines
        ],
        created_at=r.created_at,
    )


@router.get("/goods-receipts", response_model=list[GoodsReceiptOut])
async def list_receipts(
    order_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _current: AuthUser = Depends(get_current_user),
) -> list[GoodsReceiptOut]:
    rows = await receipts.list_receipts(db, order_id)
    return [_receipt_out(r) for r in rows]


@router.post("/goods-receipts", response_model=GoodsReceiptOut, status_code=201)
async def create_receipt(
    body: GoodsReceiptCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _admin: AuthUser = Depends(require_admin),
) -> GoodsReceiptOut:
    try:
        async with SessionLocal() as session:
            async with session.begin():
                payload = body.model_dump()
                fingerprint = request_fingerprint(payload) if idempotency_key else None
                if idempotency_key:
                    existing_id = await resolve_idempotency(
                        session, idempotency_key, "goods_receipt", fingerprint or ""
                    )
                    if existing_id:
                        existing = await receipts.get_receipt(session, existing_id)
                        return _receipt_out(existing)
                data = await receipts.create_receipt(
                    session,
                    receipt_no=body.receipt_no,
                    order_id=body.order_id,
                    receipt_date=body.receipt_date,
                    lines=[line.model_dump() for line in body.lines],
                    remark=body.remark,
                )
                if idempotency_key:
                    await record_idempotency(
                        session, idempotency_key, "goods_receipt", str(data.id), fingerprint or ""
                    )
                return _receipt_out(data)
    except Exception as exc:
        _raise_http(exc)


# ---------- 发票 ----------


def _invoice_out(i) -> PurchaseInvoiceOut:
    return PurchaseInvoiceOut(
        id=str(i.id),
        invoice_no=i.invoice_no,
        order_id=str(i.order_id) if i.order_id else None,
        order_no=i.order_no,
        supplier_id=str(i.supplier_id),
        supplier_name=i.supplier_name,
        invoice_date=i.invoice_date,
        status=i.status,
        currency=i.currency,
        total_amount=i.total_amount,
        tax_amount=i.tax_amount,
        remark=i.remark,
        lines=[
            InvoiceLineOut(
                id=str(line.id),
                line_no=line.line_no,
                order_line_id=str(line.order_line_id) if line.order_line_id else None,
                item_name=line.item_name,
                quantity=line.quantity,
                unit_price=line.unit_price,
                amount=line.amount,
            )
            for line in i.lines
        ],
        created_at=i.created_at,
    )


@router.get("/purchase-invoices", response_model=list[PurchaseInvoiceOut])
async def list_invoices(
    order_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _current: AuthUser = Depends(get_current_user),
) -> list[PurchaseInvoiceOut]:
    rows = await invoices.list_invoices(db, order_id)
    return [_invoice_out(i) for i in rows]


@router.post("/purchase-invoices", response_model=PurchaseInvoiceOut, status_code=201)
async def create_invoice(
    body: PurchaseInvoiceCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _admin: AuthUser = Depends(require_admin),
) -> PurchaseInvoiceOut:
    try:
        async with SessionLocal() as session:
            async with session.begin():
                payload = body.model_dump()
                fingerprint = request_fingerprint(payload) if idempotency_key else None
                if idempotency_key:
                    existing_id = await resolve_idempotency(
                        session, idempotency_key, "purchase_invoice", fingerprint or ""
                    )
                    if existing_id:
                        existing = await invoices.get_invoice(session, existing_id)
                        return _invoice_out(existing)
                data = await invoices.create_invoice(
                    session,
                    invoice_no=body.invoice_no,
                    order_id=body.order_id,
                    supplier_id=body.supplier_id,
                    invoice_date=body.invoice_date,
                    lines=[line.model_dump() for line in body.lines],
                    remark=body.remark,
                )
                if idempotency_key:
                    await record_idempotency(
                        session, idempotency_key, "purchase_invoice", str(data.id), fingerprint or ""
                    )
                return _invoice_out(data)
    except Exception as exc:
        _raise_http(exc)


@router.post("/purchase-invoices/{invoice_id}/verify", response_model=PurchaseInvoiceOut)
async def verify_invoice(
    invoice_id: str,
    request: Request,
    admin: AuthUser = Depends(require_admin),
) -> PurchaseInvoiceOut:
    """人工核对：把待核对发票标记为已核对（posted）。

    仅 admin；仅 pending_verification -> posted；已取消订单的发票不能核对。
    核对操作写入审计日志（actor / target / 来源 IP），可追溯。
    """
    try:
        async with SessionLocal() as session:
            async with session.begin():
                data = await invoices.verify_invoice(session, invoice_id)
                await audit.log_action(
                    session,
                    actor=admin,
                    action=audit.INVOICE_VERIFY,
                    target_type="purchase_invoice",
                    target_id=str(data.id),
                    status="success",
                    detail={"invoice_no": data.invoice_no, "from_status": "pending_verification"},
                    ip=client_ip(request),
                )
                return _invoice_out(data)
    except Exception as exc:
        _raise_http(exc)
