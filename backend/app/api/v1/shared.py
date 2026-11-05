"""公开的只读报表分享接口。

分享 token 本身就是访问凭证，接口不要求登录；数据库只保存 token 摘要。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas import ReportSummaryOut
from app.core.security import client_ip
from app.db.session import get_db
from app.infra.rate_limit import hit_share_limit
from app.services.datasets import load_datasets
from app.services.report_export import ExportFormat, build_export, export_filename
from app.services.report_shares import resolve_share
from app.services.reports import ReportDataError, ReportFilterError, build_report_summary

router = APIRouter(tags=["shared"])


async def _resolve_or_404(token: str, request: Request, db: AsyncSession, *, touch: bool):
    retry_after = await hit_share_limit(token=token, ip=client_ip(request))
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="分享链接访问过于频繁，请稍后再试。",
            headers={"Retry-After": str(retry_after)},
        )
    share = await resolve_share(db, token, touch=touch)
    if share is None:
        raise HTTPException(status_code=404, detail="分享链接不存在、已过期或已被撤销。")
    return share


@router.get(
    "/shared/reports/{token}",
    response_model=ReportSummaryOut,
    response_model_exclude_none=True,
)
async def shared_report(
    token: str,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> ReportSummaryOut:
    response.headers["Referrer-Policy"] = "no-referrer"
    share = await _resolve_or_404(token, request, db, touch=True)
    datasets = await load_datasets(db)
    try:
        return await build_report_summary(
            datasets,
            str(share.dataset_id),
            share.period_start,
            share.period_end,
            share.provider,
        )
    except ReportFilterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ReportDataError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/shared/reports/{token}/export")
async def shared_report_export(
    token: str,
    request: Request,
    fmt: ExportFormat = Query(default="xlsx", alias="format"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    share = await _resolve_or_404(token, request, db, touch=True)
    datasets = await load_datasets(db)
    try:
        summary = await build_report_summary(
            datasets,
            str(share.dataset_id),
            share.period_start,
            share.period_end,
            share.provider,
        )
    except ReportFilterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ReportDataError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    content, media_type = build_export(summary, fmt)
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{export_filename(summary, fmt)}"',
            "Cache-Control": "no-store",
        },
    )
