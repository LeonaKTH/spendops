"""SpendOps 端到端 API 验证脚本（真实 PostgreSQL）。

用 httpx ASGITransport 在内存中启动 FastAPI app（连测试库 spendops_test），
执行完整采购业务闭环并断言结果。可用作 G1 端到端证据，也可在 CI 中运行。

运行：
    cd backend
    python scripts/e2e_api_test.py
"""

from __future__ import annotations

import os
import sys

# 把 backend 目录加入 sys.path，使脚本可从任意位置运行。
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)


def _load_dotenv() -> dict[str, str]:
    """手动读取 backend/.env（不依赖第三方库），返回键值对。"""
    env: dict[str, str] = {}
    env_path = os.path.join(BACKEND_DIR, ".env")
    if not os.path.exists(env_path):
        return env
    with open(env_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


_dotenv = _load_dotenv()

# 必须在 import app 之前设置，让 app.db.session 使用测试库。
# 优先环境变量，其次 .env 的 TEST_DATABASE_URL；两者都缺则报错退出。
_test_url = os.environ.get("SPENDOPS_TEST_DATABASE_URL") or _dotenv.get("TEST_DATABASE_URL")
if not _test_url:
    raise SystemExit(
        "未配置测试库连接：请设置 SPENDOPS_TEST_DATABASE_URL 或 .env 的 TEST_DATABASE_URL。"
    )
if not _test_url.rsplit("/", 1)[-1].endswith("_test"):
    raise SystemExit(f"拒绝在非测试库上运行端到端脚本：{_test_url}")
os.environ["DATABASE_URL"] = _test_url
os.environ.setdefault("JWT_SECRET", _dotenv.get("JWT_SECRET", ""))

import asyncio  # noqa: E402
import uuid  # noqa: E402

import httpx  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_PASSWORD = _dotenv.get("ADMIN_PASSWORD", "admin123456")

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"


def check(name: str, condition: bool, detail: str = ""):
    mark = PASS if condition else FAIL
    print(f"  {mark} {name}" + (f"  -> {detail}" if detail and not condition else ""))
    return condition


async def main() -> int:
    results: list[bool] = []
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. 登录 admin（seed 在 lifespan 里创建）
            print("\n[1] 登录与权限")
            r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
            results.append(check("admin 登录", r.status_code == 200, f"status={r.status_code}"))
            admin_cookies = r.cookies

            # 2. 创建供应商
            print("\n[2] 供应商")
            code = f"E2E-{uuid.uuid4().hex[:6]}"
            r = await client.post(
                "/api/v1/suppliers",
                json={"code": code, "name": "端到端供应商", "contact_name": "张三", "contact_phone": "13800000000"},
                cookies=admin_cookies,
            )
            results.append(check("创建供应商", r.status_code == 201, f"status={r.status_code}"))
            sup = r.json()
            sup_id = sup["id"]

            # 3. 创建采购订单（2 明细）
            print("\n[3] 采购订单")
            r = await client.post(
                "/api/v1/purchase-orders",
                json={
                    "order_no": f"PO-{uuid.uuid4().hex[:6]}",
                    "supplier_id": sup_id,
                    "order_date": "2026-01-10",
                    "lines": [
                        {"item_code": "A", "item_name": "物料A", "quantity": "10", "unit": "件", "unit_price": "100", "tax_rate": "0"},
                        {"item_code": "B", "item_name": "物料B", "quantity": "5", "unit": "件", "unit_price": "200", "tax_rate": "0"},
                    ],
                },
                cookies=admin_cookies,
            )
            results.append(check("创建订单", r.status_code == 201, f"status={r.status_code}"))
            order = r.json()
            results.append(check("金额计算正确(2000)", order["totalAmount"] == "2000.00", order["totalAmount"]))
            line1_id = order["lines"][0]["id"]

            # 4. 部分收货
            print("\n[4] 收货")
            r = await client.post(
                "/api/v1/goods-receipts",
                json={
                    "receipt_no": f"GR-{uuid.uuid4().hex[:6]}",
                    "order_id": order["id"],
                    "receipt_date": "2026-01-15",
                    "lines": [{"order_line_id": line1_id, "quantity": "4"}],
                },
                cookies=admin_cookies,
            )
            results.append(check("部分收货", r.status_code == 201, f"status={r.status_code}"))

            # 5. 超量收货应被拒绝
            r = await client.post(
                "/api/v1/goods-receipts",
                json={
                    "receipt_no": f"GR-OVER-{uuid.uuid4().hex[:6]}",
                    "order_id": order["id"],
                    "receipt_date": "2026-01-16",
                    "lines": [{"order_line_id": line1_id, "quantity": "7"}],
                },
                cookies=admin_cookies,
            )
            results.append(check("超量收货被拒绝(400)", r.status_code == 400, f"status={r.status_code}"))

            # 6. 录入发票（追溯订单明细）
            print("\n[5] 发票")
            r = await client.post(
                "/api/v1/purchase-invoices",
                json={
                    "invoice_no": f"INV-{uuid.uuid4().hex[:6]}",
                    "order_id": order["id"],
                    "supplier_id": sup_id,
                    "invoice_date": "2026-01-20",
                    "lines": [{"order_line_id": line1_id, "item_name": "物料A", "quantity": "10", "unit_price": "100", "tax_rate": "0.13"}],
                },
                cookies=admin_cookies,
            )
            results.append(check("录入发票", r.status_code == 201, f"status={r.status_code}"))
            inv = r.json()
            results.append(check("税额正确(130)", inv["taxAmount"] == "130.00", inv["taxAmount"]))

            # 7. 订单详情反映状态与关联
            print("\n[6] 状态与关联")
            r = await client.get(f"/api/v1/purchase-orders/{order['id']}", cookies=admin_cookies)
            detail = r.json()
            results.append(check("订单状态部分收货", detail["status"] == "partially_received", detail["status"]))
            results.append(check("已收数量=4", detail["lines"][0]["receivedQty"] == "4.000", detail["lines"][0]["receivedQty"]))
            results.append(check("已开票数量=10", detail["lines"][0]["invoicedQty"] == "10.000", detail["lines"][0]["invoicedQty"]))

            # 8. 未授权访问（用独立 client，无登录 cookie）
            print("\n[7] 权限")
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as anon:
                r = await anon.post("/api/v1/suppliers", json={"code": "EVIL", "name": "越权"})
                results.append(check("未登录写操作被拒绝(401)", r.status_code == 401, f"status={r.status_code}"))

            # 创建 viewer 并验证只读权限
            viewer_name = f"v{uuid.uuid4().hex[:4]}"
            viewer_pw = uuid.uuid4().hex
            await client.post(
                "/api/v1/admin/users",
                json={"username": viewer_name, "password": viewer_pw, "role": "viewer", "display_name": "只读"},
                cookies=admin_cookies,
            )
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as viewer:
                r = await viewer.post(
                    "/api/v1/auth/login",
                    json={"username": viewer_name, "password": viewer_pw},
                )
                results.append(check("viewer 登录", r.status_code == 200, f"status={r.status_code}"))
                r = await viewer.post("/api/v1/suppliers", json={"code": "EVIL", "name": "越权"})
                results.append(check("viewer 写操作被拒绝(403)", r.status_code == 403, f"status={r.status_code}"))
                r = await viewer.get("/api/v1/suppliers")
                results.append(check("viewer 读操作允许(200)", r.status_code == 200, f"status={r.status_code}"))

    passed = sum(results)
    total = len(results)
    print(f"\n{'='*50}")
    print(f"端到端结果：{passed}/{total} 通过")
    print(f"{'='*50}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
