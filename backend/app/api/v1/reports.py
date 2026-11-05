from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas import (
    ReportDatasetOptionOut,
    ReportShareIn,
    ReportShareOut,
    ReportSummaryOut,
    ReportViewIn,
    ReportViewOut,
)
from app.core.security import AuthUser, client_ip, get_current_user
from app.db.models import Report, ReportShare
from app.db.session import get_db
from app.services.audit import (
    REPORT_EXPORT,
    REPORT_SHARE_CREATE,
    REPORT_SHARE_REVOKE,
    REPORT_VIEW_CREATE,
    REPORT_VIEW_DELETE,
    log_action,
)
from app.services.datasets import load_datasets
from app.services.report_export import ExportFormat, build_export, export_filename
from app.services.report_shares import (
    SharePermissionError,
    create_share,
    is_active,
    list_shares,
    revoke_share,
)
from app.services.report_views import (
    ReportViewPermissionError,
    create_view,
    delete_view,
    list_views,
)
from app.services.reports import (
    ReportDataError,
    ReportFilterError,
    _resolve_bill_dataset,
    build_report_summary,
    list_bill_datasets,
)

router = APIRouter(tags=["reports"])

ExportQuery = Literal["xlsx", "pdf"]


def _share_out(share: ReportShare, token: str = "") -> ReportShareOut:
    return ReportShareOut(
        id=str(share.id),
        dataset_id=str(share.dataset_id),
        dataset_name=share.dataset_name,
        period_start=share.period_start.isoformat() if share.period_start else None,
        period_end=share.period_end.isoformat() if share.period_end else None,
        provider=share.provider,
        path=f"/share/{token}" if token else "",
        active=is_active(share),
        expires_at=share.expires_at,
        created_at=share.created_at,
        created_by_username=share.created_by_username,
        view_count=share.view_count or 0,
        last_viewed_at=share.last_viewed_at,
    )


def _view_out(view: Report) -> ReportViewOut:
    return ReportViewOut(
        id=str(view.id),
        title=view.title,
        dataset_id=str(view.dataset_id or ""),
        dataset_name=view.dataset_name,
        period_start=view.period_start.isoformat() if view.period_start else None,
        period_end=view.period_end.isoformat() if view.period_end else None,
        provider=view.provider,
        created_by_username=view.created_by_username,
        created_at=view.created_at,
        updated_at=view.updated_at or view.created_at,
    )


def _export_response(summary: ReportSummaryOut, fmt: ExportFormat, *, cache: str = "no-store") -> Response:
    content, media_type = build_export(summary, fmt)
    filename = export_filename(summary, fmt)
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": cache,
        },
    )


@router.get(
    "/reports/summary",
    response_model=ReportSummaryOut,
    response_model_exclude_none=True,
)
async def report_summary(
    dataset_id: str | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    provider: str | None = Query(default=None, max_length=200),
    db: AsyncSession = Depends(get_db),
    _current: AuthUser = Depends(get_current_user),
) -> ReportSummaryOut:
    datasets = await load_datasets(db)
    try:
        return await build_report_summary(
            datasets, dataset_id, start_date, end_date, provider
        )
    except ReportFilterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ReportDataError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/reports/datasets", response_model=list[ReportDatasetOptionOut])
async def report_datasets(
    db: AsyncSession = Depends(get_db),
    _current: AuthUser = Depends(get_current_user),
) -> list[ReportDatasetOptionOut]:
    datasets = await load_datasets(db)
    return [
        ReportDatasetOptionOut(**item) for item in await list_bill_datasets(datasets)
    ]


@router.get("/reports/views", response_model=list[ReportViewOut])
async def report_views(
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
) -> list[ReportViewOut]:
    return [_view_out(view) for view in await list_views(db, actor=current)]


