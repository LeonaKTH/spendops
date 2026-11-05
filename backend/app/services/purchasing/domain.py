"""SpendOps 采购业务领域工具：金额计算、业务异常、状态常量。

金额计算全部使用 Decimal，四舍五入到分（ROUND_HALF_UP），禁止 Float。
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

# 金额精度常量
CENT = Decimal("0.01")


class BusinessError(Exception):
    """业务规则违反，由 API 层转换为 4xx 响应。"""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class NotFoundError(BusinessError):
    def __init__(self, message: str):
        super().__init__(message, status_code=404)


class ConflictError(BusinessError):
    """唯一约束冲突 / 幂等冲突。"""

    def __init__(self, message: str):
        super().__init__(message, status_code=409)


def money(value: Decimal | int | float | str) -> Decimal:
    """把金额归一到分（2 位小数）。"""
    d = Decimal(str(value))
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def qty(value: Decimal | int | float | str) -> Decimal:
    """数量归一到 3 位小数。"""
    d = Decimal(str(value))
    return d.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def line_amount(quantity: Decimal, unit_price: Decimal) -> Decimal:
    """明细金额 = 数量 × 单价，四舍五入到分。"""
    return money(Decimal(str(quantity)) * Decimal(str(unit_price)))


def total_amount(amounts: list[Decimal]) -> Decimal:
    """汇总金额 = 各明细金额之和。"""
    total = sum((Decimal(str(a)) for a in amounts), Decimal("0"))
    return money(total)


# 供应商状态
SUPPLIER_ACTIVE = "active"
SUPPLIER_INACTIVE = "inactive"
SUPPLIER_BLOCKED = "blocked"

# 采购订单状态机：
#   draft -> submitted -> partially_received -> received
#   draft / submitted -> cancelled（已收货后不可取消）
ORDER_DRAFT = "draft"
ORDER_SUBMITTED = "submitted"
ORDER_PARTIALLY_RECEIVED = "partially_received"
ORDER_RECEIVED = "received"
ORDER_CANCELLED = "cancelled"

ORDER_STATUSES = {
    ORDER_DRAFT,
    ORDER_SUBMITTED,
    ORDER_PARTIALLY_RECEIVED,
    ORDER_RECEIVED,
    ORDER_CANCELLED,
}

# 收货单 / 发票状态
POSTED = "posted"
CANCELLED = "cancelled"
