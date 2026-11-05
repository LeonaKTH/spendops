"""SpendOps G2 独立导入 Worker。

独立进程（``python -m app.worker``），从 PostgreSQL 持久任务队列认领导入任务并执行。

可靠性语义：
- 任务状态持久化在 import_tasks 表，Worker 退出不丢失。
- 认领使用 ``FOR UPDATE SKIP LOCKED``，多个 Worker 不会重复处理同一任务。
- 认领超时（claim_timeout 秒）未完成的任务可被其他 Worker 重新认领。
- 每处理一个任务重开一个 session，数据库异常不会让 Worker 崩溃退出。
- 收到 SIGINT/SIGTERM 优雅退出，当前已认领任务会因超时被后续认领。
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import uuid

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [worker] %(message)s",
)
logger = logging.getLogger("spendops.worker")

# 无任务时的轮询间隔（秒）。
POLL_INTERVAL = 2.0
# 处理任务时检查取消的频率（每 N 个单据检查一次）。
CANCEL_CHECK_EVERY = 20


async def _run_once(worker_id: str) -> bool:
    """认领并处理一个任务，返回是否处理了任务。"""
    from app.db.session import SessionLocal
    from app.services.importing import importer, tasks

    async with SessionLocal() as session:
        task = await tasks.claim_task(session, worker_id)
        if task is None:
            return False

        # 立即提取局部变量：run_import 内的 rollback 会使 task 对象过期，
        # 之后访问 task.id 会触发懒加载导致 MissingGreenlet。
        task_id = str(task.id)
        task_type = task.task_type
        total_rows = task.total_rows
        logger.info("认领任务 %s (type=%s, %d 行)", task_id, task_type, total_rows)

        async def on_progress(_processed: int) -> bool:
            """心跳：续租（防被误判超时重认领）+ 取消检查。

            返回 False 表示应中止导入（所有权丢失或任务已取消）。
            """
            if not await tasks.renew_claim(session, task_id, worker_id):
                logger.warning("任务 %s 所有权丢失，中止处理", task_id)
                return False
            if await tasks.is_task_cancelled(session, task_id):
                logger.info("任务 %s 已被取消，中止处理", task_id)
                return False
            return True

        try:
            rows = await tasks.load_import_rows(session, task_id)
            success, failed, summary = await importer.run_import(
                session, task_type, rows, on_progress
            )
            await tasks.finish_task(session, task_id)
            logger.info(
                "任务 %s 完成：成功 %d 行，失败 %d 行，状态=%s",
                task_id, success, failed,
                "completed" if failed == 0 else ("partial_failed" if success else "failed"),
            )
        except importer.ImportInterrupted:
            # 取消或所有权丢失：不更新任务统计，由取消状态或新 Worker 负责终态。
            logger.info("任务 %s 被中断，不更新终态", task_id)
        except Exception as exc:  # 不可恢复错误：标记任务失败，Worker 继续。
            logger.exception("任务 %s 执行失败", task_id)
            await tasks.fail_task(session, task_id, str(exc))
        return True


async def _run_forever() -> None:
    worker_id = f"worker-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    logger.info("Worker 启动：%s", worker_id)

    stop = asyncio.Event()

    def _handle_signal(signum: int, _frame) -> None:
        logger.info("收到信号 %s，准备退出", signum)
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal, sig, None)
        except NotImplementedError:  # Windows 不支持 add_signal_handler
            signal.signal(sig, _handle_signal)

    while not stop.is_set():
        try:
            processed = await _run_once(worker_id)
            if not processed:
                # 无任务，等待后再轮询。等待期间若收到停止信号则提前返回。
                try:
                    await asyncio.wait_for(stop.wait(), timeout=POLL_INTERVAL)
                except asyncio.TimeoutError:
                    pass
        except Exception:
            logger.exception("Worker 循环异常")
            await asyncio.sleep(POLL_INTERVAL)

    logger.info("Worker 退出：%s", worker_id)


def main() -> int:
    try:
        asyncio.run(_run_forever())
    except KeyboardInterrupt:
        logger.info("Worker 被键盘中断")
    return 0


if __name__ == "__main__":
    sys.exit(main())
