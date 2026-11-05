from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ColumnMeta(BaseModel):
    """前端展示用的字段信息（物理列名在内部使用，不直接暴露）。"""

    name: str
    type: str  # text | number | date
    sample: str = ""


class QualityOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_rows: int = Field(serialization_alias="sourceRows")
    imported_rows: int = Field(serialization_alias="importedRows")
    blank_rows: int = Field(default=0, serialization_alias="blankRows")
    duplicate_rows: int = Field(default=0, serialization_alias="duplicateRows")
    invalid_cells: int = Field(default=0, serialization_alias="invalidCells")
    issues: list[str] = Field(default_factory=list)


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    name: str
    source_file: str = Field(serialization_alias="sourceFile")
    sheet_name: str | None = Field(default=None, serialization_alias="sheetName")
    row_count: int = Field(serialization_alias="rowCount")
    columns: list[ColumnMeta] = Field(default_factory=list)
    created_at: datetime = Field(serialization_alias="createdAt")
    status: str
    owner_id: str | None = Field(default=None, serialization_alias="ownerId")
    quality: QualityOut | None = None


class PreviewOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sheet_name: str = Field(serialization_alias="sheetName")
    row_count: int = Field(serialization_alias="rowCount")
    columns: list[ColumnMeta]
    rows: list[list[object]]
    quality: QualityOut | None = None


class DatasetRowsOut(BaseModel):
    """已导入数据集的明细预览（分页）。"""

    columns: list[str]
    rows: list[list[object]]
    total: int
    offset: int
    limit: int


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    name: str
    source_file: str = Field(serialization_alias="sourceFile")
    doc_type: str = Field(serialization_alias="docType")
    page_count: int = Field(serialization_alias="pageCount")
    char_count: int = Field(serialization_alias="charCount")
    chunk_count: int = Field(serialization_alias="chunkCount")
    created_at: datetime = Field(serialization_alias="createdAt")
    status: str


class DocumentPageOut(BaseModel):
    page: int
    content: str


class DocumentPagesOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    page_count: int = Field(serialization_alias="pageCount")
    pages: list[DocumentPageOut]


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    dataset_ids: list[str] = Field(default_factory=list)


class ChatColumn(BaseModel):
    physical: str
    display: str


class TableOut(BaseModel):
    columns: list[str]
    rows: list[list[str | float | int | None]]


class ReportDatasetOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    source_file: str = Field(serialization_alias="sourceFile")
    row_count: int = Field(serialization_alias="rowCount")
    period_start: str = Field(serialization_alias="periodStart")
    period_end: str = Field(serialization_alias="periodEnd")


class ReportDatasetOptionOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    row_count: int = Field(serialization_alias="rowCount")
    period_start: str = Field(serialization_alias="periodStart")
    period_end: str = Field(serialization_alias="periodEnd")


class ReportKpiOut(BaseModel):
    label: str
    value: str
    unit: str
    delta: str
    warn: bool


class ReportSeriesOut(BaseModel):
    name: str
    data: list[float]


class ReportDatumOut(BaseModel):
    name: str
    value: float


class ReportChartOut(BaseModel):
    model_config = ConfigDict(exclude_none=True)

    type: Literal["bar", "line", "pie"]
    title: str
    x: list[str] | None = None
    series: list[ReportSeriesOut] | None = None
    data: list[ReportDatumOut] | None = None
    unit: str | None = None


class ReportInsightOut(BaseModel):
    title: str
    meta: str
    tag: str


class ReportCatalogOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    total_models: int = Field(serialization_alias="totalModels")
    provider_count: int = Field(serialization_alias="providerCount")
    summary: str
    table: TableOut


class ReportMomOut(BaseModel):
    """与上一个等长期间相比的环比。"""

    model_config = ConfigDict(populate_by_name=True)

    previous_start: str = Field(serialization_alias="previousStart")
    previous_end: str = Field(serialization_alias="previousEnd")
    previous_amount: float = Field(serialization_alias="previousAmount")
    change_pct: float | None = Field(default=None, serialization_alias="changePct")


class ReportBudgetOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    summary: str
    table: TableOut
    annual_total: float = Field(serialization_alias="annualTotal")
    used_total: float = Field(serialization_alias="usedTotal")
    usage_pct: float = Field(serialization_alias="usagePct")


class ReportPurchasingOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    summary: str
    quote_table: TableOut = Field(serialization_alias="quoteTable")
    plan_count: int = Field(default=0, serialization_alias="planCount")
    rate_limit_count: int = Field(default=0, serialization_alias="rateLimitCount")


class ReportSummaryOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    generated_at: datetime = Field(serialization_alias="generatedAt")
    dataset: ReportDatasetOut
    kpis: list[ReportKpiOut]
    provider_chart: ReportChartOut = Field(serialization_alias="providerChart")
    app_chart: ReportChartOut | None = Field(default=None, serialization_alias="appChart")
    monthly_chart: ReportChartOut | None = Field(default=None, serialization_alias="monthlyChart")
    quota_table: TableOut = Field(serialization_alias="quotaTable")
    catalog: ReportCatalogOut | None = None
    provider_summary: str = Field(serialization_alias="providerSummary")
    app_summary: str = Field(serialization_alias="appSummary")
    monthly_summary: str = Field(serialization_alias="monthlySummary")
    quota_summary: str = Field(serialization_alias="quotaSummary")
    insights: list[ReportInsightOut]
    model_count: int = Field(serialization_alias="modelCount")
    app_count: int = Field(serialization_alias="appCount")
    provider_filter: str | None = Field(default=None, serialization_alias="providerFilter")
    mom: ReportMomOut | None = None
    budget: ReportBudgetOut | None = None
    purchasing: ReportPurchasingOut | None = None
    currency_note: str | None = Field(default=None, serialization_alias="currencyNote")


class ReportShareIn(BaseModel):
    dataset_id: str = Field(min_length=1, max_length=64)
    start_date: date | None = None
    end_date: date | None = None
    provider: str | None = Field(default=None, max_length=200)
    expires_in_days: Literal[7, 30, 90] = 30


class ReportShareOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    dataset_id: str = Field(serialization_alias="datasetId")
    dataset_name: str = Field(serialization_alias="datasetName")
    period_start: str | None = Field(default=None, serialization_alias="periodStart")
    period_end: str | None = Field(default=None, serialization_alias="periodEnd")
    provider: str | None = None
    path: str
    active: bool
    expires_at: datetime = Field(serialization_alias="expiresAt")
    created_at: datetime = Field(serialization_alias="createdAt")
    created_by_username: str = Field(serialization_alias="createdByUsername")
    view_count: int = Field(serialization_alias="viewCount")
    last_viewed_at: datetime | None = Field(default=None, serialization_alias="lastViewedAt")


class ReportViewIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    dataset_id: str = Field(min_length=1, max_length=64)
    start_date: date | None = None
    end_date: date | None = None
    provider: str | None = Field(default=None, max_length=200)


class ReportViewOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    dataset_id: str = Field(serialization_alias="datasetId")
    dataset_name: str = Field(serialization_alias="datasetName")
    period_start: str | None = Field(default=None, serialization_alias="periodStart")
    period_end: str | None = Field(default=None, serialization_alias="periodEnd")
    provider: str | None = None
    created_by_username: str = Field(serialization_alias="createdByUsername")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    username: str
    display_name: str = Field(serialization_alias="displayName")
    role: Literal["admin", "viewer"]
    is_active: bool = Field(serialization_alias="isActive")
    must_change_password: bool = Field(serialization_alias="mustChangePassword")
    last_login_at: datetime | None = Field(default=None, serialization_alias="lastLoginAt")
    created_at: datetime = Field(serialization_alias="createdAt")


class AdminUserCreateIn(BaseModel):
    # 长度与格式由 users.validate_username / validate_password 校验，
    # 以便返回统一的中文提示，而不是 Pydantic 的英文默认消息。
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    role: Literal["admin", "viewer"] = "viewer"
    display_name: str = Field(default="", max_length=100)


class AdminUserUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=100)
    role: Literal["admin", "viewer"] | None = None
    is_active: bool | None = None

    def is_empty(self) -> bool:
        return self.display_name is None and self.role is None and self.is_active is None


class ResetPasswordIn(BaseModel):
    new_password: str = Field(min_length=1, max_length=128)


class PaginatedUsersOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[UserOut]
    total: int
    page: int
    page_size: int = Field(serialization_alias="pageSize")


class AuditLogOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    actor_username: str = Field(serialization_alias="actorUsername")
    action: str
    target_type: str | None = Field(default=None, serialization_alias="targetType")
    target_id: str | None = Field(default=None, serialization_alias="targetId")
    status: Literal["success", "failure"]
    detail: dict | None = None
    ip: str | None = None
    created_at: datetime = Field(serialization_alias="createdAt")


class PaginatedAuditLogsOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[AuditLogOut]
    total: int
    page: int
    page_size: int = Field(serialization_alias="pageSize")


class AdminOverviewOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    users: int
    active_users: int = Field(serialization_alias="activeUsers")
    admins: int
    datasets: int
    active_datasets: int = Field(serialization_alias="activeDatasets")
    documents: int
    audit_events_24h: int = Field(serialization_alias="auditEvents24h")
    recent_audit: list[AuditLogOut] = Field(serialization_alias="recentAudit")
