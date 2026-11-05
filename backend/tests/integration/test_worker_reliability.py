"""G2 前置可靠性修复的针对性测试：租约续期、所有权丢失、取消中止、进度对账。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.db.importing import (
    IMPORT_SUPPLIER,
    ImportStagingRow,
    ImportTask,
    ROW_ERROR,
    ROW_IMPORTED,
    ROW_VALID,
    TASK_IMPORTING,
)
from app.services.importing import importer, tasks


async def _make_importing_task(session) -> ImportTask:
    task = ImportTask(
        task_type=IMPORT_SUPPLIER,
        original_name="test.csv",
        file_hash=uuid.uuid4().hex,
        file_size=0,
        status=TASK_IMPORTING,
        total_rows=0,
    )
    session.add(task)
    await session.flush()
    return task


@pytest.mark.asyncio
async def test_renew_claim_keeps_ownership(db_session):
    """续租：所有权保持时返回 True；他人续租返回 False。"""
    task = await _make_importing_task(db_session)
    claimed = await tasks.claim_task(db_session, "worker-1")
    assert claimed is not None

    assert await tasks.renew_claim(db_session, str(task.id), "worker-1") is True
    # 其他 Worker 无法续租（所有权不匹配）
    assert await tasks.renew_claim(db_session, str(task.id), "worker-2") is False


@pytest.mark.asyncio
async def test_reclaim_after_timeout_and_renew(db_session):
    """超时重认领后，旧 Worker 续租失败（所有权已转移）。"""
    task = await _make_importing_task(db_session)
    await tasks.claim_task(db_session, "worker-1")

    # 模拟旧 Worker 处理超时（claimed_at 设为超时之前）
    await db_session.execute(
        update(ImportTask)
        .where(ImportTask.id == task.id)
        .values(claimed_at=datetime.now(UTC) - timedelta(seconds=600))
    )
    await db_session.commit()

    # worker-2 重认领
    recovered = await tasks.claim_task(db_session, "worker-2")
    assert recovered is not None
    assert recovered.claimed_by == "worker-2"

    # 旧 worker-1 续租失败（所有权已归 worker-2）
    assert await tasks.renew_claim(db_session, str(task.id), "worker-1") is False


@pytest.mark.asyncio
async def test_on_progress_false_interrupts(db_session):
    """on_progress 返回 False（取消/所有权丢失）→ 抛出 ImportInterrupted。"""
    task = await _make_importing_task(db_session)
    row = ImportStagingRow(
        task_id=task.id, row_number=2, raw_data={},
        mapped_data={"code": "S001", "name": "供应商"}, status=ROW_VALID,
    )
    db_session.add(row)
    await db_session.flush()

    async def on_progress(_processed: int) -> bool:
        return False  # 模拟取消

    with pytest.raises(importer.ImportInterrupted):
        await importer.run_import(db_session, IMPORT_SUPPLIER, [row], on_progress)


@pytest.mark.asyncio
async def test_finish_task_reconciles_after_partial(db_session):
    """进度对账：部分 imported + 部分 error + 部分 valid，finish_task 后计数准确。"""
    task = await _make_importing_task(db_session)

    # 2 行 imported（成功），1 行 error（字段级），1 行 valid（未处理）
    imported = [
        ImportStagingRow(task_id=task.id, row_number=2, raw_data={},
                         mapped_data={"code": "A"}, status=ROW_IMPORTED),
        ImportStagingRow(task_id=task.id, row_number=3, raw_data={},
                         mapped_data={"code": "B"}, status=ROW_IMPORTED),
    ]
    error_row = ImportStagingRow(
        task_id=task.id, row_number=4, raw_data={}, mapped_data=None,
        status=ROW_ERROR, error_type="missing_required", error_field="name",
        error_message="缺名称",
    )
    valid_row = ImportStagingRow(
        task_id=task.id, row_number=5, raw_data={},
        mapped_data={"code": "C"}, status=ROW_VALID,
    )
    db_session.add_all(imported + [error_row, valid_row])
    await db_session.commit()

    await tasks.finish_task(db_session, str(task.id))

    refreshed = await tasks.get_task(db_session, str(task.id))
    assert refreshed.success_rows == 2  # imported 行数
    assert refreshed.failed_rows == 1  # error 行数
    assert refreshed.processed_rows == 3
    assert refreshed.status == "partial_failed"  # 部分成功
    assert refreshed.error_summary == {"missing_required": 1}
