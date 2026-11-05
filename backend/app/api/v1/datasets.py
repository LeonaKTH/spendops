from __future__ import annotations

import hashlib
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas import ColumnMeta, DatasetOut, DatasetRowsOut, PreviewOut, QualityOut
from app.core.config import get_settings
from app.core.security import AuthUser, client_ip, get_current_user, require_admin
from app.db.models import Dataset
from app.db.session import SessionLocal, get_db
from app.infra.cache import invalidate
from app.ingest.excel import parse_upload
from app.services.audit import DATASET_DELETE, DATASET_UPLOAD, log_action
from app.services.datasets import (
    DatasetMeta,
    create_dataset,
    delete_dataset,
    find_dataset_by_hash,
    load_datasets,
)
from app.services.query import fetch_dataset_rows

router = APIRouter(tags=["datasets"])

ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}


def _to_out(dataset: DatasetMeta) -> DatasetOut:
    return DatasetOut(
        id=dataset.id,
        name=dataset.name,
        source_file=dataset.source_file,
        sheet_name=dataset.sheet_name,
        row_count=dataset.row_count,
        created_at=dataset.created_at,
        status=dataset.status,
        owner_id=dataset.owner_id,
        quality=QualityOut.model_validate(dataset.quality) if dataset.quality else None,
        columns=[
            ColumnMeta(name=column.display, type=column.kind, sample=column.sample)
            for column in dataset.columns
        ],
    )


@router.get("/datasets", response_model=list[DatasetOut])
async def list_datasets(
    db: AsyncSession = Depends(get_db),
    _current: AuthUser = Depends(get_current_user),
) -> list[DatasetOut]:
    datasets = await load_datasets(db, active_only=False)
    return [_to_out(dataset) for dataset in datasets]


@router.get("/datasets/{dataset_id}/rows", response_model=DatasetRowsOut)
async def dataset_rows(
    dataset_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _current: AuthUser = Depends(get_current_user),
) -> DatasetRowsOut:
    try:
        uuid.UUID(dataset_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="无效的数据集 ID。") from exc

    datasets = await load_datasets(db, [dataset_id], active_only=False)
    if not datasets:
        raise HTTPException(status_code=404, detail="数据集不存在。")

    dataset = datasets[0]
    result = await fetch_dataset_rows(dataset, limit, offset)
    return DatasetRowsOut(
        columns=result.columns,
        rows=result.rows,
        total=dataset.row_count,
        offset=offset,
        limit=limit,
    )


async def _read_tabular_upload(file: UploadFile):
    filename = file.filename or "upload"
    extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="仅支持 .xlsx / .xls / .csv 文件。")

    settings = get_settings()
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="文件为空。")
    if len(content) > settings.upload_max_mb * 1024 * 1024:
        raise HTTPException(
            status_code=413, detail=f"文件超过 {settings.upload_max_mb} MB 限制。"
        )

    try:
        sheet = parse_upload(filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # 损坏的 Excel 等
        raise HTTPException(status_code=400, detail=f"文件解析失败：{exc}") from exc

    return filename, sheet, hashlib.sha256(content).hexdigest()


@router.post("/datasets/preview", response_model=PreviewOut)
async def preview_dataset(
    file: UploadFile = File(...),
    _admin: AuthUser = Depends(require_admin),
) -> PreviewOut:
    _filename, sheet, _content_hash = await _read_tabular_upload(file)
    return PreviewOut(
        sheet_name=sheet.sheet_name,
        row_count=sheet.row_count,
        rows=sheet.rows[:5],
        columns=[
            ColumnMeta(name=column.display, type=column.kind, sample=column.sample)
            for column in sheet.columns
        ],
        quality=QualityOut.model_validate(sheet.quality()),
    )


@router.post("/datasets", response_model=DatasetOut, status_code=201)
async def upload_dataset(
    request: Request,
    file: UploadFile = File(...),
    force: bool = Query(default=False, description="内容重复时仍然导入"),
    admin: AuthUser = Depends(require_admin),
) -> DatasetOut:
    filename, sheet, content_hash = await _read_tabular_upload(file)

    try:
        async with SessionLocal() as session:
            async with session.begin():
                if not force:
                    existing = await find_dataset_by_hash(session, content_hash)
                    if existing is not None:
                        raise HTTPException(
                            status_code=409,
                            detail=(
                                f"该文件已导入为数据集「{existing.name}」"
                                f"（{existing.row_count} 行）。如需重复导入请选择强制导入。"
                            ),
                        )
                dataset = await create_dataset(
                    session,
                    filename,
                    sheet,
                    owner_id=str(admin.id),
                    content_hash=content_hash,
                )
                await log_action(
                    session,
                    actor=admin,
                    action=DATASET_UPLOAD,
                    target_type="dataset",
                    target_id=dataset.id,
                    detail={
                        "name": dataset.name,
                        "filename": filename,
                        "row_count": dataset.row_count,
                    },
                    ip=client_ip(request),
                )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"写入数据库失败：{exc}") from exc

    await invalidate()
    return _to_out(dataset)


@router.delete("/datasets/{dataset_id}", status_code=204)
async def remove_dataset(
    dataset_id: str,
    request: Request,
    admin: AuthUser = Depends(require_admin),
) -> None:
    try:
        uuid.UUID(dataset_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="无效的数据集 ID。") from exc

    async with SessionLocal() as session:
        async with session.begin():
            dataset = await session.get(Dataset, uuid.UUID(dataset_id))
            if dataset is None:
                raise HTTPException(status_code=404, detail="数据集不存在。")
            detail = {
                "name": dataset.name,
                "physical_table": dataset.physical_table,
                "source_file": dataset.source_file,
            }
            removed = await delete_dataset(session, dataset_id)
            if removed:
                await log_action(
                    session,
                    actor=admin,
                    action=DATASET_DELETE,
                    target_type="dataset",
                    target_id=dataset_id,
                    detail=detail,
                    ip=client_ip(request),
                )

    if not removed:
        raise HTTPException(status_code=404, detail="数据集不存在。")

    await invalidate()
