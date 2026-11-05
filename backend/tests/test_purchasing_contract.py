"""前后端字段契约测试。

防止 camelCase/snake_case 不一致导致字段被静默忽略：
- 请求模型设 extra="forbid"，前端误传 camelCase 会被拒绝（422），而不是静默丢弃。
- 响应模型用 serialization_alias 输出 camelCase，与前端 TS 类型对齐。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.api.v1.purchasing_schemas import (
    SupplierCreate,
    SupplierOut,
)


def test_supplier_create_rejects_camelcase_fields():
    """前端误传 camelCase 字段必须被拒绝，而非静默忽略。"""
    with pytest.raises(ValidationError):
        SupplierCreate(code="S001", name="供应商", contactName="张三")


def test_supplier_create_accepts_snake_case():
    """后端契约是 snake_case，前端 client.ts 负责转换。"""
    supplier = SupplierCreate(code="S001", name="供应商", contact_name="张三", contact_phone="13800000000")
    assert supplier.contact_name == "张三"


def test_supplier_out_serializes_camelcase():
    """响应字段输出 camelCase，与前端 TS 类型对齐。"""
    out = SupplierOut(
        id="00000000-0000-0000-0000-000000000001",
        code="S001",
        name="供应商",
        contact_name="张三",
        contact_phone="13800000000",
        email=None,
        address=None,
        status="active",
        remark=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    data = out.model_dump(by_alias=True)
    assert "contactName" in data
    assert "contactPhone" in data
    assert "contact_name" not in data
    assert "contact_phone" not in data
