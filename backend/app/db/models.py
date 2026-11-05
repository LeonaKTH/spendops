import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# SpendOps 采购领域模型（独立文件，与上游 datasets/documents 等业务模型并列）。
# 通过此处 import 纳入 Base.metadata，Alembic 迁移可发现。
from app.db.purchasing import (  # noqa: F401,E402
    GoodsReceipt,
    GoodsReceiptLine,
    IdempotencyKey,
    PurchaseInvoice,
    PurchaseInvoiceLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
)

# SpendOps G2 数据接入模型（导入任务队列 + 暂存行 + 错误报告）。
from app.db.importing import ImportStagingRow, ImportTask  # noqa: F401,E402


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200))
    physical_table: Mapped[str] = mapped_column(String(200), unique=True)
    source_file: Mapped[str] = mapped_column(String(500))
    sheet_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="active")
    owner_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    quality: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        CheckConstraint("role IN ('admin', 'viewer')", name="ck_users_role"),
        Index("ix_users_role_is_active", "role", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    username: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(100), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    token_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1")
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint("status IN ('success', 'failure')", name="ck_audit_logs_status"),
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_action_created_at", "action", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_username: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="success")
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(300))
    source_file: Mapped[str] = mapped_column(String(500))
    doc_type: Mapped[str] = mapped_column(String(20))
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text)


class ReportShare(Base):
    __tablename__ = "report_shares"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_report_shares_token_hash"),
        Index("ix_report_shares_dataset_id", "dataset_id"),
        Index("ix_report_shares_created_by", "created_by"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    token_hash: Mapped[str] = mapped_column(String(64))
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE")
    )
    dataset_name: Mapped[str] = mapped_column(String(200), default="")
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_username: Mapped[str] = mapped_column(String(64), default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    view_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    last_viewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Report(Base):
    """保存的报表视图（数据集 + 期间 + 下钻条件）。"""

    __tablename__ = "reports"
    __table_args__ = (
        Index("ix_reports_owner_id", "owner_id"),
        Index("ix_reports_dataset_id", "dataset_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(200))
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    chart_spec: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    layout: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    dataset_name: Mapped[str] = mapped_column(String(200), default="")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_username: Mapped[str] = mapped_column(String(64), default="")
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
