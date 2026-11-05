"""把 sample_data/ 中的示例数据导入一个正在运行的 ProcureBI 实例。

用法（Windows，项目根目录）：
    backend/.venv/Scripts/python.exe scripts/seed_demo_data.py \
        --base-url http://127.0.0.1:8000 --password admin123456

脚本以管理员账号登录，然后通过公开 API 上传 Excel 与合同文档；
已存在同名来源文件的数据集 / 文档会被跳过，可重复执行。
"""

from __future__ import annotations

import argparse
import mimetypes
import sys
from pathlib import Path

import httpx

TABULAR = {".xlsx", ".xls", ".csv"}
DOCUMENTS = {".pdf", ".docx", ".txt"}

MIME_OVERRIDES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".csv": "text/csv",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导入 ProcureBI 示例数据")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="站点地址")
    parser.add_argument("--username", default="admin", help="管理员用户名")
    parser.add_argument("--password", required=True, help="管理员密码")
    parser.add_argument(
        "--sample-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "sample_data",
        help="示例数据目录",
    )
    return parser.parse_args()


def upload(client: httpx.Client, path: Path, endpoint: str, existing: set[str]) -> str:
    if path.name in existing:
        return "skip"
    mime = MIME_OVERRIDES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0]
    response = client.post(
        endpoint,
        files={"file": (path.name, path.read_bytes(), mime or "application/octet-stream")},
    )
    if response.status_code not in (200, 201):
        print(f"  ✗ {path.name}: HTTP {response.status_code} {response.text[:300]}")
        return "fail"
    return "ok"


def main() -> int:
    args = parse_args()
    base = args.base_url.rstrip("/")
    sample_dir = args.sample_dir

    if not sample_dir.is_dir():
        print(f"示例数据目录不存在：{sample_dir}")
        return 1

    with httpx.Client(base_url=base, timeout=300, follow_redirects=False) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": args.username, "password": args.password},
        )
        if login.status_code != 200:
            print(f"登录失败：HTTP {login.status_code} {login.text[:300]}")
            return 1

        datasets = client.get("/api/v1/datasets").json()
        documents = client.get("/api/v1/documents").json()
        existing_datasets = {item["sourceFile"] for item in datasets}
        existing_documents = {item["sourceFile"] for item in documents}

        print(f"已存在 {len(existing_datasets)} 个数据集、{len(existing_documents)} 份文档。")

        counts = {"ok": 0, "skip": 0, "fail": 0}
        for path in sorted(sample_dir.iterdir()):
            suffix = path.suffix.lower()
            if suffix in TABULAR:
                endpoint = "/api/v1/datasets"
                existing = existing_datasets
            elif suffix in DOCUMENTS:
                endpoint = "/api/v1/documents"
                existing = existing_documents
            else:
                continue

            result = upload(client, path, endpoint, existing)
            counts[result] += 1
            marker = {"ok": "✓", "skip": "·", "fail": "✗"}[result]
            print(f"  {marker} {path.name} ({result})")

    print(f"完成：新增 {counts['ok']}，跳过 {counts['skip']}，失败 {counts['fail']}。")
    return 0 if counts["fail"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
