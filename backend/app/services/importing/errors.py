"""SpendOps G2 导入错误类型与行级错误结构。"""

from __future__ import annotations

from dataclasses import dataclass

# 错误类型（G2 要求至少区分这些）。
ERR_FILE_FORMAT = "file_format"                # 文件格式错误
ERR_MISSING_REQUIRED = "missing_required"      # 必填字段缺失
ERR_INVALID_FORMAT = "invalid_format"          # 日期/金额格式错误
ERR_SUPPLIER_NOT_FOUND = "supplier_not_found"  # 无法解析的供应商
ERR_ORDER_NOT_FOUND = "order_not_found"        # 订单关联失败
ERR_ORDER_LINE_NOT_FOUND = "order_line_not_found"  # 订单明细关联失败
ERR_DUPLICATE_KEY = "duplicate_business_key"   # 重复业务单号
ERR_INVALID_QUANTITY = "invalid_quantity"      # 非法收货数量
ERR_INVALID_INVOICE_QTY = "invalid_invoice_quantity"  # 非法累计开票数量
ERR_BUSINESS_CONFLICT = "business_conflict"    # 业务状态冲突


@dataclass
class RowError:
    row_number: int
    error_type: str
    field: str | None = None
    message: str = ""

    def as_dict(self) -> dict:
        return {
            "row_number": self.row_number,
            "error_type": self.error_type,
            "field": self.field,
            "message": self.message,
        }


# 错误类型 -> 修复建议（前端错误报告展示用）。
SUGGESTIONS: dict[str, str] = {
    ERR_FILE_FORMAT: "请检查文件是否为有效的 CSV/XLSX 格式，或另存为 UTF-8 后重试。",
    ERR_MISSING_REQUIRED: "请在源文件中补全该必填列的值后重新导入。",
    ERR_INVALID_FORMAT: "请修正该单元格的日期/金额格式（日期建议 YYYY-MM-DD，金额为纯数字）。",
    ERR_SUPPLIER_NOT_FOUND: "请先在「供应商」页创建该供应商，或修正供应商编码。",
    ERR_ORDER_NOT_FOUND: "请确认该采购订单已导入或已创建，并核对订单号。",
    ERR_ORDER_LINE_NOT_FOUND: "请确认订单号与物料编码匹配，明细物料必须存在于对应订单中。",
    ERR_DUPLICATE_KEY: "该业务单号已在系统或本文件中重复，请核对后合并或改名。",
    ERR_INVALID_QUANTITY: "收货数量不能为负或超过订单可收数量，请核对数量。",
    ERR_INVALID_INVOICE_QTY: "开票数量不能超过订单可开票数量，请核对累计开票数量。",
    ERR_BUSINESS_CONFLICT: "该单据当前状态不允许此操作，请检查单据状态。",
}


def suggestion_for(error_type: str) -> str:
    return SUGGESTIONS.get(error_type, "请核对数据后重新导入。")
