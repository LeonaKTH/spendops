"""SpendOps G2 数据导入 API：文件上传、任务列表/详情、错误报告、确认与取消。

上传阶段只做「解析 + 字段校验 + 暂存」，快速返回任务 ID；
业务入库由独立 Worker 异步执行。
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import AuthUser, get_current_user, require_admin
from app.db.importing import (
    IMPORT_TYPES,
    TASK_AWAITING_CONFIRM,
    TASK_COMPLETED,
    TASK_FAILED,
    TASK_PARTIAL_FAILED,
)
from app.db.session import SessionLocal
from app.services.importing import tasks

router = APIRouter(tags=["imports"])

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}


def _task_dict(task) -> dict:
    return {
        "id": str(task.id),
        "taskType": task.task_type,
        "originalName": task.original_name,
        "fileHash": task.file_hash,
        "fileSize": task.file_size,
        "status": task.status,
        "totalRows": task.total_rows,
        "processedRows": task.processed_rows,
        "successRows": task.success_rows,
        "failedRows": task.failed_rows,
        "errorSummary": task.error_summary,
        "createdByUsername": task.created_by_username,
        "lastError": task.last_error,
        "createdAt": task.created_at.isoformat() if task.created_at else None,
        "startedAt": task.started_at.isoformat() if task.started_at else None,
        "finishedAt": task.finished_at.isoformat() if task.finished_at else None,
    }


@router.post("/imports")
async def upload_import(
    task_type: str = Form(...),
    mapping: str | None = Form(default=None),
    file: UploadFile = File(...),
    admin: AuthUser = Depends(require_admin),
) -> dict:
    """上传采购数据文件，返回任务 ID 与预览。"""
    if task_type not in IMPORT_TYPES:
        raise HTTPException(status_code=400, detail=f"未知导入类型：{task_type}")

    filename = file.filename or "upload.csv"
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="仅支持 .csv / .xlsx / .xls 文件。")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空。")

    max_bytes = get_settings().upload_max_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413, detail=f"文件超过 {get_settings().upload_max_mb} MB 限制。"
        )

    parsed_mapping: dict[str, str] | None = None
    if mapping:
        try:
            parsed_mapping = json.loads(mapping)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="字段映射 JSON 无效。") from exc

    try:
        async with SessionLocal() as session:
            task, preview = await tasks.create_import_task(
                session,
                task_type=task_type,
                filename=filename,
                content=content,
                created_by=str(admin.id),
                created_by_username=admin.username,
                mapping=parsed_mapping,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"文件解析失败：{exc}") from exc

    result = _task_dict(task)
    result["preview"] = preview
    return result


@router.get("/imports")
async def list_imports(
    user: AuthUser = Depends(get_current_user),
) -> list[dict]:
    async with SessionLocal() as session:
        rows = await tasks.list_tasks(session, created_by=str(user.id))
    return [_task_dict(t) for t in rows]


@router.get("/imports/{task_id}")
async def get_import(
    task_id: str,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    async with SessionLocal() as session:
        task = await tasks.get_task(session, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="导入任务不存在。")
        if task.created_by is not None and str(task.created_by) != str(user.id):
            raise HTTPException(status_code=403, detail="无权查看该导入任务。")
        return _task_dict(task)


@router.get("/imports/{task_id}/errors")
async def get_import_errors(
    task_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: AuthUser = Depends(get_current_user),
) -> dict:
    async with SessionLocal() as session:
        task = await tasks.get_task(session, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="导入任务不存在。")
        if task.created_by is not None and str(task.created_by) != str(user.id):
            raise HTTPException(status_code=403, detail="无权查看该导入任务。")
        total, errors = await tasks.get_task_errors(session, task_id, limit, offset)
    return {"total": total, "offset": offset, "limit": limit, "errors": errors}


@router.post("/imports/{task_id}/confirm")
async def confirm_import(
    task_id: str,
    admin: AuthUser = Depends(require_admin),
) -> dict:
    async with SessionLocal() as session:
        ok = await tasks.confirm_task(session, task_id)
        if not ok:
            task = await tasks.get_task(session, task_id)
            if task is None:
                raise HTTPException(status_code=404, detail="导入任务不存在。")
            raise HTTPException(status_code=409, detail=f"任务当前状态「{task.status}」不可确认。")
        task = await tasks.get_task(session, task_id)
        return _task_dict(task)


@router.post("/imports/{task_id}/cancel")
async def cancel_import(
    task_id: str,
    admin: AuthUser = Depends(require_admin),
) -> dict:
    async with SessionLocal() as session:
        ok = await tasks.cancel_task(session, task_id)
        if not ok:
            raise HTTPException(status_code=409, detail="任务已结束或不存在，无法取消。")
        task = await tasks.get_task(session, task_id)
        return _task_dict(task)
