"""G2 1 万行导入实测：记录上传耗时、Worker 处理耗时、成功/失败行数、入库数量。

流程：生成 1 万行供应商 CSV（含 10 行错误）→ 上传 → 确认 → 等待 Worker → 校验入库数量。
运行前需启动后端（连测试库）与 Worker。
"""

from __future__ import annotations

import io
import os
import sys
import time

import httpx

BASE = os.environ.get("SPENDOPS_BASE_URL", "http://127.0.0.1:8000")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123456")

TOTAL = 10_000
GOOD = TOTAL - 10  # 9990 个正确供应商 + 5 个缺名称 + 5 个重复编码 = 10000 行


def build_csv() -> bytes:
    lines = ["供应商编码,供应商名称,联系人"]
    # 正确行
    for i in range(1, GOOD + 1):
        lines.append(f"S{i:05d},供应商{i:05d},联系人{i}")
    # 错误行：10 个缺名称
    for i in range(GOOD + 1, GOOD + 6):
        lines.append(f"S{i:05d},,联系人{i}")
    # 错误行：5 个重复编码（与前面的重复）
    for i in range(1, 6):
        lines.append(f"S{i:05d},重复供应商{i},重复联系人")
    return ("\n".join(lines) + "\n").encode("utf-8")


def main() -> int:
    csv = build_csv()
    print(f"生成 CSV：{len(csv)} 字节，{TOTAL} 行（含 10 行错误）")

    with httpx.Client(base_url=BASE, timeout=120.0) as client:
        r = client.post("/api/v1/auth/login", json={
            "username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        assert r.status_code == 200, f"登录失败 {r.status_code}"

        # 上传
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
        print(f"上传耗时：{upload_elapsed:.2f}s（解析 + 字段校验 + 暂存）")
        print(f"任务：{task['id']}，字段级错误 {task['failedRows']} 行")

        # 确认
        r = client.post(f"/api/v1/imports/{task['id']}/confirm")
        assert r.status_code == 200, f"确认失败 {r.status_code}"
        t1 = time.time()

        # 等待 Worker
        deadline = time.time() + 120
        while time.time() < deadline:
            r = client.get(f"/api/v1/imports/{task['id']}")
            cur = r.json()
            if cur["status"] in ("completed", "partial_failed", "failed"):
                break
            time.sleep(1)
        worker_elapsed = time.time() - t1

        final = client.get(f"/api/v1/imports/{task['id']}").json()
        print(f"Worker 处理耗时：{worker_elapsed:.2f}s")
        print(f"最终状态：{final['status']}")
        print(f"总行数：{final['totalRows']}，成功 {final['successRows']}，失败 {final['failedRows']}")
        print(f"错误摘要：{final['errorSummary']}")

        # 校验入库数量（通过采购 API 查供应商数）
        r = client.get("/api/v1/suppliers")
        supplier_count = len(r.json())
        print(f"数据库供应商总数：{supplier_count}")

        # 预期：正确行 9990 全部成功；缺名称 5 行字段级失败；重复编码 5 行业务级失败。
        expected_success = GOOD
        expected_fail = 10
        print(f"\n预期：成功 {expected_success}，失败 {expected_fail}")
        print(f"结果：成功 {final['successRows']}，失败 {final['failedRows']}")

        return 0


if __name__ == "__main__":
    sys.exit(main())
