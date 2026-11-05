"""SpendOps 采购业务 Pydantic 模型（请求 / 响应）。

金额字段使用 Decimal 字符串序列化，避免 JSON 浮点精度丢失。
响应字段命名采用 camelCase（与前端的 TypeScript 类型对齐）。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------- 供应商 ----------

SupplierStatus = Literal["active", "inactive", "blocked"]


class SupplierCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=200)
    contact_name: str | None = None
    contact_phone: str | None = None
    email: str | None = None
    address: str | None = None
    remark: str | None = None


class SupplierUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=200)
    contact_name: str | None = None
    contact_phone: str | None = None
    email: str | None = None
    address: str | None = None
    status: SupplierStatus | None = None
    remark: str | None = None


class SupplierOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    code: str
    name: str
    contact_name: str | None = Field(default=None, serialization_alias="contactName")
    contact_phone: str | None = Field(default=None, serialization_alias="contactPhone")
    email: str | None = None
    address: str | None = None
    status: str
    remark: str | None = None
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


# ---------- 采购订单 ----------

OrderStatus = Literal["draft", "submitted", "partially_received", "received", "cancelled"]


class OrderLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_code: str = Field(min_length=1, max_length=64)
    item_name: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(gt=0)
    unit: str = Field(default="件", max_length=20)
    unit_price: Decimal = Field(ge=0)
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1)


class PurchaseOrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_no: str = Field(min_length=1, max_length=40)
    supplier_id: str
    order_date: date
    lines: list[OrderLineIn] = Field(min_length=1)
    remark: str | None = None


class OrderLineOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    line_no: int = Field(serialization_alias="lineNo")
    item_code: str = Field(serialization_alias="itemCode")
    item_name: str = Field(serialization_alias="itemName")
    quantity: Decimal
    unit: str
    unit_price: Decimal = Field(serialization_alias="unitPrice")
    tax_rate: Decimal = Field(serialization_alias="taxRate")
    amount: Decimal
    received_qty: Decimal = Field(serialization_alias="receivedQty")
    invoiced_qty: Decimal = Field(serialization_alias="invoicedQty")


class PurchaseOrderOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    order_no: str = Field(serialization_alias="orderNo")
    supplier_id: str = Field(serialization_alias="supplierId")
    supplier_name: str = Field(default="", serialization_alias="supplierName")
    order_date: date = Field(serialization_alias="orderDate")
    status: str
    currency: str
    total_amount: Decimal = Field(serialization_alias="totalAmount")
    remark: str | None = None
    lines: list[OrderLineOut] = Field(default_factory=list)
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class PurchaseOrderStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["submitted", "cancelled"]


# ---------- 收货 ----------


class ReceiptLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_line_id: str
    quantity: Decimal = Field(gt=0)


class GoodsReceiptCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt_no: str = Field(min_length=1, max_length=40)
    order_id: str
    receipt_date: date
    lines: list[ReceiptLineIn] = Field(min_length=1)
    remark: str | None = None


class ReceiptLineOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    line_no: int = Field(serialization_alias="lineNo")
    order_line_id: str = Field(serialization_alias="orderLineId")
    item_name: str = Field(default="", serialization_alias="itemName")
    quantity: Decimal
    unit_price: Decimal = Field(serialization_alias="unitPrice")
    amount: Decimal


class GoodsReceiptOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    receipt_no: str = Field(serialization_alias="receiptNo")
    order_id: str = Field(serialization_alias="orderId")
    order_no: str = Field(default="", serialization_alias="orderNo")
    supplier_id: str = Field(serialization_alias="supplierId")
    supplier_name: str = Field(default="", serialization_alias="supplierName")
    receipt_date: date = Field(serialization_alias="receiptDate")
    status: str
    total_quantity: Decimal = Field(serialization_alias="totalQuantity")
    total_amount: Decimal = Field(serialization_alias="totalAmount")
    remark: str | None = None
    lines: list[ReceiptLineOut] = Field(default_factory=list)
    created_at: datetime = Field(serialization_alias="createdAt")


# ---------- 发票 ----------


class InvoiceLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_line_id: str | None = None
    item_name: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(ge=0)
    unit_price: Decimal = Field(ge=0)
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1)


class PurchaseInvoiceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_no: str = Field(min_length=1, max_length=40)
    order_id: str | None = None
    supplier_id: str
    invoice_date: date
    lines: list[InvoiceLineIn] = Field(min_length=1)
    remark: str | None = None


class InvoiceLineOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    line_no: int = Field(serialization_alias="lineNo")
    order_line_id: str | None = Field(default=None, serialization_alias="orderLineId")
    item_name: str = Field(serialization_alias="itemName")
    quantity: Decimal
    unit_price: Decimal = Field(serialization_alias="unitPrice")
    amount: Decimal


class PurchaseInvoiceOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    invoice_no: str = Field(serialization_alias="invoiceNo")
    order_id: str | None = Field(default=None, serialization_alias="orderId")
    order_no: str = Field(default="", serialization_alias="orderNo")
    supplier_id: str = Field(serialization_alias="supplierId")
    supplier_name: str = Field(default="", serialization_alias="supplierName")
    invoice_date: date = Field(serialization_alias="invoiceDate")
    status: str
    currency: str
    total_amount: Decimal = Field(serialization_alias="totalAmount")
    tax_amount: Decimal = Field(serialization_alias="taxAmount")
    remark: str | None = None
    lines: list[InvoiceLineOut] = Field(default_factory=list)
    created_at: datetime = Field(serialization_alias="createdAt")
