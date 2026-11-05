"""G4 异步导入性能实测：1 万行供应商导入，记录上传/校验/Worker 处理耗时与吞吐。

用法：先启动后端（连 perf 库）与 Worker，再运行本脚本。
"""

from __future__ import annotations

import os
import sys
import time

import httpx

BASE = os.environ.get("SPENDOPS_BASE_URL", "http://127.0.0.1:8002")
ADMIN = {"username": "admin", "password": "admin123456"}

TOTAL = 10_000
GOOD = TOTAL - 20  # 9980 正确 + 10 缺名称 + 10 重复编码


def build_csv() -> bytes:
    lines = ["供应商编码,供应商名称,联系人"]
    for i in range(1, GOOD + 1):
        lines.append(f"IMP-{i:05d},导入供应商{i:05d},联系人{i}")
    for i in range(GOOD + 1, GOOD + 11):
        lines.append(f"IMP-{i:05d},,联系人{i}")  # 缺名称
    for i in range(1, 11):
        lines.append(f"IMP-{i:05d},重复供应商{i},重复")  # 重复编码
    return ("\n".join(lines) + "\n").encode("utf-8")


def main() -> int:
    csv = build_csv()
    print(f"生成 CSV：{len(csv)} 字节，{TOTAL} 行（含 20 行错误）")

    with httpx.Client(base_url=BASE, timeout=300.0) as client:
        r = client.post("/api/v1/auth/login", json=ADMIN)
        assert r.status_code == 200, f"登录失败 {r.status_code}"

        # 上传（解析 + 字段校验 + 暂存）
        t0 = time.time()
        r = client.post(
            "/api/v1/imports",
            data={"task_type": "supplier"},
            files={"file": ("suppliers_10k.csv", csv, "text/csv")},
        )
        upload_elapsed = time.time() - t0
        if r.status_code != 200:
            print(f"上传失败：{r.status_code} {r.text[:200]}")
            return 1
        task = r.json()
        print(f"上传耗时：{upload_elapsed:.2f}s（解析+字段校验+暂存）")
        print(f"任务 {task['id'][:8]}：字段级错误 {task['failedRows']} 行")

        # 确认导入
        r = client.post(f"/api/v1/imports/{task['id']}/confirm")
        assert r.status_code == 200, f"确认失败 {r.status_code}"
        t1 = time.time()

        # 等待 Worker 完成
        deadline = time.time() + 300
        while time.time() < deadline:
            cur = client.get(f"/api/v1/imports/{task['id']}").json()
            if cur["status"] in ("completed", "partial_failed", "failed"):
                break
            time.sleep(2)
        worker_elapsed = time.time() - t1

        final = client.get(f"/api/v1/imports/{task['id']}").json()
        print(f"Worker 处理耗时：{worker_elapsed:.2f}s")
        print(f"最终状态：{final['status']}")
        print(f"总 {final['totalRows']} 行，成功 {final['successRows']}，失败 {final['failedRows']}")
        print(f"吞吐：{final['successRows'] / worker_elapsed:.0f} 行/秒（Worker 逐单据事务）")
        print(f"错误摘要：{final['errorSummary']}")

        # 验证数据库入库
        r = client.get("/api/v1/suppliers")
        total_suppliers = len(r.json())
        print(f"数据库供应商总数：{total_suppliers}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