@router.post("/reports/views", response_model=ReportViewOut, status_code=201)
async def create_report_view(
    payload: ReportViewIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
) -> ReportViewOut:
    if payload.start_date and payload.end_date and payload.start_date > payload.end_date:
        raise HTTPException(status_code=400, detail="开始日期不能晚于结束日期。")

    datasets = await load_datasets(db)
    picked = await _resolve_bill_dataset(datasets, payload.dataset_id)
    if picked is None:
        raise HTTPException(status_code=404, detail="未找到可保存的账单数据集。")

    view = await create_view(
        db,
        actor=current,
        title=payload.title,
        dataset=picked.dataset,
        start_date=payload.start_date,
        end_date=payload.end_date,
        provider=payload.provider,
    )
    await log_action(
        db,
        actor=current,
        action=REPORT_VIEW_CREATE,
        target_type="report_view",
        target_id=str(view.id),
        detail={
            "title": view.title,
            "dataset_id": picked.dataset.id,
            "provider": view.provider,
        },
        ip=client_ip(request),
    )
    await db.commit()
    return _view_out(view)


@router.delete("/reports/views/{view_id}", status_code=204)
async def remove_report_view(
    view_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
) -> Response:
    try:
        view = await delete_view(db, view_id, actor=current)
    except ReportViewPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if view is None:
        raise HTTPException(status_code=404, detail="报表视图不存在。")

    await log_action(
        db,
        actor=current,
        action=REPORT_VIEW_DELETE,
        target_type="report_view",
        target_id=str(view.id),
        detail={"title": view.title},
        ip=client_ip(request),
    )
    await db.commit()
    return Response(status_code=204)


@router.get("/reports/export")
async def report_export(
    request: Request,
    dataset_id: str | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    provider: str | None = Query(default=None, max_length=200),
    fmt: ExportQuery = Query(default="xlsx", alias="format"),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
) -> Response:
    datasets = await load_datasets(db)
    try:
        summary = await build_report_summary(
            datasets, dataset_id, start_date, end_date, provider
        )
    except ReportFilterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ReportDataError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    await log_action(
        db,
        actor=current,
        action=REPORT_EXPORT,
        target_type="dataset",
        target_id=summary.dataset.id,
        detail={
            "format": fmt,
            "period_start": summary.dataset.period_start,
            "period_end": summary.dataset.period_end,
        },
        ip=client_ip(request),
    )
    await db.commit()
    return _export_response(summary, fmt)


@router.post("/reports/shares", response_model=ReportShareOut, status_code=201)
async def create_report_share(
    payload: ReportShareIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
) -> ReportShareOut:
    if payload.start_date and payload.end_date and payload.start_date > payload.end_date:
        raise HTTPException(status_code=400, detail="开始日期不能晚于结束日期。")

    datasets = await load_datasets(db)
    picked = await _resolve_bill_dataset(datasets, payload.dataset_id)
    if picked is None:
        raise HTTPException(status_code=404, detail="未找到可分享的账单数据集。")

    share, token = await create_share(
        db,
        dataset_id=picked.dataset.id,
        dataset_name=picked.dataset.name,
        period_start=payload.start_date,
        period_end=payload.end_date,
        actor=current,
        expires_in_days=payload.expires_in_days,
        provider=payload.provider,
    )
    await log_action(
        db,
        actor=current,
        action=REPORT_SHARE_CREATE,
        target_type="report_share",
        target_id=str(share.id),
        detail={
            "dataset_id": picked.dataset.id,
            "expires_in_days": payload.expires_in_days,
            "period_start": payload.start_date.isoformat() if payload.start_date else None,
            "period_end": payload.end_date.isoformat() if payload.end_date else None,
            "provider": payload.provider,
        },
        ip=client_ip(request),
    )
    await db.commit()
    return _share_out(share, token)


@router.get("/reports/shares", response_model=list[ReportShareOut])
async def report_shares(
    dataset_id: str | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
) -> list[ReportShareOut]:
    try:
        shares = await list_shares(
            db,
            actor=current,
            dataset_id=dataset_id,
            include_inactive=include_inactive,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="数据集 ID 不合法。") from exc
    return [_share_out(share) for share in shares]


@router.delete("/reports/shares/{share_id}", status_code=204)
async def delete_report_share(
    share_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
) -> Response:
    try:
        share = await revoke_share(db, share_id, actor=current)
    except SharePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if share is None:
        raise HTTPException(status_code=404, detail="分享链接不存在。")

    await log_action(
        db,
        actor=current,
        action=REPORT_SHARE_REVOKE,
        target_type="report_share",
        target_id=str(share.id),
        detail={"dataset_id": str(share.dataset_id)},
        ip=client_ip(request),
    )
    await db.commit()
    return Response(status_code=204)
