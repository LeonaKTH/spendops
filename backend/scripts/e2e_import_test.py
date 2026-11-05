"""G2 端到端导入验证脚本。

连接真实后端（连测试库），执行：登录 -> 上传供应商 -> 上传采购订单 ->
确认 -> 等待 Worker 入库 -> 校验业务表数据。

用法：先启动后端（DATABASE_URL 指向测试库）与 Worker，再运行本脚本。
"""

from __future__ import annotations

import os
import sys
import time

import httpx

BASE = os.environ.get("SPENDOPS_BASE_URL", "http://127.0.0.1:8001")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123456")

SUPPLIER_CSV = (
    "供应商编码,供应商名称,联系人,联系电话\n"
    "SUP-E2E-1,端到端供应商甲,张三,13800000001\n"
    "SUP-E2E-2,端到端供应商乙,李四,13800000002\n"
    "SUP-E2E-BAD,,王五,13800000003\n"  # 缺名称 -> 字段级错误
).encode("utf-8")

ORDER_CSV = (
    "采购订单号,供应商编码,下单日期,物料编码,物料名称,数量,单位,单价\n"
    "PO-E2E-1,SUP-E2E-1,2026-01-10,A001,物料A,10,件,1.50\n"
    "PO-E2E-1,SUP-E2E-1,2026-01-10,B002,物料B,5,件,2.25\n"
    "PO-E2E-2,SUP-E2E-NOPE,2026-01-11,C003,物料C,3,件,5.00\n"  # 供应商不存在 -> 业务级错误
).encode("utf-8")

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
results: list[bool] = []


def check(name: str, cond: bool, detail: str = ""):
    results.append(cond)
    mark = PASS if cond else FAIL
    print(f"  {mark} {name}" + (f"  -> {detail}" if not cond else ""))


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=30.0) as client:
        # 1. 登录
        r = client.post("/api/v1/auth/login", json={
            "username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        check("登录", r.status_code == 200, f"status={r.status_code}")
        if r.status_code != 200:
            print("登录失败，无法继续")
            return 1

        # 2. 上传供应商
        r = client.post(
            "/api/v1/imports",
            data={"task_type": "supplier"},
            files={"file": ("suppliers.csv", SUPPLIER_CSV, "text/csv")},
        )
        check("上传供应商任务", r.status_code == 200, f"status={r.status_code} {r.text[:120]}")
        sup_task = r.json()
        check("供应商任务字段级错误=1", sup_task["failed_rows"] == 1, f"failed={sup_task['failed_rows']}")

        # 3. 上传采购订单
        r = client.post(
            "/api/v1/imports",
            data={"task_type": "purchase_order"},
            files={"file": ("orders.csv", ORDER_CSV, "text/csv")},
        )
        check("上传订单任务", r.status_code == 200, f"status={r.status_code}")
        order_task = r.json()

        # 4. 确认两个任务（进入 importing，等待 Worker 处理）
        for task in (sup_task, order_task):
            r = client.post(f"/api/v1/imports/{task['id']}/confirm")
            check(f"确认任务 {task['id'][:8]}", r.status_code == 200, f"status={r.status_code}")

        # 5. 轮询等待 Worker 完成
        deadline = time.time() + 30
        final_statuses = {}
        while time.time() < deadline:
            r1 = client.get(f"/api/v1/imports/{sup_task['id']}").json()
            r2 = client.get(f"/api/v1/imports/{order_task['id']}").json()
            if r1["status"] in ("completed", "partial_failed", "failed") and \
               r2["status"] in ("completed", "partial_failed", "failed"):
                final_statuses = {"supplier": r1, "order": r2}
                break
            time.sleep(1)

        sup_final = final_statuses.get("supplier", {})
        order_final = final_statuses.get("order", {})
        check("供应商任务完成", sup_final.get("status") == "completed",
              f"status={sup_final.get('status')}")
        check("订单任务部分失败", order_final.get("status") == "partial_failed",
              f"status={order_final.get('status')}")
        check("订单任务成功2行失败1行",
              order_final.get("success_rows") == 2 and order_final.get("failed_rows") == 1,
              f"success={order_final.get('success_rows')} failed={order_final.get('failed_rows')}")

        # 6. 查询订单错误报告
        r = client.get(f"/api/v1/imports/{order_task['id']}/errors")
        check("订单错误报告可查", r.status_code == 200 and r.json()["total"] >= 1,
              f"total={r.json().get('total') if r.status_code == 200 else 'N/A'}")
        if r.status_code == 200:
            err = r.json()["errors"][0]
            check("错误类型=供应商不存在", err["errorType"] == "supplier_not_found",
                  f"type={err['errorType']}")

        # 7. 校验业务表数据（通过采购 API 查询订单）
        r = client.get("/api/v1/purchase-orders")
        orders = r.json()["items"]  # G4 分页后返回 {items, total}
        po1 = [o for o in orders if o["orderNo"] == "PO-E2E-1"]
        check("订单 PO-E2E-1 已入库", len(po1) == 1, f"found={len(po1)}")
        if po1:
            check("订单金额=26.25 (Decimal精确)", po1[0]["totalAmount"] == "26.25",
                  f"total={po1[0]['totalAmount']}")

        r = client.get("/api/v1/suppliers")
        suppliers = r.json()
        check("供应商 SUP-E2E-1 已入库",
              any(s["code"] == "SUP-E2E-1" for s in suppliers))
        check("供应商 SUP-E2E-BAD 未入库(错误行)",
              not any(s["code"] == "SUP-E2E-BAD" for s in suppliers))

    passed = sum(results)
    print(f"\n结果：{passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
