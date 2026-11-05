"""SpendOps G2 数据接入模型：持久化导入任务队列 + 暂存行 + 错误报告。

设计要点：
1. ``ImportTask`` 是持久任务队列。Worker 通过 ``FOR UPDATE SKIP LOCKED``
   认领任务，进程退出后状态不丢失，超时可被其他 Worker 重新认领。
2. ``ImportStagingRow`` 保存解析后的原始行、映射结果与行级校验错误，
   保证错误报告可查询、可追溯，不依赖进程内状态。
3. 暂存数据与正式业务表（Supplier/PO/GR/Invoice）分离：文件先进入暂存，
   校验通过并确认后才写入正式业务表，不直接修改正式单据状态。

任务状态机：
    uploaded -> validating -> awaiting_confirm -> importing
        -> completed | partial_failed | failed
    任意状态可被 cancelled 打断。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# 导入任务状态（收敛后）。
TASK_UPLOADED = "uploaded"
TASK_VALIDATING = "validating"
TASK_AWAITING_CONFIRM = "awaiting_confirm"
TASK_IMPORTING = "importing"
TASK_COMPLETED = "completed"
TASK_PARTIAL_FAILED = "partial_failed"
TASK_FAILED = "failed"
TASK_CANCELLED = "cancelled"

TASK_STATUSES = (
    TASK_UPLOADED,
    TASK_VALIDATING,
    TASK_AWAITING_CONFIRM,
    TASK_IMPORTING,
    TASK_COMPLETED,
    TASK_PARTIAL_FAILED,
    TASK_FAILED,
    TASK_CANCELLED,
)

# 导入业务类型（对应四类采购业务数据）。
IMPORT_SUPPLIER = "supplier"
IMPORT_PURCHASE_ORDER = "purchase_order"
IMPORT_GOODS_RECEIPT = "goods_receipt"
IMPORT_PURCHASE_INVOICE = "purchase_invoice"

IMPORT_TYPES = (
    IMPORT_SUPPLIER,
    IMPORT_PURCHASE_ORDER,
    IMPORT_GOODS_RECEIPT,
    IMPORT_PURCHASE_INVOICE,
)

# 暂存行状态。
ROW_PENDING = "pending"
ROW_VALID = "valid"
ROW_ERROR = "error"
ROW_IMPORTED = "imported"


class ImportTask(Base):
    """一次批量导入任务。同时充当持久化任务队列的队列表。"""

    __tablename__ = "import_tasks"
    __table_args__ = (
        CheckConstraint(
            f"task_type IN {IMPORT_TYPES}", name="ck_import_tasks_type"
        ),
        CheckConstraint(
            f"status IN {TASK_STATUSES}", name="ck_import_tasks_status"
        ),
        # 队列认领时按创建时间取最早未处理任务。
        Index("ix_import_tasks_status_created", "status", "created_at"),
        Index("ix_import_tasks_file_hash", "file_hash"),
        Index("ix_import_tasks_created_by", "created_by"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_type: Mapped[str] = mapped_column(String(32))
    original_name: Mapped[str] = mapped_column(String(500))
    file_hash: Mapped[str] = mapped_column(String(64))  # sha256
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(32), default=TASK_UPLOADED)

    # 行级统计。
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    processed_rows: Mapped[int] = mapped_column(Integer, default=0)
    success_rows: Mapped[int] = mapped_column(Integer, default=0)
    failed_rows: Mapped[int] = mapped_column(Integer, default=0)

    # 字段映射（中文列名 -> 业务字段），JSONB 存储便于前端展示与校验。
    mapping: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 错误摘要（错误类型 -> 数量）。
    error_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # 创建者与幂等作用域。
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_username: Mapped[str] = mapped_column(String(64), default="")
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Worker 认领信息。
    claimed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ImportStagingRow(Base):
    """暂存行：解析后的原始行 + 映射结果 + 行级校验错误。"""

    __tablename__ = "import_staging_rows"
    __table_args__ = (
        CheckConstraint(
            f"status IN ('{ROW_PENDING}', '{ROW_VALID}', '{ROW_ERROR}', '{ROW_IMPORTED}')",
            name="ck_import_staging_status",
        ),
        Index("ix_import_staging_task_status", "task_id", "status"),
        Index("ix_import_staging_task_row", "task_id", "row_number"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_tasks.id", ondelete="CASCADE"), index=True
    )
    row_number: Mapped[int] = mapped_column(Integer)  # 源文件行号（含表头，从 2 起）
    raw_data: Mapped[dict] = mapped_column(JSONB)  # 原始单元格（列名 -> 值）
    mapped_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # 映射后的业务字段
    status: Mapped[str] = mapped_column(String(16), default=ROW_PENDING)
    error_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_field: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_key: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 业务主键（如单号）
