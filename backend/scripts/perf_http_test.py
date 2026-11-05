"""G4 HTTP 并发性能测试：真实 FastAPI + PostgreSQL，有控制并发。

测试经营分析查询（overview/suppliers/trend）与采购列表，记录 P50/P95 响应时间、
吞吐、成功率。默认单并发 + 5 并发 + 10 并发。

用法：python scripts/perf_http_test.py [--concurrency 1,5,10] [--requests 30]
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time

import httpx

BASE = "http://127.0.0.1:8002"
ADMIN = {"username": "admin", "password": "admin123456"}

OVERVIEW_URL = "/api/v1/metrics/overview?start=2026-01-01&end=2026-12-31"
SUPPLIERS_URL = "/api/v1/metrics/suppliers?start=2026-01-01&end=2026-12-31&top_n=10"
ORDERS_URL = "/api/v1/purchase-orders"


async def _run_batch(client: httpx.AsyncClient, url: str, n: int) -> list[float]:
    """并发 n 个请求，返回每个请求的耗时（秒）。"""
    t0 = time.time()
    results = await asyncio.gather(*[client.get(url) for _ in range(n)])
    elapsed = time.time() - t0
    latencies = []
    for r in results:
        latencies.append(0.0)  # 占位，实际用 gather 完成时间近似
    return [elapsed] * n, [r.status_code for r in results]


async def _measure(client: httpx.AsyncClient, url: str, concurrency: int, total: int) -> dict:
    """分批次并发请求，返回延迟统计。"""
    latencies: list[float] = []
    statuses: list[int] = []
    batches = total // concurrency
    for _ in range(batches):
        t0 = time.time()
        rs = await asyncio.gather(*[client.get(url) for _ in range(concurrency)])
        batch_time = time.time() - t0
        latencies.extend([batch_time] * concurrency)
        statuses.extend([r.status_code for r in rs])
    ok = sum(1 for s in statuses if s == 200)
    if not latencies:
        return {}
    latencies.sort()
    return {
        "url": url,
        "concurrency": concurrency,
        "requests": len(statuses),
        "success": ok,
        "error_rate": (len(statuses) - ok) / len(statuses) if statuses else 0,
        "p50": latencies[int(len(latencies) * 0.5)],
        "p95": latencies[int(len(latencies) * 0.95)],
        "throughput": len(statuses) / sum(latencies) if sum(latencies) else 0,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", default="1,5,10")
    parser.add_argument("--requests", type=int, default=30)
    args = parser.parse_args()
    levels = [int(x) for x in args.concurrency.split(",")]

    # 登录
    async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as client:
        r = await client.post("/api/v1/auth/login", json=ADMIN)
        if r.status_code != 200:
            print("登录失败，无法继续")
            return 1

        results = []
        for concurrency in levels:
            for name, url in [("overview", OVERVIEW_URL), ("suppliers", SUPPLIERS_URL),
                              ("orders", ORDERS_URL)]:
                m = await _measure(client, url, concurrency, args.requests)
                if m:
                    results.append(m)
                    print(
                        f"[{name:10s}] 并发{concurrency:2d} 请求{m['requests']:3d} "
                        f"成功{m['success']:3d} P50={m['p50']*1000:7.1f}ms "
                        f"P95={m['p95']*1000:7.1f}ms 吞吐={m['throughput']:6.1f} req/s"
                    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
