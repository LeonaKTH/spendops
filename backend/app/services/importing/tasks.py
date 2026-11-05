"""SpendOps G2 导入任务服务：任务创建、暂存、字段校验、认领、进度与错误报告。

任务生命周期：
    uploaded -> awaiting_confirm -> importing -> completed / partial_failed / failed
    任意状态可被 cancelled。

上传阶段（同步）只做：文件解析 + 字段映射 + 字段校验 + 暂存写入，
不写业务表。业务入库由独立 Worker 异步执行。
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.importing import (
    IMPORT_TYPES,
    ImportStagingRow,
    ImportTask,
    ROW_ERROR,
    ROW_IMPORTED,
    ROW_PENDING,
    ROW_VALID,
    TASK_AWAITING_CONFIRM,
    TASK_CANCELLED,
    TASK_COMPLETED,
    TASK_FAILED,
    TASK_IMPORTING,
    TASK_PARTIAL_FAILED,
    TASK_UPLOADED,
    TASK_VALIDATING,
)
from app.services.importing.errors import RowError, suggestion_for
from app.services.importing.mappings import FieldDef, auto_map, get_fields
from app.services.importing.parse import parse_tabular
from app.services.importing.validate import mapped_to_json, validate_row

# Worker 认领超时（秒）：超过该时长视为 Worker 崩溃，可被重新认领。
CLAIM_TIMEOUT_SECONDS = 300


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _mapping_or_auto(
    task_type: str, headers: list[str], mapping: dict[str, str] | None
) -> dict[str, str]:
    """使用用户提供的映射，否则自动映射。"""
    if mapping:
        return mapping
    return auto_map(headers, task_type)


async def create_import_task(
    session: AsyncSession,
    *,
    task_type: str,
    filename: str,
    content: bytes,
    created_by: str | None,
    created_by_username: str,
    mapping: dict[str, str] | None = None,
) -> tuple[ImportTask, list[dict]]:
    """解析文件 + 字段校验 + 写入暂存与任务。返回 (任务, 预览行)。

    预览行用于前端展示解析结果；这里不写业务表。
    """
    if task_type not in IMPORT_TYPES:
        raise ValueError(f"未知导入类型：{task_type}")

    headers, rows = parse_tabular(filename, content)
    fields = get_fields(task_type)
    resolved_mapping = _mapping_or_auto(task_type, headers, mapping)

    file_hash = _sha256(content)

    task = ImportTask(
        task_type=task_type,
        original_name=filename,
        file_hash=file_hash,
        file_size=len(content),
        status=TASK_UPLOADED,
        mapping=resolved_mapping,
        created_by=uuid.UUID(created_by) if created_by else None,
        created_by_username=created_by_username,
        total_rows=len(rows),
    )
    session.add(task)
    await session.flush()  # 拿到 task.id

    staging_rows: list[ImportStagingRow] = []
    error_summary: dict[str, int] = {}
    failed_count = 0

    for index, raw_row in enumerate(rows):
        row_number = index + 2  # 第 1 行是表头
        mapped, errors = validate_row(raw_row, resolved_mapping, fields)
        if errors:
            err = errors[0]
            status = ROW_ERROR
            failed_count += 1
            error_summary[err.error_type] = error_summary.get(err.error_type, 0) + 1
            staging = ImportStagingRow(
                task_id=task.id,
                row_number=row_number,
                raw_data=raw_row,
                mapped_data=None,
                status=status,
                error_type=err.error_type,
                error_field=err.field,
                error_message=err.message,
                business_key=_business_key(task_type, raw_row, resolved_mapping),
            )
        else:
            status = ROW_VALID
            staging = ImportStagingRow(
                task_id=task.id,
                row_number=row_number,
                raw_data=raw_row,
                mapped_data=mapped_to_json(mapped),
                status=status,
                business_key=_business_key(task_type, raw_row, resolved_mapping),
            )
        staging_rows.append(staging)

    session.add_all(staging_rows)

    # 字段校验完成，任务进入等待确认（业务校验 + 入库由 Worker 在确认后执行）。
    task.status = TASK_AWAITING_CONFIRM
    task.failed_rows = failed_count
    task.error_summary = error_summary or None
    await session.commit()

    preview = [
        {"rowNumber": s.row_number, "raw": s.raw_data, "mapped": s.mapped_data,
         "status": s.status, "errorType": s.error_type,
         "errorField": s.error_field, "errorMessage": s.error_message}
        for s in staging_rows[:10]
    ]
    return task, preview


def _business_key(task_type: str, raw_row: dict[str, Any], mapping: dict[str, str]) -> str | None:
    group_field = {
        "supplier": "code",
        "purchase_order": "order_no",
        "goods_receipt": "receipt_no",
        "purchase_invoice": "invoice_no",
    }.get(task_type)
    if not group_field:
        return None
    source_col = next((col for col, key in mapping.items() if key == group_field), None)
    if source_col is None:
        return None
    value = raw_row.get(source_col)
    return str(value).strip() if value else None


async def list_tasks(
    session: AsyncSession, created_by: str | None = None
) -> list[ImportTask]:
    statement = select(ImportTask).order_by(ImportTask.created_at.desc())
    if created_by:
        statement = statement.where(ImportTask.created_by == uuid.UUID(created_by))
    return list((await session.execute(statement)).scalars())


async def get_task(session: AsyncSession, task_id: str) -> ImportTask | None:
    try:
        key = uuid.UUID(task_id)
    except ValueError:
        return None
    return await session.get(ImportTask, key)


async def get_task_errors(
    session: AsyncSession, task_id: str, limit: int = 100, offset: int = 0
) -> tuple[int, list[dict]]:
    """读取任务的错误行报告（行号、字段、错误类型、建议）。"""
    try:
        key = uuid.UUID(task_id)
    except ValueError:
        return 0, []

    total = await session.scalar(
        select(func.count()).select_from(ImportStagingRow).where(
            ImportStagingRow.task_id == key, ImportStagingRow.status == ROW_ERROR
        )
    )
    rows = (
        await session.execute(
            select(ImportStagingRow)
            .where(ImportStagingRow.task_id == key, ImportStagingRow.status == ROW_ERROR)
            .order_by(ImportStagingRow.row_number)
            .offset(offset)
            .limit(limit)
        )
    ).scalars()

    return int(total or 0), [
        {
            "rowNumber": row.row_number,
            "errorType": row.error_type,
            "field": row.error_field,
            "message": row.error_message,
            "suggestion": suggestion_for(row.error_type or ""),
        }
        for row in rows
    ]


async def cancel_task(session: AsyncSession, task_id: str) -> bool:
    """取消任务：仅未完成的任务可取消。"""
    task = await get_task(session, task_id)
    if task is None:
        return False
    if task.status in (TASK_COMPLETED, TASK_PARTIAL_FAILED, TASK_FAILED, TASK_CANCELLED):
        return False
    task.status = TASK_CANCELLED
    task.finished_at = datetime.now(UTC)
    await session.commit()
    return True


async def confirm_task(session: AsyncSession, task_id: str) -> bool:
    """用户确认导入：awaiting_confirm -> importing。"""
    task = await get_task(session, task_id)
    if task is None or task.status != TASK_AWAITING_CONFIRM:
        return False
    task.status = TASK_IMPORTING
    await session.commit()
    return True


async def claim_task(session: AsyncSession, worker_id: str) -> ImportTask | None:
    """Worker 认领一个待处理任务（FOR UPDATE SKIP LOCKED，防并发重复处理）。

    认领条件：status=importing，且（未被认领 或 认领超时可重试）。
    """
    # 认领超时的任务标记为可重试：先更新状态，再抢锁。
    await session.execute(
        update(ImportTask)
        .where(
            ImportTask.status == TASK_IMPORTING,
            ImportTask.claimed_at.is_not(None),
            ImportTask.claimed_at < datetime.now(UTC) - timedelta(seconds=CLAIM_TIMEOUT_SECONDS),
        )
        .values(claimed_by=None, claimed_at=None)
    )
    await session.commit()

    task = (
        await session.execute(
            select(ImportTask)
            .where(
                ImportTask.status == TASK_IMPORTING,
                (ImportTask.claimed_by.is_(None)) | (ImportTask.claimed_by == ""),
            )
            .order_by(ImportTask.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()

    if task is None:
        return None

    task.claimed_by = worker_id
    task.claimed_at = datetime.now(UTC)
    task.attempts = (task.attempts or 0) + 1
    task.started_at = task.started_at or datetime.now(UTC)
    await session.commit()
    return task


async def load_import_rows(
    session: AsyncSession, task_id: str
) -> list[ImportStagingRow]:
    """读取待导入的暂存行（status=valid）。"""
    try:
        key = uuid.UUID(task_id)
    except ValueError:
        return []
    rows = (
        await session.execute(
            select(ImportStagingRow).where(
                ImportStagingRow.task_id == key, ImportStagingRow.status == ROW_VALID
            ).order_by(ImportStagingRow.row_number)
        )
    ).scalars()
    return list(rows)


async def renew_claim(session: AsyncSession, task_id: str, worker_id: str) -> bool:
    """续租：更新 claimed_at，条件是 claimed_by 仍是当前 Worker。

    返回 True 表示续租成功（所有权未丢失）；False 表示任务已被其他 Worker
    重新认领（所有权丢失），当前 Worker 应中止处理。
    """
    try:
        key = uuid.UUID(task_id)
    except ValueError:
        return False
    result = await session.execute(
        update(ImportTask)
        .where(ImportTask.id == key, ImportTask.claimed_by == worker_id)
        .values(claimed_at=datetime.now(UTC))
    )
    await session.commit()
    return result.rowcount == 1


async def is_task_cancelled(session: AsyncSession, task_id: str) -> bool:
    """任务是否已被取消。"""
    task = await get_task(session, task_id)
    return task is not None and task.status == TASK_CANCELLED


async def finish_task(session: AsyncSession, task_id: str) -> None:
    """任务完成：从暂存表对账统计 imported/error 行数，更新终态。

    用 staging 表对账（而非参数累加），保证 Worker 崩溃重试后计数仍准确：
    - imported 行数 = 成功行数（已成功不会因重试被误记为失败）；
    - error 行数 = 失败行数（字段级错误 + 业务级错误）；
    - 终态按对账结果判定，不会错误显示 completed。
    """
    task = await get_task(session, task_id)
    if task is None:
        return
    key = uuid.UUID(task_id)

    imported = await session.scalar(
        select(func.count()).select_from(ImportStagingRow).where(
            ImportStagingRow.task_id == key, ImportStagingRow.status == ROW_IMPORTED
        )
    )
    error = await session.scalar(
        select(func.count()).select_from(ImportStagingRow).where(
            ImportStagingRow.task_id == key, ImportStagingRow.status == ROW_ERROR
        )
    )
    summary_rows = await session.execute(
        select(ImportStagingRow.error_type, func.count())
        .where(ImportStagingRow.task_id == key, ImportStagingRow.status == ROW_ERROR)
        .group_by(ImportStagingRow.error_type)
    )
    error_summary = {et: int(c) for et, c in summary_rows.all() if et}

    task.success_rows = int(imported or 0)
    task.failed_rows = int(error or 0)
    task.processed_rows = task.success_rows + task.failed_rows
    task.error_summary = error_summary or None
    if task.failed_rows == 0:
        task.status = TASK_COMPLETED
    elif task.success_rows == 0:
        task.status = TASK_FAILED
    else:
        task.status = TASK_PARTIAL_FAILED
    task.finished_at = datetime.now(UTC)
    task.claimed_by = None
    task.claimed_at = None
    await session.commit()


async def fail_task(session: AsyncSession, task_id: str, message: str) -> None:
    """任务执行中发生不可恢复错误，标记失败。"""
    task = await get_task(session, task_id)
    if task is None:
        return
    task.status = TASK_FAILED
    task.last_error = message
    task.finished_at = datetime.now(UTC)
    task.claimed_by = None
    task.claimed_at = None
    await session.commit()
